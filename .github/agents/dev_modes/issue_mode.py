#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue mode: Issue → Branch → PR flow for AI Developer
"""
import os
import subprocess
from typing import TYPE_CHECKING

from utils import get_repo_language, slugify
from dev_core.path_isolation import compute_project_root_for_issue, ensure_dir
from dev_core import (
    enforce_all,
    constraints_block, diff_format_block, files_list_block, snapshots_block,
    comment_with_llm_preview
)

if TYPE_CHECKING:
    from dev_core.github_client import GitHubClient
    from dev_core.git_operations import GitOperations
    from dev_core.diff_processor import DiffProcessor


class IssueMode:
    """Handles the complete Issue → Implementation → PR flow"""
    
    def __init__(self, github_client: 'GitHubClient', git_ops: 'GitOperations', diff_processor: 'DiffProcessor'):
        self.github = github_client
        self.git = git_ops
        self.diff_processor = diff_processor
    
    def run(self, issue_number: int) -> int:
        """
        Execute complete issue mode flow.
        Returns 0 on success, 1 on failure.
        """
        print(f"🔨 Issue Mode: Processing issue #{issue_number}")
        
        try:
            # Get issue details
            issue_title, issue_body = self._get_issue_details(issue_number)
            
            # Compute project root and setup
            project_root = compute_project_root_for_issue(issue_number, issue_title, issue_body)
            print(f"📁 PROJECT_ROOT = {project_root}")
            ensure_dir(project_root)
            
            # Generate implementation diff
            diff = self._generate_implementation_diff(project_root, issue_title, issue_body)
            
            if not diff or not diff.strip():
                self.github.post_comment(issue_number,
                    "ℹ️ Nessuna modifica proposta dall'LLM (diff vuoto). Nulla da applicare.")
                print("ℹ️ No-op: empty diff")
                return 0
            # Enforce: tutto sotto project_root (eccezione README di progetto)
            enforce_all(diff, project_root, allow_project_readme=True)
            
            # Create branch and implement
            branch = self._create_implementation_branch(issue_number, issue_title)
            success = self._apply_implementation(diff)
            if not success:
                self.github.post_comment(issue_number, "❌ Failed to apply implementation diff. Please check logs.")
                return 1
            
            # Commit and push
            self._commit_and_push(issue_number, branch)
            
            # Create PR
            pr_number = self._create_pr(issue_number, issue_title, project_root, branch)
            
            # Add labels if possible
            self._add_labels_if_available(pr_number)
            
            print(f"✅ Issue #{issue_number} successfully implemented in PR #{pr_number}")
            return 0
            
        except Exception as e:
            # Diagnostica uniforme
            comment_with_llm_preview(self.github, issue_number, "Issue implementation failed", e, self.diff_processor)
            print(f"❌ Issue mode failed: {e}")
            return 1
    
    def _get_issue_details(self, issue_number: int) -> tuple[str, str]:
        """Get issue title and body from env or API"""
        issue_title = os.getenv("ISSUE_TITLE", "")
        issue_body = os.getenv("ISSUE_BODY", "")
        
        if not issue_title or not issue_body:
            print("📥 Fetching issue details from GitHub API...")
            issue_data = self.github.get_issue(issue_number)
            issue_title = issue_data.get("title", "")
            issue_body = issue_data.get("body", "")
        
        return issue_title, issue_body
    
    def _build_issue_prompt(self, project_root: str, issue_title: str, issue_body: str, repo_lang: str) -> str:
            """Build prompt for LLM to implement issue (blocchi condivisi)"""
            header = (
                "You are implementing a feature from an issue.\n"
                f"Project root (mandatory): `{project_root}`\n"
                f"Primary language of the repo: {repo_lang}\n"
            )
            prompt = (
                header
                + constraints_block(project_root)
                + diff_format_block(project_root)
                + files_list_block([])            
                + snapshots_block([])              
                + f"\n# Issue Title\n{issue_title}\n\n# Issue Body\n{issue_body}\n"
            )
            return prompt
    
    def _generate_implementation_diff(self, project_root: str, issue_title: str, issue_body: str) -> str:
        """Generate diff for issue implementation"""
        repo_lang = get_repo_language()
        prompt = self._build_issue_prompt(project_root, issue_title, issue_body, repo_lang)
        return self.diff_processor.process_full_cycle(prompt, project_root)
    
    def _create_implementation_branch(self, issue_number: int, issue_title: str) -> str:
        """Create and checkout implementation branch"""
        slug = slugify(issue_title) or f"issue-{issue_number}"
        branch = f"bot/issue-{issue_number}-{slug}"
        
        self.git.ensure_identity()
        
        try:
            self.git.create_branch(branch)
        except subprocess.CalledProcessError:
            # Branch might exist locally, try checkout
            self.git.checkout(branch)
        
        return branch
    
    def _apply_implementation(self, diff: str) -> bool:
        """Apply implementation diff to working directory"""
        self.git.ensure_clean_worktree()
        return self.diff_processor.apply_diff(diff)
    
    def _commit_and_push(self, issue_number: int, branch: str) -> None:
        """Commit changes and push branch"""
        self.git.add_all()
        self.git.commit(f"feat(issue #{issue_number}): implement from issue")
        self.git.push_with_upstream("origin", branch)
    
    def _create_pr(self, issue_number: int, issue_title: str, project_root: str, branch: str) -> int:
        """Create pull request for implementation"""
        pr_title = f"[Bot] Implement from issue #{issue_number}: {issue_title}"
        pr_body = f"Auto-generated implementation.\n\nCloses #{issue_number}\n\nProject root: `{project_root}`"
        
        base_branch = self.github.get_default_branch()
        pr_data = self.github.create_pr(
            base=base_branch,
            head=branch,
            title=pr_title,
            body=pr_body
        )
        
        pr_number = pr_data.get("number")
        print(f"🔗 PR opened: #{pr_number}")
        return pr_number
    
    def _add_labels_if_available(self, pr_number: int) -> None:
        """Add labels to PR if utils function is available"""
        try:
            from utils import add_labels
            owner, repo = self.github.get_repo_info()
            add_labels(owner, repo, pr_number, ["type:feature", "bot:generated"])
        except Exception as e:
            print(f"⚠️ Label add failed: {e}")
