#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Code Reviewer — Segmented architecture (PR-centric review with project scoping)

Features:
- Real LLM integration with robust parsing + fallbacks
- Sticky comment management with structured sections
- Policy enforcement (strict/lenient/essential-only) after side effects
- Project root scoping with auto-detection + enforcement
- Suggested patches filtered to project scope
"""
import os
import sys
import json
from typing import Optional

# Import segmented modules
from rew_core import ProjectDetector, LLMReviewer, CommentManager
from rew_policies import LabelManager, PolicyEnforcer
from utils.github_api import get_repo_info, get_pr, get_pr_files


def get_pr_number_from_env() -> int:
    """Get PR number from environment or GitHub event"""
    # Direct env var
    if os.getenv("PR_NUMBER"):
        return int(os.getenv("PR_NUMBER"))
    
    # GitHub event fallback
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
    # GitHub token
    if not (os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN")):
        return False, "Missing GitHub token (GH_CLASSIC_TOKEN/GITHUB_TOKEN)"
    
    # Repository info
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo:
        return False, "Missing GITHUB_REPOSITORY"
    if "/" not in repo:
        return False, "GITHUB_REPOSITORY must be in 'owner/repo' format"
    
    # LLM API key
    llm_keys = [
        os.getenv("OPENAI_API_KEY"),
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("GEMINI_API_KEY")
    ]
    if not any(llm_keys):
        return False, "Missing LLM API key (OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY)"
    
    return True, "Environment validation passed"


def setup_dependencies() -> tuple[ProjectDetector, LLMReviewer, CommentManager, LabelManager, PolicyEnforcer]:
    """Initialize and return all dependencies"""
    project_detector = ProjectDetector()
    llm_reviewer = LLMReviewer()
    comment_manager = CommentManager()
    label_manager = LabelManager()
    policy_enforcer = PolicyEnforcer()
    
    return project_detector, llm_reviewer, comment_manager, label_manager, policy_enforcer


def main() -> int:
    """Main entry point for AI Reviewer"""
    print("AI Code Reviewer: start (segmented architecture)")
    
    # Validate environment
    env_valid, env_message = validate_environment()
    if not env_valid:
        print(f"❌ {env_message}")
        return 1
    
    print(f"✅ {env_message}")
    
    # Get PR number
    pr_number = get_pr_number_from_env()
    if not pr_number:
        print("No PR number found - nothing to review")
        return 0
    
    print(f"📋 Reviewing PR #{pr_number}")
    
    try:
        # Setup dependencies
        project_detector, llm_reviewer, comment_manager, label_manager, policy_enforcer = setup_dependencies()
        # Ensure standard labels exist (idempotente)
        try:
            label_manager.ensure_policy_labels_exist()
        except Exception as e:
            print(f"Label bootstrap failed (non-blocking): {e}")
        
        # Get PR and files data
        owner, repo = get_repo_info()
        pr_data = get_pr(owner, repo, pr_number)
        files_data = get_pr_files(owner, repo, pr_number)
        pr_labels = label_manager.get_pr_labels_set(pr_number)
        
        # Project root detection and scope validation
        project_root = project_detector.compute_project_root(pr_data, files_data, pr_labels)
        scope_valid, scope_offenders = project_detector.validate_files_under_root(files_data, project_root)
        
        print(f"📁 Project root: {project_root}")
        if not scope_valid:
            print(f"⚠️ Path scope violation: {len(scope_offenders)} files outside root")
        
        # Run LLM review
        try:
            result = llm_reviewer.run_review(pr_data, files_data, project_root)
        except Exception as e:
            print(f"❌ LLM review failed: {e}")
            result = llm_reviewer.create_fallback_result(str(e))
        
        # Handle path scope violations (adjust counts and findings)
        if not scope_valid:
            scope_finding = project_detector.create_scope_violation_finding(project_root, scope_offenders)
            result["findings"].append(scope_finding)
            
            # Update summary with scope violation info
            scope_note = project_detector.get_scope_summary_note(project_root, scope_offenders)
            if result.get("summary"):
                result["summary"] += f"\n\n{scope_note}"
            else:
                result["summary"] = scope_note
            
            # Adjust counts based on enforcement policy
            if project_detector.enforce_scope:
                result["blockers"] = max(result["blockers"], 1)
                print("🔒 ENFORCE_PROJECT_ROOT: Path scope violation treated as BLOCKER")
        
        # Filter patches to project root
        raw_patches = result.get("patches", [])
        filtered_patches = llm_reviewer.filter_patches_under_root(raw_patches, project_root)
        
        if raw_patches and not filtered_patches:
            print(f"⚠️ All {len(raw_patches)} suggested patches were outside project root - filtered out")
        
        # Determine policy and enforcement
        policy_name = label_manager.detect_policy_from_labels(pr_labels)
        must_fix = policy_enforcer.determine_must_fix(
            policy_name, 
            result["blockers"], 
            result["importants"]
        )
        
        print(f"🎯 Review results: {result['blockers']} blockers, {result['importants']} important, {result['suggestions']} suggestions")
        print(f"📋 Policy: {policy_name}, Must fix: {must_fix}")
        
        # === SIDE EFFECTS (before exit code calculation) ===
        
        # 1. Update sticky comment with all results
        comment_manager.create_and_post_sticky_comment(
            pr_number=pr_number,
            result=result,
            project_root=project_root,
            filtered_patches=filtered_patches,
            total_patches=len(raw_patches)
        )
        
        # 2. Apply labels based on policy decision  
        label_manager.apply_review_labels(pr_number, must_fix)
        
        # 3. Update project status if source issue found
        try:
            source_issue = policy_enforcer.extract_source_issue_from_pr_body(pr_data.get("body", ""))
            if source_issue:
                policy_enforcer.update_project_status_to_in_review(source_issue)
        except Exception as e:
            print(f"⚠️ Project status update failed: {e}")
        
        # === POLICY ENFORCEMENT (exit code) ===
        
        exit_code = policy_enforcer.enforce_policy_and_get_exit_code(
            policy_name=policy_name,
            blockers=result["blockers"],
            importants=result["importants"],
            suggestions=result["suggestions"]
        )
        
        print(f"🏁 Review completed with exit code: {exit_code}")
        return exit_code
        
    except Exception as e:
        print(f"❌ Review process failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())