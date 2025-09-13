#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PR context detection and event parsing for Progress Manager
"""
import os
import json
import re
from typing import Optional, Dict

from utils.github_api import rest_request, get_repo_info


class PRDetector:
    """Detects PR context from GitHub Actions events and environment variables"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
    
    def get_pr_from_context(self) -> Optional[Dict]:
        """
        Get PR information from multiple sources with fallback chain.
        
        Returns:
            PR dictionary if found, None otherwise
        """
        # Try multiple detection methods in order of reliability
        pr = (self._get_pr_from_event() or 
              self._get_pr_from_env_vars() or 
              self._get_pr_from_git_refs())
        
        if pr:
            print(f"Detected PR #{pr.get('number')}: {pr.get('title', 'No title')[:50]}")
        else:
            print("No PR context found")
        
        return pr
    
    def _get_pr_from_event(self) -> Optional[Dict]:
        """Extract PR from GitHub Actions event context"""
        event_path = os.getenv("GITHUB_EVENT_PATH")
        if not event_path or not os.path.exists(event_path):
            return None
        
        try:
            with open(event_path, "r", encoding="utf-8") as f:
                event_data = json.load(f)
            
            event_name = os.getenv("GITHUB_EVENT_NAME", "")
            
            # Handle different event types
            if event_name in ["pull_request", "pull_request_target"]:
                pr = event_data.get("pull_request")
            elif event_name == "workflow_run":
                # For workflow_run events, PR might be in different location
                pr = event_data.get("pull_request")
                if not pr:
                    # Try to get from workflow run context
                    workflow_run = event_data.get("workflow_run", {})
                    head_sha = workflow_run.get("head_sha")
                    if head_sha:
                        return self._find_pr_by_sha(head_sha)
            else:
                pr = event_data.get("pull_request")
            
            if isinstance(pr, dict) and pr.get("number"):
                return pr
                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"Warning: Could not parse event data: {e}")
        
        return None
    
    def _get_pr_from_env_vars(self) -> Optional[Dict]:
        """Get PR info via environment variables with multiple fallback methods"""
        # Method 1: Direct PR_NUMBER env var
        pr_num = os.getenv("PR_NUMBER")
        if pr_num and str(pr_num).isdigit():
            try:
                return rest_request("GET", f"/repos/{self.owner}/{self.repo}/pulls/{int(pr_num)}")
            except Exception as e:
                print(f"Warning: Could not fetch PR #{pr_num}: {e}")
        
        # Method 2: Extract from GITHUB_REF (refs/pull/<n>/merge or refs/pull/<n>/head)
        ref = os.getenv("GITHUB_REF", "")
        ref_match = re.search(r"refs/pull/(\d+)/", ref)
        if ref_match:
            pr_num = int(ref_match.group(1))
            try:
                return rest_request("GET", f"/repos/{self.owner}/{self.repo}/pulls/{pr_num}")
            except Exception as e:
                print(f"Warning: Could not fetch PR #{pr_num} from ref: {e}")
        
        return None
    
    def _get_pr_from_git_refs(self) -> Optional[Dict]:
        """Extract PR from git reference information"""
        # Method: Extract from GITHUB_HEAD_REF (for pull_request events)
        head_ref = os.getenv("GITHUB_HEAD_REF", "")
        if head_ref:
            try:
                # Search for PRs with this head branch
                prs = rest_request("GET", f"/repos/{self.owner}/{self.repo}/pulls", params={
                    "head": f"{self.owner}:{head_ref}",
                    "state": "open"
                })
                
                if prs and isinstance(prs, list):
                    return prs[0]  # Return first matching PR
                    
            except Exception as e:
                print(f"Warning: Could not find PR for branch {head_ref}: {e}")
        
        return None
    
    def _find_pr_by_sha(self, sha: str) -> Optional[Dict]:
        """Find PR by commit SHA"""
        try:
            # GitHub API to find PR by commit
            result = rest_request("GET", f"/repos/{self.owner}/{self.repo}/commits/{sha}/pulls")
            if result and isinstance(result, list) and result:
                return result[0]  # Return first PR containing this commit
        except Exception as e:
            print(f"Warning: Could not find PR for SHA {sha}: {e}")
        
        return None
    
    def validate_pr_context(self, pr: Dict) -> bool:
        """
        Validate that PR context is suitable for progress management.
        
        Args:
            pr: PR dictionary
            
        Returns:
            True if PR is valid for progression, False otherwise
        """
        if not pr or not isinstance(pr, dict):
            return False
        
        # Must have a number
        if not pr.get("number"):
            return False

        # Enrich PR data if 'merged'/'state' might be missing
        if "merged" not in pr or "state" not in pr:
            try:
                pr_num = int(pr.get("number"))
                fresh = rest_request("GET", f"/repos/{self.owner}/{self.repo}/pulls/{pr_num}")
                if isinstance(fresh, dict):
                    pr.update({k: fresh.get(k) for k in ("state", "merged", "body", "title")})
            except Exception as e:
                print(f"Warning: could not enrich PR #{pr.get('number')}: {e}")
        
        # Must have a body (to look for closing patterns)
        if not pr.get("body"):
            print(f"Warning: PR #{pr.get('number')} has no body")
            return False
        
        # Should be merged or closed (for progression to trigger)
        state = pr.get("state", "")
        merged = pr.get("merged", False)
        
        if state == "open":
            print(f"Info: PR #{pr.get('number')} is still open, no progression needed yet")
            return False
        
        if state == "closed" and not merged:
            print(f"Info: PR #{pr.get('number')} was closed without merging")
            return False
        
        return True
    
    def get_pr_summary(self, pr: Dict) -> str:
        """Get formatted summary of PR for logging"""
        if not pr:
            return "No PR detected"
        
        number = pr.get("number", "Unknown")
        title = pr.get("title", "No title")
        state = pr.get("state", "unknown")
        merged = pr.get("merged", False)
        
        status = "merged" if merged else state
        
        return f"PR #{number} ({status}): {title[:60]}"
