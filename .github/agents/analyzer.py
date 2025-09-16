#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Issue Analyzer — Segmented architecture (Issue analysis + implementation planning)

Features:
- Enhanced issue analysis with complexity detection
- LLM-based implementation planning with robust JSON parsing
- Detailed pre-execution reports
- Automated task and sprint creation with project integration
- Auto-start first task for seamless workflow
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import Tuple, List, Dict

# Import segmented modules
from ana_core import IssueAnalyzer, PlanGenerator, ReportBuilder, TaskCreator
from utils.system_info import validate_environment
from utils.github_api import post_issue_comment, get_repo_info
from state import ThreadLedger, SnapshotStore, normalize_paths_under_root, safe_snapshot_existing_files


def get_issue_info_from_env() -> Tuple[int, str]:
    """Get issue information from environment"""
    try:
        issue_number = int(os.environ["ISSUE_NUMBER"])
        issue_body = os.getenv("ISSUE_BODY", "")
        return issue_number, issue_body
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Missing or invalid ISSUE_NUMBER environment variable: {e}")


def get_repo_info_from_env() -> Tuple[str, str]:
    """Get repository information from environment"""
    try:
        repo = os.environ["GITHUB_REPOSITORY"]
        if "/" not in repo:
            raise ValueError("GITHUB_REPOSITORY must be in 'owner/repo' format")
        return repo.split("/", 1)
    except KeyError:
        raise RuntimeError("Missing GITHUB_REPOSITORY environment variable")


def validate_analyzer_environment() -> Tuple[bool, str]:
    """Validate environment for analyzer operation"""
    # Use utils validation
    env_checks = validate_environment()
    
    # Check analyzer-specific requirements
    required_env = ["GITHUB_REPOSITORY", "ISSUE_NUMBER"]
    missing_env = []
    
    for env_var in required_env:
        if not os.getenv(env_var):
            missing_env.append(env_var)
    
    # Check for essential capabilities
    missing_requirements = []
    essential_checks = ["github_token", "github_repo", "llm_key_available"]
    
    for check in essential_checks:
        if not env_checks.get(check, False):
            missing_requirements.append(check)
    
    if missing_env or missing_requirements:
        missing_all = missing_env + missing_requirements
        return False, f"Missing requirements: {', '.join(missing_all)}"
    
    return True, "Environment validation passed"

def _get_repo_root() -> Path:
    """Resolve git repository root (fallback to current working dir)."""
    try:
        root = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True, capture_output=True, check=True
        ).stdout.strip()
        return Path(root)
    except Exception:
        return Path.cwd()

def _collect_all_paths_from_plan(plan: Dict) -> List[str]:
    """Collect unique paths from plan tasks."""
    paths: List[str] = []
    for t in plan.get("tasks", []):
        paths.extend(list(t.get("paths", [])))
    # normalizza e dedup
    norm = []
    seen = set()
    for p in paths:
        q = str(p).strip().lstrip("./")
        if q and q not in seen:
            seen.add(q); norm.append(q)
    return norm

def _merge_snapshot_metas_into_ledger(ledger: ThreadLedger, metas: Dict[str, Dict]) -> None:
    if not metas:
        return
    cur = ledger.read().get("snapshots", {})
    cur.update({p: {"sha": m["sha"], "lines": m["lines"], "content_path": m["content_path"]} for p, m in metas.items()})
    ledger.update(snapshots=cur)

def setup_dependencies() -> Tuple[IssueAnalyzer, PlanGenerator, ReportBuilder, TaskCreator]:
    """Initialize and return all analyzer dependencies"""
    issue_analyzer = IssueAnalyzer()
    plan_generator = PlanGenerator()
    report_builder = ReportBuilder()
    task_creator = TaskCreator()
    
    return issue_analyzer, plan_generator, report_builder, task_creator


def post_status_update(issue_number: int, message: str) -> None:
    """Post status update to issue with error handling"""
    try:
        owner, repo = get_repo_info()
        post_issue_comment(owner, repo, issue_number, message)
    except Exception as e:
        print(f"Failed to post status update: {e}")


def main() -> int:
    """Main entry point for AI Analyzer"""
    print("AI Issue Analyzer: start (segmented architecture)")
    
    try:
        # Get basic info
        issue_number, issue_body = get_issue_info_from_env()
        owner, repo = get_repo_info_from_env()
        
        print(f"Analyzing issue #{issue_number} in {owner}/{repo}")
        
        # Validate environment
        env_valid, env_message = validate_analyzer_environment()
        if not env_valid:
            print(f"Environment validation failed: {env_message}")
            post_status_update(issue_number, f"Analyzer failed: {env_message}")
            return 1
        
        print(f"Environment validation passed")
        
        # Setup dependencies
        issue_analyzer, plan_generator, report_builder, task_creator = setup_dependencies()
        
        # === STATE / LEDGER BOOTSTRAP ===
        thread_id = f"ISSUE-{issue_number}"
        repo_root = _get_repo_root()
        ledger = ThreadLedger(thread_id)
        # metadati base del thread
        ledger.update(repo=f"{owner}/{repo}", status="triage")
        # base SHA al momento dell'analisi (il branch nascerà più avanti nel flusso)
        try:
            base_sha = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
        except Exception:
            base_sha = "HEAD"
        ledger.update(base_sha=base_sha, branch=None)

        
        # Ensure standard labels exist
        task_creator.ensure_standard_labels()
        
        # Post initial status
        post_status_update(
            issue_number,
            f"Analyzer started for issue #{issue_number}\n"
            f"Repository: {owner}/{repo}\n"
            f"Model: {plan_generator.model}\n"
            f"Project Integration: {'enabled' if task_creator.project_id else 'disabled'}"
        )
        
        # === ISSUE ANALYSIS PHASE ===
        
        print("Phase 1: Issue analysis...")
        try:
            issue_analysis = issue_analyzer.analyze_issue_comprehensive(issue_number)
            summary = issue_analyzer.get_analysis_summary(issue_analysis)
            print(f"Issue analysis complete: {summary}")
            
            # Proietta root progetto da project_tag (se presente)
            project_tag = issue_analysis.get("project_tag")
            project_root = f"projects/{project_tag}" if project_tag else "projects"
            # Fotografa struttura progetto (profondità limitata)
            snap = SnapshotStore(repo_root)
            structure = snap.scan_tree(project_root, depth=3)
            ledger.set_project(project_root, structure)
            ledger.append_decision(f"Analyzer: set project_root='{project_root}' ({len(structure)} files @depth=3)", actor="Analyzer")
            # Scope iniziale dai file citati nell'issue (se presenti)
            initial_files = issue_analysis.get("requirements", {}).get("files", [])
            if initial_files:
                # normalizza sotto project_root
                must_edit = normalize_paths_under_root(initial_files, project_root)
                ledger.set_scope(must_edit=must_edit, must_not_edit=[])
                ledger.append_decision(f"Analyzer: initial scope from issue ({len(must_edit)} files)", actor="Analyzer")
                # → Priming snapshot SAFE (solo file esistenti)
                metas, missing = safe_snapshot_existing_files(
                    snap, must_edit, base_sha,
                    on_log=lambda m: ledger.append_decision(f"Analyzer: {m}", actor="Analyzer")
                )
                _merge_snapshot_metas_into_ledger(ledger, metas)
                if missing:
                    to_create = set(ledger.read().get("files_to_create", []))
                    to_create.update(missing)
                    ledger.update(files_to_create=sorted(to_create))
                
            # Stato
            ledger.set_status("dev_pending")
            
        except Exception as e:
            error_msg = f"Issue analysis failed: {e}"
            print(error_msg)
            post_status_update(issue_number, error_msg)
            return 1
        
        # === PLAN GENERATION PHASE ===
        
        print("Phase 2: Plan generation...")
        try:
            plan = plan_generator.generate_implementation_plan(issue_analysis)
            dependency_analysis = plan_generator.analyze_task_dependencies(plan)
            # Surface warnings in the report
            if dependency_analysis.get("unknown_dependencies"):
                plan["_dependency_warnings"] = dependency_analysis["unknown_dependencies"]
            
            print(f"Plan generated: {len(plan['tasks'])} tasks, {len(plan['sprints'])} sprints")
            if dependency_analysis["has_dependencies"]:
                print(f"Dependencies detected: {len(dependency_analysis['dependent_tasks'])} dependent tasks")
                
            # Aggiorna scope con i path dai task (unione con quelli iniziali)
            plan_paths = _collect_all_paths_from_plan(plan)
            if plan_paths:
                plan_paths_norm = normalize_paths_under_root(plan_paths, project_root)
                current = ledger.read().get("scope", {}).get("must_edit", [])
                merged = list({*current, *plan_paths_norm})
                ledger.set_scope(must_edit=merged, must_not_edit=[])
                ledger.append_decision(f"Analyzer: scope merged with plan paths (now {len(merged)} files)", actor="Analyzer")                
                # → Priming snapshot SAFE (solo file esistenti)
                metas, missing = safe_snapshot_existing_files(
                    snap, merged, base_sha,
                    on_log=lambda m: ledger.append_decision(f"Analyzer: {m}", actor="Analyzer"))
                _merge_snapshot_metas_into_ledger(ledger, metas)
                if missing:
                    to_create = set(ledger.read().get("files_to_create", []))
                    to_create.update(missing)
                    ledger.update(files_to_create=sorted(to_create))
                
        except Exception as e:
            error_msg = f"Plan generation failed: {e}"
            print(error_msg)
            post_status_update(issue_number, error_msg)
            return 1
        
        # === REPORT GENERATION PHASE ===
        
        print("Phase 3: Report generation...")
        try:
            detailed_report = report_builder.create_detailed_report(plan, issue_analysis)
            post_status_update(issue_number, detailed_report)
            print("Detailed execution plan posted")
        except Exception as e:
            print(f"Report generation failed (non-blocking): {e}")
        
        # === TASK CREATION PHASE ===
        
        print("Phase 4: Task and sprint creation...")
        
        # Apply policy and complexity labels to parent issue
        try:
            task_creator.apply_policy_and_complexity_labels(issue_number, plan, issue_analysis)
        except Exception as e:
            print(f"Label application failed (non-blocking): {e}")
        
        # Create sprint if specified
        sprint_number = None
        sprints = plan.get("sprints", [])
        if sprints:
            try:
                sprint_number = task_creator.create_sprint_issue(sprints[0], issue_number)
                if sprint_number:
                    post_status_update(issue_number, f"Created sprint: #{sprint_number} — {sprints[0].get('name', 'Sprint 1')}")
            except Exception as e:
                print(f"Sprint creation failed (non-blocking): {e}")
        
        # Create task issues
        try:
            tasks = plan.get("tasks", [])
            created_tasks, failed_tasks = task_creator.create_task_issues(tasks, issue_number)
            
            print(f"Task creation results: {len(created_tasks)} created, {len(failed_tasks)} failed")
            
        except Exception as e:
            error_msg = f"Task creation failed: {e}"
            print(error_msg)
            post_status_update(issue_number, error_msg)
            return 1
        
        # === AUTO-START FIRST TASK ===
        
        print("Phase 5: Auto-starting first task...")
        if created_tasks:
            success = task_creator.auto_start_first_task(created_tasks, issue_number)
            if success:
                print(f"Successfully auto-started task #{created_tasks[0]}")
        
        # === FINAL SUMMARY ===
        print("Phase 6: Final summary...")
        try:
            summary_message = task_creator.create_execution_summary(
                created_tasks, failed_tasks, sprint_number, plan
            )
            post_status_update(issue_number, summary_message)
            ledger.append_decision("Analyzer completed: report posted, tasks created", actor="Analyzer")
        except Exception as e:
            print(f"Summary posting failed (non-blocking): {e}")
        
        # === COMPLETION ===
        
        print(f"Analysis complete: {len(created_tasks)} tasks created")
        
        # Return success if we created at least one task
        if created_tasks:
            # Lasciamo il thread pronto per il Dev agent
            ledger.set_status("dev_pending")
            return 0
        else:
            print("No tasks were created - this may indicate a problem")
            return 1
            
    except Exception as e:
        error_msg = f"Analyzer process failed: {e}"
        print(error_msg)
        
        # Try to report error to issue if we have the number
        try:
            if 'issue_number' in locals():
                post_status_update(issue_number, error_msg)
        except Exception:
            pass  # Don't fail if error reporting fails
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
