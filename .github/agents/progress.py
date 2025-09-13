#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Task Progress Manager — Segmented architecture (Task progression after PR merge)

Features:
- Enhanced PR detection from multiple contexts (events, env vars, git refs)
- Robust issue relationship parsing (closes patterns, parent-child hierarchy)
- Intelligent sibling task discovery with dependency analysis
- Comprehensive project status management and progress reporting
- Graceful error handling with fallback mechanisms
"""
import os
import sys
from typing import Optional, Dict, List

# Import segmented modules
from prg_core import PRDetector, RelationshipParser, TaskSequencer, StatusUpdater
from utils.github_api import get_repo_info, rest_request


def validate_progress_environment() -> tuple[bool, str]:
    """Validate environment for progress manager operation"""
    missing = []
    # Token GitHub (classic o actions)
    if not (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")):
        missing.append("GITHUB_TOKEN/GH_TOKEN")
    # Repo owner/repo
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo or "/" not in (repo or ""):
        missing.append("GITHUB_REPOSITORY('owner/repo')")
    else:
        # Convalida formale usando util già pronto
        try:
            get_repo_info()
        except Exception:
            missing.append("repo info (get_repo_info)")
    if missing:
        return False, "Missing requirements: " + ", ".join(missing)
    return True, "Environment validation passed"

def setup_dependencies() -> tuple[PRDetector, RelationshipParser, TaskSequencer, StatusUpdater]:
    """Initialize and return all progress manager dependencies"""
    pr_detector = PRDetector()
    relationship_parser = RelationshipParser()
    task_sequencer = TaskSequencer()
    status_updater = StatusUpdater()
    
    return pr_detector, relationship_parser, task_sequencer, status_updater

def _env_flag(name: str, default: bool = False) -> bool:
    """Parse boolean-ish env flags like '1', 'true', 'yes' (case-insensitive)."""
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}

def _pr_has_approval(owner: str, repo: str, pr_number: int) -> bool:
    """Return True if PR has at least one APPROVED review and no later CHANGES_REQUESTED."""
    try:
        reviews = rest_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews") or []
        if not isinstance(reviews, list):
            return False
        # Considera l'ultimo stato per ciascun reviewer
        latest_by_user = {}
        for r in reviews:
            user = (r.get("user") or {}).get("login") or "unknown"
            submitted_at = r.get("submitted_at") or ""
            state = (r.get("state") or "").upper()
            prev = latest_by_user.get(user)
            if not prev or submitted_at > prev["submitted_at"]:
                latest_by_user[user] = {"state": state, "submitted_at": submitted_at}
        states = [v["state"] for v in latest_by_user.values()]
        has_approved = any(s == "APPROVED" for s in states)
        has_changes_requested = any(s == "CHANGES_REQUESTED" for s in states)
        return has_approved and not has_changes_requested
    except Exception as e:
        print(f"Warning: could not read reviews for PR #{pr_number}: {e}")
        return False
    
def _maybe_auto_merge_pr(pr: Dict, status_updater: StatusUpdater) -> Optional[Dict]:
    """
    If AUTO_MERGE_PR is enabled and PR is open, approved, and mergeable, merge it and return a fresh PR dict.
    If not mergeable, leave an explanatory comment and return None to pause the flow.
    """
    auto_merge = _env_flag("AUTO_MERGE_PR", False)
    if not auto_merge:
        print("Auto-merge disabled (AUTO_MERGE_PR not set). Waiting for manual merge.")
        return None

    owner, repo = get_repo_info()
    pr_number = int(pr.get("number"))

    # Refresh PR to get mergeability fields
    fresh = rest_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}") or {}
    state = fresh.get("state")
    merged = bool(fresh.get("merged"))
    mergeable = bool(fresh.get("mergeable"))
    mergeable_state = fresh.get("mergeable_state")  # 'clean', 'blocked', 'dirty', 'behind', 'unstable', 'draft', ...

    if state != "open" or merged:
        return fresh

    # Require approval
    if not _pr_has_approval(owner, repo, pr_number):
        msg = ("⏸️ Auto-merge non eseguito: PR non ancora APPROVED "
               "(o presenti CHANGES_REQUESTED). Attendere approvazione.")
        status_updater.post_progress_comment(pr_number, msg)
        print(msg)
        return None
        
    # Basic mergeability gate (safe-by-default)
    allow_unstable = _env_flag("AUTO_MERGE_ALLOW_UNSTABLE", False)
    allowed_states = {"clean"} | ({"unstable"} if allow_unstable else set())
    if not mergeable or mergeable_state not in allowed_states:
        msg = (f"⏸️ Auto-merge non eseguito: mergeable={mergeable}, "
               f"mergeable_state='{mergeable_state}'. "
               "Verifica check di stato / branch protection.")
        
        status_updater.post_progress_comment(pr_number, msg)
        print(msg)
        return None

    # Perform merge
    method = os.getenv("AUTO_MERGE_METHOD", "squash")
    title = fresh.get("title") or f"PR #{pr_number}"
    try:
        result = rest_request("PUT", f"/repos/{owner}/{repo}/pulls/{pr_number}/merge", json={
            "merge_method": method,
            "commit_title": f"Merge PR #{pr_number}: {title}",
            "commit_message": "Auto-merged by Progress Manager"
        })
        if not result or not result.get("merged"):
            status = result.get("message", "unknown") if isinstance(result, dict) else "unknown"
            msg = f"⚠️ Auto-merge fallito: {status}. Procedere manualmente."
            status_updater.post_progress_comment(pr_number, msg)
            print(msg)
            return None
        print(f"✅ Auto-merge eseguito su PR #{pr_number} (method={method})")
        # Fetch merged PR view
        return rest_request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}") or fresh
    except Exception as e:
        msg = f"⚠️ Auto-merge fallito per errore: {e}"
        status_updater.post_progress_comment(pr_number, msg)
        print(msg)
        return None

def log_project_integration_status(status_updater: StatusUpdater) -> None:
    """Log current project integration configuration status"""
    status = status_updater.get_project_integration_status()
    
    if status["project_integration_enabled"]:
        print("Project integration: ENABLED")
        print(f"  - Project ID: {status['project_id']}")
        print(f"  - Status field: {status['status_field_id']}")
        print(f"  - Available statuses: Done={status['done_status_available']}, "
              f"InProgress={status['in_progress_status_available']}, "
              f"Backlog={status['backlog_status_available']}")
    else:
        print("Project integration: DISABLED (missing configuration)")


def main() -> int:
    """Main entry point for AI Task Progress Manager"""
    print("AI Task Progress Manager: start (segmented architecture)")
    
    # Validate environment (use progress-specific validator)
    env_valid, env_message = validate_progress_environment()
    if not env_valid:
        print(f"Environment validation failed: {env_message}")
        return 1
    
    print("Environment validation passed")
    
    # Setup dependencies
    pr_detector, relationship_parser, task_sequencer, status_updater = setup_dependencies()
    
    # Log project integration status
    log_project_integration_status(status_updater)
    
    try:
        # === PHASE 1: PR DETECTION ===
        
        print("Phase 1: PR context detection...")
        pr = pr_detector.get_pr_from_context()
        
        if not pr:
            print("No PR context found - nothing to progress")
            return 0
        
        # Se il PR è ancora aperto, prova auto-merge (se abilitato); in caso contrario, attendi merge manuale
        if pr.get("state") == "open" and not pr.get("merged"):
            print("PR detected but still open — evaluating auto-merge gate...")
            merged_view = _maybe_auto_merge_pr(pr, status_updater)
            if not merged_view:
                # Gate non superato: interrompi il flusso, si riproverà dopo il merge
                return 0
            pr = merged_view

        # A questo punto il PR dovrebbe essere merged/closed per far proseguire il progress
        # Ora validiamo il contesto PR
        if not pr_detector.validate_pr_context(pr):
            return 0
        
        print(f"PR context validated: {pr_detector.get_pr_summary(pr)}")
        
        # === PHASE 2: RELATIONSHIP ANALYSIS ===
        
        print("Phase 2: Issue relationship analysis...")
        closing_issue, parent_issue, parent_issue_data = relationship_parser.analyze_pr_issue_chain(pr)
        
        if not closing_issue:
            print("PR does not close any issue - no progression needed")
            return 0
        
        if not parent_issue:
            print(f"Issue #{closing_issue} has no parent - no progression needed")
            return 0
        
        # Validate relationship hierarchy
        if not relationship_parser.validate_issue_hierarchy(closing_issue, parent_issue):
            print("Invalid issue hierarchy detected")
            return 1
        
        print(f"Relationship chain: PR -> Issue #{closing_issue} -> Parent #{parent_issue}")
        
        # === PHASE 3: SIBLING TASK DISCOVERY ===
        
        print("Phase 3: Sibling task discovery...")
        sibling_tasks = task_sequencer.find_sibling_tasks(parent_issue, exclude_issue=closing_issue)
        
        if not sibling_tasks:
            print("No remaining sibling tasks found")
            
            # Mark parent as completed
            print("Phase 4: Marking parent as completed...")
            success = status_updater.mark_parent_as_done(parent_issue)
            if success:
                completion_comment = status_updater.create_completion_comment(parent_issue)
                status_updater.post_progress_comment(parent_issue, completion_comment)
            
            print(f"Parent issue #{parent_issue} marked as completed")
            return 0
        
        print(f"Found {len(sibling_tasks)} remaining sibling tasks")
        
        # === PHASE 4: TASK SEQUENCING ===
        
        print("Phase 4: Next task selection...")
        sequencing_rec = task_sequencer.get_sequencing_recommendation(sibling_tasks)
        
        next_task = sequencing_rec.get("next_task")
        if not next_task:
            print("No suitable next task found")
            return 1
        
        next_task_number = next_task.get("number")
        strategy = sequencing_rec.get("recommendation", "unknown")
        rationale = sequencing_rec.get("rationale", "No rationale provided")
        
        print(f"Selected task #{next_task_number} (strategy: {strategy})")
        print(f"Rationale: {rationale}")
        
        # Log warnings if present
        if "warning" in sequencing_rec:
            print(f"WARNING: {sequencing_rec['warning']}")
        
        # === PHASE 5: TASK TRANSITION EXECUTION ===
        
        print("Phase 5: Executing task transition...")
        transition_success = status_updater.execute_task_transition(
            completed_task=closing_issue,
            parent_number=parent_issue,
            next_task=next_task,
            remaining_tasks=sibling_tasks
        )
        
        if not transition_success:
            print("Warning: Some aspects of task transition failed (check logs)")
        
        print(f"Progress update complete: #{closing_issue} -> #{next_task_number}")
        return 0
        
    except Exception as e:
        print(f"Progress manager failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
