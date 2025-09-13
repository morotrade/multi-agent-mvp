# -*- coding: utf-8 -*-
"""
GitHub API utilities - REST & GraphQL operations (unified for dev + reviewer)
"""
import os
import json
from typing import List, Optional, Dict, Tuple
import httpx

# Configuration constants
TIMEOUT_DEFAULT = 60
TIMEOUT_GRAPHQL = 40

def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v

def get_token() -> str:
    """Get GitHub token with fallback priority"""
    tkn = os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not tkn:
        raise RuntimeError("Missing token (GH_CLASSIC_TOKEN/GITHUB_TOKEN)")
    return tkn

def get_github_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-developer/unified"
    }

def get_github_graphql_headers() -> dict:
    """GraphQL headers - prefer classic token for project access"""
    token = os.environ.get("GH_CLASSIC_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GH_CLASSIC_TOKEN/GITHUB_TOKEN for GraphQL")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-developer/unified"
    }

def rest_request(method: str, path: str, timeout: int = TIMEOUT_DEFAULT, **kwargs) -> Optional[Dict]:
    """Unified REST API request handler"""
    url = f"https://api.github.com{path}"
    with httpx.Client(timeout=timeout) as client:
        response = client.request(method, url, headers=get_github_headers(), **kwargs)
    
    if response.status_code >= 400:
        raise RuntimeError(f"REST {method} {path} -> {response.status_code}: {response.text[:300]}")
    
    return response.json() if response.text else None

def graphql_request(query: str, variables: dict, timeout: int = TIMEOUT_GRAPHQL) -> Dict:
    """Unified GraphQL request handler"""
    url = "https://api.github.com/graphql"
    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, headers=get_github_graphql_headers(), json={
            "query": query, 
            "variables": variables
        })
    
    if response.status_code >= 400:
        raise RuntimeError(f"GraphQL HTTP {response.status_code}: {response.text[:300]}")
    
    data = response.json()
    if "errors" in data:
        error_msg = str(data["errors"])
        if any(term in error_msg.lower() for term in ["scope", "permission", "forbidden"]):
            raise RuntimeError("GraphQL access requires GH_CLASSIC_TOKEN with appropriate scopes")
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    
    return data["data"]

def get_repo_info() -> Tuple[str, str]:
    """Get owner and repo from environment or event"""
    full = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in full:
        owner, repo = full.split("/", 1)
        return owner, repo
    
    # Fallback to GitHub event
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        with open(event_path, "r", encoding="utf-8") as f:
            event = json.load(f)
        repo_info = event.get("repository", {})
        return repo_info["owner"]["login"], repo_info["name"]
    
    raise RuntimeError("Cannot determine repository info")

# ==== Issue/PR Operations ====

def get_issue(owner: str, repo: str, issue_number: int) -> Dict:
    """Get issue details"""
    return rest_request("GET", f"/repos/{owner}/{repo}/issues/{issue_number}")

def get_pr(owner: str, repo: str, pr_number: int) -> Dict:
    """Get pull request details"""
    return rest_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")

def get_pr_files(owner: str, repo: str, pr_number: int) -> List[Dict]:
    """Get files changed in PR with pagination support"""
    all_files = []
    page = 1
    per_page = 100
    
    while True:
        chunk = rest_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/files", params={
            "per_page": per_page,
            "page": page
        })
        
        if not chunk:
            break
        
        all_files.extend(chunk)
        if len(chunk) < per_page:
            break
        page += 1
    
    return all_files

def get_pr_comments(owner: str, repo: str, pr_number: int) -> List[Dict]:
    """Get PR/issue comments"""
    return rest_request("GET", f"/repos/{owner}/{repo}/issues/{pr_number}/comments") or []

def post_issue_comment(owner: str, repo: str, issue_number: int, body: str) -> Dict:
    """Post comment on issue or PR"""
    return rest_request("POST", f"/repos/{owner}/{repo}/issues/{issue_number}/comments", json={
        "body": body
    })

def update_comment(owner: str, repo: str, comment_id: int, body: str) -> Dict:
    """Update existing comment"""
    return rest_request("PATCH", f"/repos/{owner}/{repo}/issues/comments/{comment_id}", json={
        "body": body
    })

def create_issue(owner: str, repo: str, title: str, body: str, labels: Optional[List[str]] = None) -> Dict:
    """Create new issue"""
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    return rest_request("POST", f"/repos/{owner}/{repo}/issues", json=payload)

def create_pr(owner: str, repo: str, base: str, head: str, title: str, body: str) -> Dict:
    """Create new pull request"""
    return rest_request("POST", f"/repos/{owner}/{repo}/pulls", json={
        "title": title,
        "head": head,
        "base": base,
        "body": body
    })

# ==== Label Operations ====

def get_pr_labels(owner: str, repo: str, pr_number: int) -> List[Dict]:
    """Get labels attached to PR/issue"""
    try:
        return rest_request("GET", f"/repos/{owner}/{repo}/issues/{pr_number}/labels") or []
    except Exception:
        return []

def add_labels(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    """Add labels to issue/PR"""
    rest_request("POST", f"/repos/{owner}/{repo}/issues/{issue_number}/labels", json={
        "labels": labels
    })

def remove_label(owner: str, repo: str, issue_number: int, label: str) -> None:
    """Remove label from issue/PR"""
    try:
        rest_request("DELETE", f"/repos/{owner}/{repo}/issues/{issue_number}/labels/{label}")
    except Exception:
        pass  # Label might not exist

def add_labels_to_issue(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    """Alias for backward compatibility"""
    add_labels(owner, repo, issue_number, labels)

def ensure_label_exists(owner: str, repo: str, name: str, color: str = "0E8A16", description: str = "") -> None:
    """Create label if missing; ignore if it already exists"""
    base_path = f"/repos/{owner}/{repo}/labels"
    
    # Check if exists
    try:
        rest_request("GET", f"{base_path}/{name}")
        return  # Label exists
    except RuntimeError:
        pass  # Label doesn't exist, create it
    
    # Create label
    payload = {
        "name": name,
        "color": color.lstrip("#"),
        "description": description or ""
    }
    
    try:
        rest_request("POST", base_path, json=payload)
    except RuntimeError as e:
        # Handle race condition - ignore if already exists
        if "already_exists" in str(e).lower():
            return
        raise

# ==== Repository Operations ====

def get_repo_details(owner: str, repo: str) -> Dict:
    """Get repository details"""
    return rest_request("GET", f"/repos/{owner}/{repo}")

def get_repo_language(owner: Optional[str] = None, repo: Optional[str] = None) -> str:
    """Get primary language of repository"""
    if not owner or not repo:
        try:
            owner, repo = get_repo_info()
        except Exception:
            return "Python"
    
    try:
        languages = rest_request("GET", f"/repos/{owner}/{repo}/languages")
        if not languages:
            return "Python"
        # Return most-used language
        return max(languages, key=languages.get)
    except Exception:
        return "Python"

def get_default_branch(owner: Optional[str] = None, repo: Optional[str] = None) -> str:
    """Get repository default branch"""
    if not owner or not repo:
        try:
            owner, repo = get_repo_info()
        except Exception:
            return "main"
    
    try:
        repo_data = get_repo_details(owner, repo)
        return (repo_data.get("default_branch") or "main").strip()
    except Exception:
        return "main"

# ==== GraphQL Project Operations ====

def get_issue_node_id(owner: str, repo: str, issue_number: int) -> str:
    """Get GraphQL node ID for issue"""
    data = graphql_request("""
        query($owner: String!, $repo: String!, $number: Int!) {
            repository(owner: $owner, name: $repo) {
                issue(number: $number) { id }
            }
        }
    """, {"owner": owner, "repo": repo, "number": issue_number})
    
    return data["repository"]["issue"]["id"]

def add_item_to_project(project_id: str, content_node_id: str) -> str:
    """Add item to ProjectV2 and return item ID"""
    data = graphql_request("""
        mutation($projectId: ID!, $contentId: ID!) {
            addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
                item { id }
            }
        }
    """, {"projectId": project_id, "contentId": content_node_id})
    
    return data["addProjectV2ItemById"]["item"]["id"]

def set_project_single_select(project_id: str, item_id: str, field_id: str, option_id: str) -> None:
    """Set ProjectV2 SingleSelect field (e.g., Status)"""
    graphql_request("""
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
            updateProjectV2ItemFieldValue(
                input: {
                    projectId: $projectId,
                    itemId: $itemId,
                    fieldId: $fieldId,
                    value: { singleSelectOptionId: $optionId }
                }
            ) {
                projectV2Item { id }
            }
        }
    """, {
        "projectId": project_id,
        "itemId": item_id,
        "fieldId": field_id,
        "optionId": option_id
    })
