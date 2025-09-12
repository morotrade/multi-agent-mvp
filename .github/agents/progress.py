#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
progress.py - Enhanced Task Progression Manager (PATCHED VERSION)
Enhanced with:
- Better error handling for Project v2 operations
- Improved sibling task detection and sequencing
- Enhanced status management and reporting
- Graceful handling of missing permissions
"""
import os, re, json
import httpx
from urllib.parse import quote as urlquote
from utils import (
    get_github_headers, get_issue_node_id,
    add_item_to_project, set_project_single_select
)

REPO = os.environ["GITHUB_REPOSITORY"]  # "owner/repo"
TIMEOUT_DEFAULT = 30

def gh_get(url, timeout=TIMEOUT_DEFAULT):
    """Enhanced GitHub API GET with better error handling"""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, headers=get_github_headers())
            r.raise_for_status()
            return r
    except httpx.TimeoutException:
        raise RuntimeError(f"Timeout accessing {url}")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP {e.response.status_code} for {url}: {e.response.text[:200]}")

def get_closing_issue_number_from_pr(pr: dict):
    """Extract 'Closes #<n>' from PR body with enhanced pattern matching"""
    body = pr.get("body") or ""
    
    # Multiple patterns to catch various closing keywords
    patterns = [
        r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b",
        r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:issue\s+)?#(\d+)\b",
        r"(?i)#(\d+)(?:\s+(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?))?",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body)
        if match:
            return int(match.group(1))
    
    return None

def get_issue(owner: str, repo: str, number: int) -> dict:
    """Get issue details with error handling"""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    try:
        return gh_get(url).json()
    except Exception as e:
        print(f"Warning: Could not fetch issue #{number}: {e}")
        return {}

def find_siblings(owner: str, repo: str, parent_number: int):
    """
    Find open issues that reference the same parent.
    Uses GitHub Search API with enhanced query construction.
    """
    try:
        # Construct search query for parent references
        queries = [
            f'repo:{owner}/{repo} is:issue is:open in:body "Parent: #{parent_number}"',
            f'repo:{owner}/{repo} is:issue is:open in:body "parent #{parent_number}"',
            f'repo:{owner}/{repo} is:issue is:open in:body "#{parent_number}"',
        ]
        
        all_results = []
        for query in queries:
            try:
                url = f"https://api.github.com/search/issues?q={urlquote(query)}&per_page=100"
                response = gh_get(url)
                results = response.json().get("items", [])
                all_results.extend(results)
            except Exception as e:
                print(f"Search query failed: {query} - {e}")
                continue
        
        # Deduplicate by issue number
        seen_numbers = set()
        unique_results = []
        for item in all_results:
            number = item.get("number")
            if number and number not in seen_numbers:
                seen_numbers.add(number)
                unique_results.append(item)
        
        return unique_results
        
    except Exception as e:
        print(f"Warning: Sibling search failed: {e}")
        return []

def get_event_pr_from_context(owner: str, repo: str) -> dict | None:
    """
    Extract PR from GitHub Actions event context with enhanced parsing.
    """
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Handle different event types
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        
        if event_name == "pull_request":
            pr = data.get("pull_request")
        elif event_name == "pull_request_target":
            pr = data.get("pull_request")
        elif event_name == "workflow_run":
            # For workflow_run events, we might need to get PR from head_repository
            pr = None
        else:
            pr = data.get("pull_request")
        
        if isinstance(pr, dict) and pr.get("number"):
            return pr
            
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"Warning: Could not parse event data: {e}")
    
    return None

def get_pr_via_env(owner: str, repo: str) -> dict | None:
    """
    Get PR info via environment variables with multiple fallback methods.
    """
    # Method 1: Direct PR_NUMBER env var
    pr_num = os.environ.get("PR_NUMBER")
    if pr_num and str(pr_num).isdigit():
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{int(pr_num)}"
            return gh_get(url).json()
        except Exception as e:
            print(f"Warning: Could not fetch PR #{pr_num}: {e}")

    # Method 2: Extract from GITHUB_REF (refs/pull/<n>/merge or refs/pull/<n>/head)
    ref = os.environ.get("GITHUB_REF", "")
    ref_match = re.search(r"refs/pull/(\d+)/", ref)
    if ref_match:
        pr_num = int(ref_match.group(1))
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
            return gh_get(url).json()
        except Exception as e:
            print(f"Warning: Could not fetch PR #{pr_num} from ref: {e}")
    
    # Method 3: Extract from GITHUB_HEAD_REF (for pull_request events)
    head_ref = os.environ.get("GITHUB_HEAD_REF", "")
    if head_ref:
        try:
            # Search for PRs with this head branch
            url = f"https://api.github.com/repos/{owner}/{repo}/pulls?head={owner}:{head_ref}&state=open"
            response = gh_get(url)
            prs = response.json()
            if prs:
                return prs[0]  # Return first matching PR
        except Exception as e:
            print(f"Warning: Could not find PR for branch {head_ref}: {e}")
    
    return None

def update_project_status_safe(issue_number: int, status_option_id: str, status_name: str = ""):
    """
    Update project status with comprehensive error handling.
    """
    project_id = os.environ.get("GITHUB_PROJECT_ID") or os.environ.get("GH_PROJECT_ID")
    field_id = os.environ.get("PROJECT_STATUS_FIELD_ID")
    
    if not (project_id and field_id and status_option_id):
        print("Info: Project status update skipped (missing configuration)")
        return False
    
    try:
        owner, repo = REPO.split("/", 1)
        node_id = get_issue_node_id(owner, repo, issue_number)
        item_id = add_item_to_project(project_id, node_id)
        set_project_single_select(project_id, item_id, field_id, status_option_id)
        
        status_desc = f" to '{status_name}'" if status_name else ""
        print(f"Project status updated for #{issue_number}{status_desc}")
        return True
        
    except Exception as e:
        error_msg = str(e).lower()
        if any(keyword in error_msg for keyword in ["scope", "permission", "forbidden", "unauthorized"]):
            print(f"Warning: Project access requires GH_CLASSIC_TOKEN with 'project' scope")
        else:
            print(f"Warning: Project update failed for #{issue_number}: {e}")
        return False

def post_progress_comment(owner: str, repo: str, issue_number: int, message: str):
    """Post comment with error handling"""
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
            r = client.post(url, headers=get_github_headers(), json={"body": message})
            r.raise_for_status()
    except Exception as e:
        print(f"Warning: Could not post comment to #{issue_number}: {e}")

def main():
    """
    Enhanced main function with comprehensive error handling and status management.
    """
    print("Progress Manager: Enhanced version starting...")
    
    owner, repo = REPO.split("/", 1)

    # Step 1: Get PR information from multiple sources
    pr = get_event_pr_from_context(owner, repo) or get_pr_via_env(owner, repo)
    
    if not pr:
        print("Info: No PR context found, exiting gracefully")
        return 0

    pr_number = pr.get("number")
    print(f"Processing PR #{pr_number}: {pr.get('title', 'No title')[:50]}")

    # Step 2: Find the issue this PR closes
    closing_issue_number = get_closing_issue_number_from_pr(pr)
    if not closing_issue_number:
        print("Info: PR does not close any issue, no progression needed")
        return 0

    print(f"PR closes issue #{closing_issue_number}")

    # Step 3: Get the closed issue and find its parent
    closed_issue = get_issue(owner, repo, closing_issue_number)
    if not closed_issue:
        print(f"Warning: Could not fetch closed issue #{closing_issue_number}")
        return 0

    issue_body = closed_issue.get("body", "")
    parent_match = re.search(r"(?i)\*\*Parent\*\*:\s*#(\d+)\b|Parent:\s*#(\d+)\b", issue_body)
    
    if not parent_match:
        print("Info: Closed issue has no parent reference, no progression needed")
        return 0

    parent_number = int(parent_match.group(1))
    print(f"Parent issue: #{parent_number}")

    # Step 4: Find sibling tasks (other open issues with same parent)
    siblings = find_siblings(owner, repo, parent_number)
    if not siblings:
        print(f"Info: No sibling tasks found for parent #{parent_number}")
        
        # Mark parent as done if no more tasks
        status_done_id = os.environ.get("PROJECT_STATUS_DONE_ID")
        if status_done_id:
            update_project_status_safe(parent_number, status_done_id, "Done")
            post_progress_comment(owner, repo, parent_number, 
                                f"All tasks completed! Parent issue can be closed.")
        
        return 0

    # Step 5: Exclude the just-closed issue and find next task
    open_siblings = [s for s in siblings if s.get("number") != closing_issue_number]
    
    if not open_siblings:
        print("Info: No remaining open sibling tasks")
        
        # Mark parent as done
        status_done_id = os.environ.get("PROJECT_STATUS_DONE_ID")
        if status_done_id:
            update_project_status_safe(parent_number, status_done_id, "Done")
            post_progress_comment(owner, repo, parent_number,
                                f"All tasks completed! Parent issue #{parent_number} ready to close.")
        
        return 0

    # Step 6: Select next task (lowest number = oldest)
    next_task = min(open_siblings, key=lambda x: x.get("number", float('inf')))
    next_issue_number = next_task.get("number")
    
    print(f"Next task to start: #{next_issue_number}")

    # Step 7: Add bot:implement label to next task
    try:
        # Get current labels
        current_labels_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{next_issue_number}"
        current_issue_data = gh_get(current_labels_url).json()
        current_labels = {label["name"] for label in current_issue_data.get("labels", [])}
        
        # Add bot:implement if not already present
        if "bot:implement" not in current_labels:
            current_labels.add("bot:implement")
            
            # Update labels
            labels_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{next_issue_number}"
            with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
                r = client.patch(labels_url, headers=get_github_headers(), 
                               json={"labels": list(current_labels)})
                r.raise_for_status()
            
            print(f"Added 'bot:implement' label to #{next_issue_number}")
        else:
            print(f"Task #{next_issue_number} already has 'bot:implement' label")
            
    except Exception as e:
        print(f"Warning: Could not update labels for #{next_issue_number}: {e}")

    # Step 8: Update project status to "In Progress"
    status_inprogress_id = os.environ.get("PROJECT_STATUS_INPROGRESS_ID")
    if status_inprogress_id:
        update_project_status_safe(next_issue_number, status_inprogress_id, "In Progress")

    # Step 9: Post progress updates
    try:
        # Comment on parent issue
        remaining_count = len(open_siblings)
        parent_comment = f"""Progress Update: Task #{closing_issue_number} completed!

**Next Task**: #{next_issue_number} - {next_task.get('title', 'No title')}
**Remaining Tasks**: {remaining_count}
**Status**: Automatically started next task with `bot:implement` label

The development pipeline will continue automatically."""

        post_progress_comment(owner, repo, parent_number, parent_comment)
        
        # Comment on next task
        task_comment = f"""Development Started: This task has been automatically selected as the next priority.

**Triggered by**: Completion of #{closing_issue_number}
**Parent Issue**: #{parent_number}
**Position in Queue**: Next in line

The bot will begin implementation shortly."""

        post_progress_comment(owner, repo, next_issue_number, task_comment)
        
    except Exception as e:
        print(f"Warning: Could not post progress comments: {e}")

    print(f"Progress update complete: #{closing_issue_number} -> #{next_issue_number}")
    return 0

if __name__ == "__main__":
    exit(main())