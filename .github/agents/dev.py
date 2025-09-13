#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Developer — Segmented architecture (Issue mode + PR-fix mode)

Modalità:
  - Issue mode:    env ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY
  - PR-fix mode:   env PR_NUMBER

Requisiti env (minimo):
  - GITHUB_TOKEN (e/o GH_CLASSIC_TOKEN per GraphQL/permessi estesi)
  - GITHUB_REPOSITORY (owner/repo)
  - OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY (almeno una)

Opzionali:
  - DEVELOPER_MODEL (default: gpt-4o-mini)
  - PROJECT_ROOT (override della root del progetto)
"""
import os
import sys
import json
from typing import Optional

# Import segmented modules
from dev_core import GitOperations, GitHubClient, DiffProcessor
from dev_modes import IssueMode, PRFixMode


def get_issue_number() -> int:
    """Get issue number from environment"""
    n = os.getenv("ISSUE_NUMBER")
    return int(n) if n else 0


def get_pr_number() -> int:
    """Get PR number from environment or GitHub event"""
    n = os.getenv("PR_NUMBER")
    if n:
        return int(n)
    
    # Fallback to GitHub event
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, "r", encoding="utf-8") as f:
                event = json.load(f)
            pr = event.get("pull_request", {})
            return int(pr.get("number", 0))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    
    return 0


def validate_environment() -> tuple[bool, str]:
    """Validate required environment variables"""
    # Check for GitHub token
    token = os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return False, "Missing GITHUB_TOKEN/GH_CLASSIC_TOKEN"
    
    # Check for repository info
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo:
        return False, "Missing GITHUB_REPOSITORY"
    if "/" not in repo:
        return False, "GITHUB_REPOSITORY must be in 'owner/repo' format"
    
    # Check for at least one LLM API key
    llm_keys = [
        os.getenv("OPENAI_API_KEY"),
        os.getenv("ANTHROPIC_API_KEY"), 
        os.getenv("GEMINI_API_KEY")
    ]
    if not any(llm_keys):
        return False, "Missing LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY)"
    
    # Check git availability (best-effort)
    try:
        import subprocess
        subprocess.check_output(["git", "--version"], text=True)
    except Exception:
        return False, "git not available in PATH"
    
    return True, "Environment validation passed"


def setup_dependencies() -> tuple[GitHubClient, GitOperations, DiffProcessor]:
    """Initialize and return core dependencies"""
    github_client = GitHubClient()
    git_ops = GitOperations()
    diff_processor = DiffProcessor()
    
    return github_client, git_ops, diff_processor


def main() -> int:
    """Main entry point for AI Developer"""
    print("🛠️ AI Developer: start (segmented architecture)")
    
    # Validate environment
    env_valid, env_message = validate_environment()
    if not env_valid:
        print(f"❌ {env_message}")
        return 1
    
    print(f"✅ {env_message}")
    
    # Determine operation mode
    issue_number = get_issue_number()
    pr_number = get_pr_number()
    
    if not issue_number and not pr_number:
        print("ℹ️ Neither ISSUE_NUMBER nor PR_NUMBER set — nothing to do.")
        return 0
    if issue_number and pr_number:
        print(f"ℹ️ Both ISSUE_NUMBER ({issue_number}) and PR_NUMBER ({pr_number}) are set — Issue Mode takes precedence.")
    
    # Setup dependencies
    try:
        github_client, git_ops, diff_processor = setup_dependencies()
    except Exception as e:
        print(f"❌ Failed to setup dependencies: {e}")
        return 1
    
    # Route to appropriate mode
    try:
        if issue_number:
            print(f"🎯 Routing to Issue Mode for issue #{issue_number}")
            mode = IssueMode(github_client, git_ops, diff_processor)
            return mode.run(issue_number)
        
        elif pr_number:
            print(f"🎯 Routing to PR Fix Mode for PR #{pr_number}")
            mode = PRFixMode(github_client, git_ops, diff_processor)
            return mode.run(pr_number)
        
    except Exception as e:
        print(f"❌ Mode execution failed: {e}")
        return 1
    
    # Should not reach here
    print("⚠️ Unexpected execution path")
    return 1


if __name__ == "__main__":
    sys.exit(main())
