#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub API client wrapper for AI Developer
"""
import os
import json
from typing import Optional, Dict, List, Tuple
import httpx


class GitHubClient:
    """Clean wrapper for GitHub REST API operations"""
    
    def __init__(self, token: Optional[str] = None, repository: Optional[str] = None):
        self.base_url = "https://api.github.com"
        self.token = token or self._get_token()
        self.repository = repository or os.getenv("GITHUB_REPOSITORY", "")
        
        if self.token:
            token_type = "GH_CLASSIC_TOKEN" if os.getenv("GH_CLASSIC_TOKEN") else "GITHUB_TOKEN"
            print(f"🔑 Using token: {token_type}")
    
    def _get_token(self) -> str:
        """Get token from environment with fallback"""
        return os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN", "")
    
    def _headers(self) -> Dict[str, str]:
        """Standard headers for GitHub API"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-developer/segmented"
        }
    
    def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        """Make HTTP request to GitHub API with small retry/backoff."""
        url = f"{self.base_url}{path}"
        last_exc = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60) as client:
                    response = client.request(method, url, headers=self._headers(), **kwargs)
                # Retry su 5xx o 429
                if response.status_code in (429, 500, 502, 503, 504):
                    import time
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"GitHub API {method} {path} -> {response.status_code}: {response.text[:300]}"
                    )
                return response.json() if response.text else None
            except (httpx.RequestError, RuntimeError) as e:
                last_exc = e
                if attempt < 2:
                    import time
                    time.sleep(1.0 * (attempt + 1))
                else:
                    break
        raise RuntimeError(f"GitHub API request failed after retries: {last_exc}")
    
    def get_repo_info(self) -> Tuple[str, str]:
        """Get owner and repo name from environment or event"""
        if "/" in self.repository:
            owner, repo = self.repository.split("/", 1)
            return owner, repo
        
        # Fallback to GitHub event
        event_path = os.getenv("GITHUB_EVENT_PATH")
        if event_path and os.path.exists(event_path):
            with open(event_path, "r", encoding="utf-8") as f:
                event = json.load(f)
            repo_info = event.get("repository", {})
            return repo_info["owner"]["login"], repo_info["name"]
        
        raise RuntimeError("Cannot determine repository info")
    
    def get_issue(self, number: int) -> Dict:
        """Get issue details"""
        owner, repo = self.get_repo_info()
        return self._request("GET", f"/repos/{owner}/{repo}/issues/{number}")
    
    def get_pr(self, number: int) -> Dict:
        """Get pull request details"""
        owner, repo = self.get_repo_info()
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")
    
    def get_pr_files(self, number: int) -> List[Dict]:
        """Get files changed in PR"""
        owner, repo = self.get_repo_info()
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}/files") or []
    
    def get_pr_comments(self, number: int) -> List[Dict]:
        """Get PR/issue comments"""
        owner, repo = self.get_repo_info()
        return self._request("GET", f"/repos/{owner}/{repo}/issues/{number}/comments") or []
    
    def create_pr(self, base: str, head: str, title: str, body: str) -> Dict:
        """Create new pull request"""
        owner, repo = self.get_repo_info()
        return self._request("POST", f"/repos/{owner}/{repo}/pulls", json={
            "title": title,
            "head": head, 
            "base": base,
            "body": body
        })
    
    def post_comment(self, number: int, body: str) -> Dict:
        """Post comment on issue or PR"""
        owner, repo = self.get_repo_info()
        return self._request("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={
            "body": body
        })
    
    def get_repo_details(self) -> Dict:
        """Get repository details"""
        owner, repo = self.get_repo_info()
        return self._request("GET", f"/repos/{owner}/{repo}")
    
    def get_default_branch(self) -> str:
        """Get repository default branch"""
        try:
            repo_data = self.get_repo_details()
            return (repo_data.get("default_branch") or "main").strip()
        except Exception:
            return "main"
