#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR Fix mode: usa analisi reviewer + snapshot dal ThreadLedger per generare il prompt.
Priorità: leggere dal ledger; fallback: sticky comment & filesystem.
"""
import re
import os
import subprocess
from typing import TYPE_CHECKING, List, Dict, Tuple
from collections import Counter
from pathlib import Path

from utils import get_repo_language, get_preferred_model, FullFileRefacer
from dev_core.path_isolation import compute_project_root_for_pr, ensure_dir
from dev_core import (
    enforce_all,
    constraints_block, diff_format_block, files_list_block, findings_block, snapshots_block,
    collect_snapshots, comment_with_llm_preview, normalize_diff_headers_against_fs,
    coerce_unified_diff
)
from state import (
    ThreadLedger, DiffRecorder,
    preflight_git_apply_check, preflight_git_apply_threeway,
    detect_changed_files, post_commit_snapshot_update
)

if TYPE_CHECKING:
    from dev_core.github_client import GitHubClient
    from dev_core.git_operations import GitOperations
    from dev_core.diff_processor import DiffProcessor

SNAPSHOT_CHAR_LIMIT = 8000  # evita prompt eccessivi
MAX_SNAPSHOT_FILES = 20     # limita quanti file embeddare nel prompt

class PRFixMode:
    """Handles PR fix flow: reviewer feedback → in-place patches"""
    
    STICKY_TAG_TEMPLATE = "<!-- AI-REVIEWER:PR-{n} -->"
    
    def __init__(self, github_client: 'GitHubClient', git_ops: 'GitOperations', diff_processor: 'DiffProcessor'):
        self.github = github_client
        self.git = git_ops
        self.diff_processor = diff_processor
        # Feature flag per abilitare il full refacing come fallback robusto
        self._use_reface = os.getenv("REFACE_STRATEGY", "").lower() == "full"
        self._refacer = FullFileRefacer() if self._use_reface else None
    
    def run(self, pr_number: int) -> int:
        """
        Execute complete PR fix mode flow.
        Returns 0 on success, 1 on failure.
        """
        print(f"🔧 PR Fix Mode: Processing PR #{pr_number}")
        
        try:
            # Get PR details
            pr_data = self.github.get_pr(pr_number)
            branch = pr_data.get("head", {}).get("ref")
            if not branch:
                print("❌ Cannot get PR head branch.")
                return 1
            
            owner, repo = self.github.get_repo_info()
            base_sha = (pr_data.get("base", {}) or {}).get("sha") or "HEAD"
            head_sha = (pr_data.get("head", {}) or {}).get("sha")

            # === STATE / LEDGER BOOTSTRAP ===
            thread_id = f"PR-{pr_number}"
            ledger = ThreadLedger(thread_id)
            ledger.update(repo=f"{owner}/{repo}", base_sha=base_sha, branch=branch)
            ledger.append_decision(f"Fix: bootstrap repo={owner}/{repo} base={base_sha} head={head_sha}", actor="Fix")
 
            
            # === FEEDBACK REVIEWER: preferisci il LEDGER, fallback sticky comment ===
            reviewer_findings, prioritized_actions = self._load_reviewer_from_ledger(pr_number)
            if not reviewer_findings:
                reviewer_findings = self._read_reviewer_sticky(pr_number)
            changed_files = self.github.get_pr_files(pr_number)

            # Setup project root (env/body)  inferenza dai file se fallback pr-<n>
            project_root = compute_project_root_for_pr(pr_number, pr_data.get("body", ""))
            project_root = self._maybe_infer_root_from_files(project_root, changed_files)
            self.github.post_comment(pr_number, f"🔎 Using project root: `{project_root}` for PR-fix")
            print(f"📁 PROJECT_ROOT = {project_root}")
            ensure_dir(project_root)
            
            # Persist project root + scope nel ledger (senza creare snapshot qui)
            must_edit = sorted({
                (f.get("filename") or "").strip()
                for f in changed_files
                if (f.get("filename") or "").strip().startswith(project_root.rstrip("/") + "/")
            })
            ledger.set_scope(must_edit=must_edit, must_not_edit=[])
            ledger.update(project_root=project_root)
            ledger.append_decision(f"Fix: set project_root='{project_root}', scope={len(must_edit)} files", actor="Fix")
            ledger.set_status("fix_pending")

            # Checkout PR branch PRIMA di generare il diff: così leggiamo i file reali
            self._checkout_pr_branch(branch)
            
            # Config git per auto-fix whitespace nel repo corrente (preflight/apply)
            try:
                repo_root = Path(subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    text=True, capture_output=True, check=True
                ).stdout.strip())
                subprocess.run(
                    ["git", "config", "--local", "apply.whitespace", "fix"],
                    check=True, cwd=str(repo_root)
                )
            except Exception as _:
                repo_root = Path.cwd()

            # Raccogli SNAPSHOT: prima dal LEDGER (content_path), poi fallback a filesystem
            paths = [(f.get("filename", "") or "").strip() for f in changed_files[:MAX_SNAPSHOT_FILES]]
            snapshots = self._snapshots_from_ledger(pr_number, paths, SNAPSHOT_CHAR_LIMIT)
            if not snapshots:
                snapshots = collect_snapshots(
                    project_root,
                    paths=paths,
                    max_files=MAX_SNAPSHOT_FILES,
                    char_limit=SNAPSHOT_CHAR_LIMIT
                )

            # Genera + valida + applica con un retry locale (una sola volta) su errori formali
            retried = False
            rec = DiffRecorder()  # per audit artefatti di questa run
            while True:
                # Arricchisci i finding con le Prioritized Actions dal ledger (se presenti)
                enriched_findings = self._merge_findings_with_actions(reviewer_findings, prioritized_actions)
                diff = self._generate_fix_diff(project_root, pr_data, enriched_findings, changed_files, snapshots)
                if not diff or not diff.strip():
                    self.github.post_comment(
                        pr_number,
                        "ℹ️ Nessuna modifica proposta dall'LLM per i fix (diff vuoto)."
                    )
                    print("ℹ️ No-op: empty diff (PR-fix)")
                    return 0
                try:
                    # Log prompt/diff grezzo (per diagnosi)
                    rec.save_metadata(agent="Fix", thread_id=thread_id, pr_number=pr_number)
                    # Il prompt è costruito internamente da _build_pr_fix_prompt; registriamo il testo usato rigenerandolo qui
                    repo_lang = get_repo_language()
                    prompt_preview = self._build_pr_fix_prompt(project_root, pr_data, enriched_findings, changed_files, repo_lang, snapshots)
                    rec.record_prompt(prompt_preview)
                    rec.record_model_raw(diff)

                    # Harden: coercizza il diff per evitare "corrupt patch"
                    diff = coerce_unified_diff(diff)
                    
                    # Normalizza header (nuovi file/eliminazioni) rispetto al filesystem
                    diff = normalize_diff_headers_against_fs(diff, project_root)
                    # Enforce: tutto sotto project_root (eccezione README di progetto)
                    enforce_all(diff, project_root, allow_project_readme=True)

                    # Preflight: usa la vera repo_root per coerenza con Git
                    
                    print(f"\n=== DEBUG PREFLIGHT ===")
                    print(f"Project root: {project_root}")
                    print(f"Repo root: {repo_root}")
                    print(f"Branch: {branch}")
                    print(f"Must edit files: {must_edit}")
                    print(f"Diff size: {len(diff)} chars")
                    print(f"=== DIFF PREVIEW (first 1000 chars) ===")
                    print(diff[:1000])
                    print(f"=== END DIFF PREVIEW ===\n")
                    
                    ok, out, err = preflight_git_apply_check(diff, repo_root)
                    
                    print(f"\n=== PREFLIGHT RESULT ===")
                    print(f"OK: {ok}")
                    print(f"STDOUT: {out}")
                    print(f"STDERR: {err}")
                    
                    if not ok:
                        ok, out, err = preflight_git_apply_threeway(diff, repo_root)
                        print(f"3WAY OK: {ok}")
                        print(f"3WAY STDOUT: {out}")
                        print(f"3WAY STDERR: {err}")
                        
                    print(f"=== END PREFLIGHT DEBUG ===\n")

                    rec.record_preflight(out, err)
                    rec.record_payload(diff)
                    
                    # Persist esito preflight nel ledger
                    model_name = os.getenv("DEVELOPER_MODEL") or get_preferred_model("developer") or "gpt-4o-mini"
                    ledger.update(dev_fix={
                        "model": model_name,
                        "params": {"temperature": 0.2},  # se hai un valore reale, mettilo qui
                        "last_prompt_hash": str(hash(prompt_preview)),
                        "last_generated_patch": str(rec.dir / "payload_to_git.patch"),
                        "preflight": {"ok": ok, "stderr": err}
                    })
                    
                    if not ok:
                        print(f"=== FINAL PREFLIGHT FAILURE ===")
                        print(f"Both normal and 3way preflight failed")
                        print(f"Last error: {err}")
                        # 🔁 Fallback: prova il full refacing su un file target se abilitato
                        if self._refacer:
                            target_path = ""
                            for fp in must_edit:
                                if fp.startswith(project_root.rstrip("/") + "/"):
                                    target_path = fp
                                    break
                            if target_path:
                                print(f"🧠 Refacing fallback on {target_path}")
                                # Costruisci un ‘requirements’ semplice dal reviewer_findings + actions
                                req = "Address reviewer feedback and make the file pass syntax/format checks."
                                if reviewer_findings:
                                    req += f"\n\nReviewer Findings:\n{reviewer_findings}"
                                if prioritized_actions:
                                    actions_txt = "\n".join(f"- {a.get('title') or a.get('id')}" for a in prioritized_actions[:10])
                                    req += f"\n\nPrioritized Actions:\n{actions_txt}"
                                rf_ok = self._refacer.reface_file(
                                    file_path=target_path,
                                    requirements=req,
                                    review_history=[reviewer_findings or ""],
                                    style_guide="Follow project conventions"
                                )
                                if rf_ok:
                                    print("✅ Refacing fallback succeeded; skipping patch apply.")
                                    # Traccia nel ledger che si è passati al refacing
                                    ledger.append_decision(f"Fix: preflight failed → refacing applied on {target_path}", actor="Fix")
                                    diff = ""  # non usiamo più il diff, andiamo al commit/push
                                    break
                        # Se non c’è refacer o ha fallito, alza errore come prima
                        raise RuntimeError(f"Preflight failed; patch would not apply cleanly. Error: {err}")
                    
                    # Applica i fix
                    success = self._apply_fixes(diff)
                    if not success:
                        raise RuntimeError("git apply failed")
                    
                    break
                except Exception as e:
                    msg = str(e).lower()
                    
                    # stampa riga incriminata, se presente nel messaggio di git
                    try:
                        m = re.search(r"line\s+(\d+)", msg)
                        if m:
                            bad = int(m.group(1))
                            lines = diff.splitlines()
                            start = max(0, bad - 4)
                            end = min(len(lines), bad + 3)
                            print("=== PATCH CONTEXT AROUND ERROR ===")
                            for i in range(start, end):
                                # mostra numero di riga 1-based + contenuto
                                print(f"{i+1:04d} | {lines[i]!r}")
                            print("=== END PATCH CONTEXT ===")
                    except Exception:
                        pass

                    retriable = any(k in msg for k in ("missing unified hunk", "malformed patch", "corrupt patch", "git apply failed"))
                    if retriable and not retried:
                        retried = True
                        
                        # STRICT FULL-FILE RETRY: usa contenuto ATTUALE come base e vieta rinomini
                        repo_lang = get_repo_language()
                        curr_content = ""
                        target_path = ""
                        try:
                            # prendi il primo file sotto project_root dai changed_files del PR
                            for item in changed_files:
                                fp = (item.get("filename") or "").strip()
                                if fp.startswith(f"{project_root}/"):
                                    target_path = fp
                                    break
                            if target_path:
                                with open(target_path, "r", encoding="utf-8", errors="ignore") as fh:
                                    curr_content = fh.read()
                        except Exception:
                            curr_content = ""

                        # 🔁 Prima del retry testuale, se abilitato prova il refacing diretto sul file target
                        if self._refacer and target_path:
                            print(f"🧠 Trying refacing before STRICT FULL-FILE diff retry on {target_path}")
                            req = "Apply the requested fixes reliably by rewriting the complete file."
                            if reviewer_findings:
                                req += f"\n\nReviewer Findings:\n{reviewer_findings}"
                            rf_ok = self._refacer.reface_file(
                                file_path=target_path,
                                requirements=req,
                                review_history=[reviewer_findings or ""],
                                style_guide="Follow project conventions"
                            )
                            if rf_ok:
                                print("✅ Refacing succeeded; skipping STRICT FULL-FILE diff retry.")
                                diff = ""  # salta il retry patch: andiamo al commit/push
                                break

                        prompt = self._build_pr_fix_prompt(
                            project_root, pr_data, enriched_findings, changed_files, repo_lang, snapshots
                        )
                        prompt += (
                            "\n\n# RETRY INSTRUCTIONS (STRICT FULL-FILE)\n"
                            "- Your previous patch failed (corrupt/misaligned hunk). DO NOT emit partial hunks.\n"
                            "- Emit ONE fenced unified diff with a FULL-FILE replacement for EACH modified file.\n"
                            "- Use headers exactly as: '--- a/<path>' and '+++ b/<same path>'.\n"
                            "- The final file must be complete and runnable; DO NOT rename existing identifiers unless explicitly requested.\n"
                            f"- Base yourself on CURRENT content of {target_path} below and apply the requested changes:\n"
                            f"\n<CURRENT {target_path}>\n{curr_content}\n</CURRENT>\n"
                        )
                        diff = self.diff_processor.process_full_cycle(prompt, project_root)
                        diff = coerce_unified_diff(diff)
                        
                        # Torna al loop per normalizzare/enforce/apply
                        continue
                    # Log failure nel ledger e rilancia
                    ledger.append_decision(f"Fix: generation/apply retry needed: {e}", actor="Fix")
                    raise
            
            # Commit and push fixes
            self._commit_and_push_fixes(pr_number, branch)

            # === SNAPSHOT UPDATE AFTER COMMIT (centralizzato) ===
            new_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                text=True, capture_output=True, check=True
            ).stdout.strip()

            changed_files = detect_changed_files(
                repo_root=repo_root, commit_from="HEAD~1", commit_to="HEAD", diff_text=diff
            )

            post_commit_snapshot_update(
                repo_root=repo_root,
                ledger=ledger,
                commit=new_commit,
                changed_files=changed_files,
                context="Fix",
                actor="Fix",
            )

            # Stato → CI
            ledger.update(dev_fix={"applied_commit": new_commit})
            ledger.set_status("ci_running")
            ledger.append_decision("Fix: patch applied and pushed; status→ci_running", actor="Fix")
            
            # === ALWAYS ADD 'need-review' LABEL AFTER FIX PUSH ===
            try:
                from utils import add_labels
                owner, repo = self.github.get_repo_info()
                add_labels(owner, repo, pr_number, ["need-review"])
            except Exception as e:
                print(f"⚠️ Label add failed on PR-fix: {e}")
    
            
            print(f"✅ PR #{pr_number} fixes applied successfully")
            return 0
            
        except Exception as e:
            # Diagnostica uniforme
            comment_with_llm_preview(self.github, pr_number, "LLM diff validation failed in PR-fix mode", e, self.diff_processor)
            print(f"❌ PR fix mode failed: {e}")
            return 1
    
    def _maybe_infer_root_from_files(self, project_root: str, changed_files: List[Dict]) -> str:
        """
        Se la root è nel fallback 'projects/pr-<num>', prova a dedurla dai file del PR:
        es. 'projects/math/math_utils.py' -> 'projects/math'
        """
        try:
            if not project_root or project_root.startswith("projects/pr-"):
                candidates = []
                for f in changed_files or []:
                    path = f.get("filename", "")
                    m = re.match(r"^projects/([^/]+)/", path)
                    if m:
                        candidates.append(f"projects/{m.group(1)}")
                if candidates:
                    deduced = Counter(candidates).most_common(1)[0][0]
                    print(f"🔎 Deduced project root from files: {deduced}")
                    return deduced
        except Exception as _:
            pass
        return project_root
    
    def _read_reviewer_sticky(self, pr_number: int) -> str:
        """Read sticky reviewer comment with findings"""
        tag = self.STICKY_TAG_TEMPLATE.format(n=pr_number)
        
        try:
            comments = self.github.get_pr_comments(pr_number)
        except Exception as e:
            print(f"⚠️ Cannot load PR comments: {e}")
            return ""
        
        for comment in comments:
            body = comment.get("body", "")
            if tag in body:
                # Extract content between sticky markers
                match = re.search(
                    r"<!-- reviewer:sticky:start -->(.*?)<!-- reviewer:sticky:end -->", 
                    body, 
                    re.DOTALL
                )
                return match.group(1).strip() if match else body
        
        # Fallback: cerca i marker su qualsiasi commento
        for comment in comments:
            body = comment.get("body", "")
            match = re.search(r"<!-- reviewer:sticky:start -->(.*?)<!-- reviewer:sticky:end -->", body, re.DOTALL)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _build_pr_fix_prompt(self, project_root: str, pr_data: Dict, reviewer_findings: str, changed_files: List[Dict], repo_lang: str, snapshots: List[Tuple[str, str]]) -> str:
        """Build prompt per PR-fix usando i blocchi condivisi"""
        title = pr_data.get("title", "")
        body = pr_data.get("body", "")
        paths = [f.get("filename", "") for f in changed_files[:50]]
        header = (
            "You are fixing an open PR based on reviewer feedback.\n"
            f"Project root (mandatory): `{project_root}`\n"
            f"Primary language of the repo: {repo_lang}\n"
            "Use the snapshots below as the exact current contents of those files and emit unified diff hunks that apply cleanly.\n"
        )
        prompt = (
            header
            + constraints_block(project_root)
            + diff_format_block(project_root)
            + findings_block(reviewer_findings or "")
            + files_list_block(paths)
            + snapshots_block(snapshots)
            + f"\n# PR Title\n{title}\n\n# PR Body\n{body}\n"
        )
        return prompt
    
    def _generate_fix_diff(self, project_root: str, pr_data: Dict, reviewer_findings: str, changed_files: List[Dict], snapshots: List[Tuple[str, str]]) -> str:
        """Generate diff to fix PR issues"""
        repo_lang = get_repo_language()
        prompt = self._build_pr_fix_prompt(project_root, pr_data, reviewer_findings, changed_files, repo_lang, snapshots)
        return self.diff_processor.process_full_cycle(prompt, project_root)
    
    def _checkout_pr_branch(self, branch: str) -> None:
        """Checkout the PR branch for applying fixes"""
        self.git.ensure_identity()
        
        try:
            self.git.checkout(branch)
        except subprocess.CalledProcessError:
            # Branch doesn't exist locally, fetch and checkout
            self.git.fetch_and_checkout_remote("origin", branch)
    
    def _apply_fixes(self, diff: str) -> bool:
        """Apply fix diff to working directory"""
        self.git.ensure_clean_worktree()
        return self.diff_processor.apply_diff(diff)
        
    def _commit_and_push_fixes(self, pr_number: int, branch: str) -> None:
        """Commit fixes (only if there are changes) and push to existing PR branch."""
        self.git.add_all()
        # Se non ci sono cambi staged, evita di fallire il commit e spingi lo stato corrente
        try:
            # Prova a committare; GitOperations può alzare se no changes
            self.git.commit(f"fix(pr #{pr_number}): address reviewer feedback")
        except subprocess.CalledProcessError as e:
            print(f"ℹ️ No new changes to commit (possibly refacing already committed): {e}")
        finally:
            self.git.push_to_existing("origin", branch)
            print("✅ Pushed fixes to the same PR branch")    
    
    # -------- Helpers: ledger-first data sources --------
    def _load_reviewer_from_ledger(self, pr_number: int) -> Tuple[str, List[Dict]]:
        """Legge sticky_findings + prioritized_actions dal ThreadLedger (fallback vuoto)."""
        try:
            ledger = ThreadLedger(f"PR-{pr_number}")
            data = ledger.read().get("reviewer", {}) or {}
            findings = (data.get("sticky_findings") or "").strip()
            actions = data.get("prioritized_actions") or []
            return findings, actions
        except Exception:
            return "", []

    def _merge_findings_with_actions(self, findings_text: str, actions: List[Dict]) -> str:
        """Appende un elenco sintetico delle azioni prioritarie al testo dei findings."""
        if not actions:
            return findings_text or ""
        lines = []
        for a in actions[:20]:
            title = a.get("title") or a.get("id") or ""
            sev = (a.get("severity") or "").upper()
            eff = a.get("effort") or ""
            rationale = a.get("rationale") or a.get("why", "")
            files = ", ".join(a.get("files_touched", []) or []) or "—"
            badge = f"[{sev}/{eff}]" if sev or eff else ""
            lines.append(f"- {badge} {title} — {rationale} (files: {files})")
        block = "# Prioritized Actions (from reviewer)\n" + "\n".join(lines) + "\n"
        return (findings_text or "") + "\n\n" + block

    def _snapshots_from_ledger(self, pr_number: int, paths: List[str], char_limit: int) -> List[Tuple[str, str]]:
        """Carica i contenuti snapshot dal ledger (content_path) rispettando i limiti di prompt."""
        try:
            ledger = ThreadLedger(f"PR-{pr_number}")
            snaps = ledger.read().get("snapshots", {}) or {}
            out: List[Tuple[str, str]] = []
            for rel in (paths or [])[:MAX_SNAPSHOT_FILES]:
                meta = snaps.get(rel) or {}
                cp = meta.get("content_path")
                if not cp:
                    continue
                p = Path(cp)
                if not p.exists() or not p.is_file():
                    continue
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if len(txt) > char_limit:
                    cut = txt.rfind("\n", 0, char_limit)
                    if cut == -1:
                        cut = char_limit
                    txt = txt[:cut].rstrip("\n") + "\n# . (truncated) .\n"
                # evita collisioni con fence markdown nel prompt
                txt = txt.replace("```", "``\u200b`")
                out.append((rel, txt))
            return out
        except Exception:
            return []