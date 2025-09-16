#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR Fix mode: PR reviewer feedback → In-place fixes for AI Developer
Con integrazione dello state: ThreadLedger/SnapshotStore/PromptBuilder/DiffRecorder.
"""
import re
import os
import subprocess
from typing import TYPE_CHECKING, List, Dict, Tuple
from collections import Counter
from pathlib import Path

from utils import get_repo_language
from dev_core.path_isolation import compute_project_root_for_pr, ensure_dir
from dev_core import (
    enforce_all,
    constraints_block, diff_format_block, files_list_block, findings_block, snapshots_block,
    collect_snapshots, comment_with_llm_preview, normalize_diff_headers_against_fs
)
from state import (
    ThreadLedger, SnapshotStore, DiffRecorder,
    preflight_git_apply_check, preflight_git_apply_threeway,
    safe_snapshot_existing_files, detect_changed_files, post_commit_snapshot_update
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
 
            
            # Carica feedback e file PR (servono per inferire la root)
            reviewer_findings = self._read_reviewer_sticky(pr_number)
            changed_files = self.github.get_pr_files(pr_number)

            # Setup project root (env/body)  inferenza dai file se fallback pr-<n>
            project_root = compute_project_root_for_pr(pr_number, pr_data.get("body", ""))
            project_root = self._maybe_infer_root_from_files(project_root, changed_files)
            self.github.post_comment(pr_number, f"🔎 Using project root: `{project_root}` for PR-fix")
            print(f"📁 PROJECT_ROOT = {project_root}")
            ensure_dir(project_root)
            
            # Persist project root + scope nel ledger
            must_edit = sorted({
                (f.get("filename") or "").strip()
                for f in changed_files
                if (f.get("filename") or "").strip().startswith(project_root.rstrip("/") + "/")
            })
            ledger.update(reviewer={"sticky_findings": reviewer_findings or ""})
            ledger.set_scope(must_edit=must_edit, must_not_edit=[])
            # Priming snapshot meta @ base_sha (utile a prompt futuri/diagnostica)
            try:
                repo_root = Path(subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    text=True, capture_output=True, check=True
                ).stdout.strip())
            except Exception:
                repo_root = Path.cwd()
            
            snap = SnapshotStore(repo_root)
            if must_edit:
                metas, missing = safe_snapshot_existing_files(
                    snap, must_edit, base_sha,
                    on_log=lambda m: ledger.append_decision(f"Fix: {m}", actor="Fix")
                )
                if metas:
                    cur = ledger.read().get("snapshots", {})
                    cur.update({
                        p: {"sha": m["sha"], "lines": m["lines"], "content_path": m["content_path"]}
                        for p, m in metas.items()
                    })
                    ledger.update(snapshots=cur)
                if missing:
                    to_create = set(ledger.read().get("files_to_create", []))
                    to_create.update(missing)
                    ledger.update(files_to_create=sorted(to_create))
            ledger.update(project_root=project_root)
            ledger.append_decision(f"Fix: set project_root='{project_root}', scope={len(must_edit)} files; primed snapshots @base", actor="Fix")
            ledger.set_status("fix_pending")

            # Checkout PR branch PRIMA di generare il diff: così leggiamo i file reali
            self._checkout_pr_branch(branch)

            # Raccogli snapshot condivisi dei file PR sotto project_root
            paths = [(f.get("filename", "") or "").strip() for f in changed_files[:MAX_SNAPSHOT_FILES]]
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
                diff = self._generate_fix_diff(project_root, pr_data, reviewer_findings, changed_files, snapshots)
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
                    prompt_preview = self._build_pr_fix_prompt(project_root, pr_data, reviewer_findings, changed_files, repo_lang, snapshots)
                    rec.record_prompt(prompt_preview)
                    rec.record_model_raw(diff)

                    # Normalizza header (nuovi file/eliminazioni) rispetto al filesystem
                    diff = normalize_diff_headers_against_fs(diff, project_root)
                    # Enforce: tutto sotto project_root (eccezione README di progetto)
                    enforce_all(diff, project_root, allow_project_readme=True)

                    # Preflight: usa la vera repo_root per coerenza con Git
                    ok, out, err = preflight_git_apply_check(diff, repo_root)
                    if not ok:
                        ok, out, err = preflight_git_apply_threeway(diff, repo_root)
                    rec.record_preflight(out, err)
                    rec.record_payload(diff)
                    # Persist esito preflight nel ledger
                    ledger.update(dev_fix={
                        "model": os.getenv("DEVELOPER_MODEL") or "gpt-5-thinking",
                        "params": {"temperature": 0.2},  # se hai un valore reale, mettilo qui
                        "last_prompt_hash": str(hash(prompt_preview)),
                        "last_generated_patch": str(rec.dir / "payload_to_git.patch"),
                        "preflight": {"ok": ok, "stderr": err}
                    })
                    if not ok:
                        raise RuntimeError("Preflight failed; patch would not apply cleanly")
                    # Applica i fix
                    success = self._apply_fixes(diff)
                    if not success:
                        raise RuntimeError("git apply failed")
                    
                    break
                except Exception as e:
                    msg = str(e).lower()
                    retriable = any(k in msg for k in ("missing unified hunk", "malformed patch", "corrupt patch", "git apply failed"))
                    if retriable and not retried:
                        retried = True
                        # Istruzioni esplicite per obbligare unified hunks validi o full-file diff
                        repo_lang = get_repo_language()
                        prompt = self._build_pr_fix_prompt(project_root, pr_data, reviewer_findings, changed_files, repo_lang, snapshots)
                        prompt += (
                            "\n\n# RETRY INSTRUCTIONS\n"
                            "- Your previous patch failed (invalid or missing '@@' hunks / apply failed).\n"
                            "- Regenerate ONE fenced unified diff.\n"
                            "- Include proper '@@' sections; if unsure, emit FULL-FILE unified diffs for files you modify.\n"
                        )
                        # Rigenera con prompt rinforzato
                        diff = self.diff_processor.process_full_cycle(prompt, project_root)
                        # Torna al loop per normalizzare/enforce/apply
                        continue
                    # Log failure nel ledger e rilancia
                    ledger.append_decision(f"Fix: generation/apply retry needed: {e}", actor="Fix")
                    raise
            
            # Commit and push fixes
            self._commit_and_push_fixes(pr_number, branch)

            # === SNAPSHOT UPDATE AFTER COMMIT (centralizzato) ===
            try:
                repo_root = Path(subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    text=True, capture_output=True, check=True
                ).stdout.strip())
            except Exception:
                repo_root = Path.cwd()

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
    
    # (rimosso) _collect_snapshots — usiamo dev_core.snapshots.collect_snapshots
    
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
        """Commit fixes and push to existing PR branch"""
        self.git.add_all()
        self.git.commit(f"fix(pr #{pr_number}): address reviewer feedback")
        self.git.push_to_existing("origin", branch)
        print("✅ Pushed fixes to the same PR branch")