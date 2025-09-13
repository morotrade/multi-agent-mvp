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
from typing import Tuple

# Import segmented modules
from ana_core import IssueAnalyzer, PlanGenerator, ReportBuilder, TaskCreator
from utils.system_info import validate_environment
from utils.github_api import post_issue_comment, get_repo_info


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
        except Exception as e:
            print(f"Summary posting failed (non-blocking): {e}")
        
        # === COMPLETION ===
        
        print(f"Analysis complete: {len(created_tasks)} tasks created")
        
        # Return success if we created at least one task
        if created_tasks:
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
