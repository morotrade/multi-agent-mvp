#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR Fix mode: PR reviewer feedback → In-place fixes for AI Developer
"""
import re
import subprocess
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple
from collections import Counter
from pathlib import Path

from utils import get_repo_language
from dev_core.path_isolation import compute_project_root_for_pr, ensure_dir

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
            
            # Carica feedback e file PR (servono per inferire la root)
            reviewer_findings = self._read_reviewer_sticky(pr_number)
            changed_files = self.github.get_pr_files(pr_number)

            # Setup project root (env/body)  inferenza dai file se fallback pr-<n>
            project_root = compute_project_root_for_pr(pr_number, pr_data.get("body", ""))
            project_root = self._maybe_infer_root_from_files(project_root, changed_files)
            self.github.post_comment(pr_number, f"🔎 Using project root: `{project_root}` for PR-fix")
            print(f"📁 PROJECT_ROOT = {project_root}")
            ensure_dir(project_root)

            # Checkout PR branch PRIMA di generare il diff: così leggiamo i file reali
            branch = pr_data.get("head", {}).get("ref")
            self._checkout_pr_branch(branch)

            # Raccogli snapshot dei file cambiati sotto project_root
            snapshots = self._collect_snapshots(project_root, changed_files)

            # Genera il diff per i fix (con snapshot reali a contesto)
            diff = self._generate_fix_diff(project_root, pr_data, reviewer_findings, changed_files, snapshots)

            # Accettiamo unified diff anche senza 'diff --git'; rifiutiamo solo se vuoto
            if not diff or not diff.strip():
                self.github.post_comment(
                    pr_number,
                    "ℹ️ Nessuna modifica proposta dall'LLM per i fix (diff vuoto)."
                )
                print("ℹ️ No-op: empty diff (PR-fix)")
                return 0
            
            # Applica i fix
            success = self._apply_fixes(diff)
            if not success:
                self.github.post_comment(pr_number, "❌ Failed to apply LLM patch in PR-fix mode. See logs.")
                return 1
            
            # Commit and push fixes
            self._commit_and_push_fixes(pr_number, branch)
            
            print(f"✅ PR #{pr_number} fixes applied successfully")
            return 0
            
        except Exception as e:
            error_msg = self.diff_processor.sanitize_error_for_comment(str(e))
            self.github.post_comment(pr_number, f"❌ LLM diff validation failed in PR-fix mode:\n\n```\n{error_msg}\n```")
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
        """Build prompt for LLM to fix PR issues"""
        # Prepare summary of changed files
        file_list = "\n".join(f"- {f.get('filename', '')}" for f in changed_files[:50])
        
        title = pr_data.get("title", "")
        body = pr_data.get("body", "")
        
        guidance = f"""
You are fixing an open PR based on reviewer feedback.
Project root (mandatory): `{project_root}`
Primary language of the repo: {repo_lang}

Constraints:
- Output EXACTLY ONE fenced unified diff block and NOTHING ELSE.
- Use the snapshots below as the exact current contents for building hunks.
- No prose outside the diff block.
  The block MUST look like:
  ```diff
  --- a/<path/within/{project_root}/...>
  +++ b/<path/within/{project_root}/...>
  @@ ...
  ```
- Do NOT include any additional commentary or multiple code blocks.
"""
        
        details = f"""
# PR Title
{title}

# PR Body
{body}

# Reviewer Findings (markdown)
{reviewer_findings}

# Files currently in the PR
{file_list}
"""
        # Aggiungi snapshot correnti (read-only) dei file sotto root
        if snapshots:
            details += "\n# Current file snapshots (read-only)\n"
            for rel, content in snapshots:
                lang = "python" if rel.endswith(".py") else ""
                details += f"\n## {rel}\n```{lang}\n{content}\n```\n"
        return guidance + "\n" + details
    
    def _generate_fix_diff(self, project_root: str, pr_data: Dict, reviewer_findings: str, changed_files: List[Dict], snapshots: List[Tuple[str, str]]) -> str:
        """Generate diff to fix PR issues"""
        repo_lang = get_repo_language()
        prompt = self._build_pr_fix_prompt(project_root, pr_data, reviewer_findings, changed_files, repo_lang, snapshots)
        return self.diff_processor.process_full_cycle(prompt, project_root)
    
    def _collect_snapshots(self, project_root: str, changed_files: List[Dict]) -> List[Tuple[str, str]]:
        """
        Raccoglie il contenuto attuale (post-checkout) dei file cambiati sotto project_root.
        Ritorna lista di tuple (relative_path, content_troncato).
        """
        out: List[Tuple[str, str]] = []
        root = project_root.rstrip("/")
        for f in changed_files[:MAX_SNAPSHOT_FILES]:
            rel = (f.get("filename", "") or "").strip().lstrip("./")
            if not rel or not rel.startswith(root + "/"):
                continue
            p = Path(rel)
            if p.exists() and p.is_file():
                try:
                   txt = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if len(txt) > SNAPSHOT_CHAR_LIMIT:
                    txt = txt[:SNAPSHOT_CHAR_LIMIT] + "\n# ... (truncated) ..."
                out.append((rel, txt))
        return out
    
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