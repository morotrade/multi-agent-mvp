#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git operations wrapper for AI Developer
"""
import subprocess
from typing import Optional


class GitOperations:
    """Handles all Git operations with proper error handling"""
    
    def __init__(self, timeout: int = 300):
        self.timeout = timeout
    
    def _run(self, cmd: list[str], check: bool = True, cwd: Optional[str] = None) -> subprocess.CompletedProcess:
        """Execute git command with logging"""
        print(f"$ {' '.join(cmd)}")
        return subprocess.run(
            cmd, 
            check=check, 
            cwd=cwd, 
            timeout=self.timeout, 
            text=True, 
            capture_output=False
        )
    
    def current_branch(self) -> str:
        """Get current branch name"""
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], 
            text=True
        ).strip()
    
    def create_branch(self, branch: str) -> None:
        """Create and checkout new branch"""
        self._run(["git", "checkout", "-b", branch])
    
    def checkout(self, branch: str) -> None:
        """Checkout existing branch"""
        self._run(["git", "checkout", branch])
    
    def fetch_and_checkout_remote(self, remote: str, branch: str) -> None:
        """Fetch and checkout remote branch with tracking"""
        self._run(["git", "fetch", remote, branch])
        self._run(["git", "checkout", "-t", f"{remote}/{branch}"])
    
    def add_all(self) -> None:
        """Stage all changes"""
        self._run(["git", "add", "-A"])
    
    def commit(self, message: str) -> None:
        """Commit with message"""
        self._run(["git", "commit", "-m", message])
    
    def push_with_upstream(self, remote: str, branch: str) -> None:
        """Push with upstream tracking, handle protected branch scenarios"""
        try:
            self._run(["git", "push", "-u", remote, branch])
            print(f"✅ Successfully pushed {branch} to {remote}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Push failed for {branch}: {str(e)}"
            print(f"❌ {error_msg}")
            # Re-raise so caller can handle (e.g., comment on issue/PR)
            raise RuntimeError(error_msg)
    
    def push_to_existing(self, remote: str, branch: str) -> None:
        """Push to existing remote branch (no upstream setting)"""
        try:
            self._run(["git", "push", remote, branch])
            print(f"✅ Successfully pushed to {remote}/{branch}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to push fixes to {branch}: {str(e)}"
            print(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
    
    def ensure_identity(self) -> None:
        """Ensure git identity is set"""
        try:
            name = subprocess.check_output(
                ["git", "config", "--get", "user.name"], 
                text=True
            ).strip()
        except subprocess.CalledProcessError:
            name = ""
        
        if not name:
            # Prima prova locale (repo), poi globale come fallback
            try:
                self._run(["git", "config", "--local", "user.name", "AI Developer"])
                self._run(["git", "config", "--local", "user.email", "ai-dev@users.noreply.github.com"])
            except subprocess.CalledProcessError:
                self._run(["git", "config", "--global", "user.name", "AI Developer"])
                self._run(["git", "config", "--global", "user.email", "ai-dev@users.noreply.github.com"])
    
    def ensure_clean_worktree(self) -> None:
        """
        Garantisce una working tree pulita prima di applicare patch.
        Se sporca, fa hard reset + clean per evitare conflitti transitori nei runner.
        """
        try:
            status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
            if status.strip():
                print("⚠️ Working tree not clean. Resetting to HEAD and cleaning untracked files.")
                self._run(["git", "reset", "--hard", "HEAD"])
                self._run(["git", "clean", "-fd"])
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Unable to check/clean worktree: {e}")
