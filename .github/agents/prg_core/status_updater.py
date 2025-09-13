#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project status updates and comment management for Progress Manager
"""
import os
from typing import Dict, List, Optional

from utils.github_api import (
    get_repo_info, get_issue_node_id, add_item_to_project, 
    set_project_single_select, post_issue_comment, rest_request
)


class StatusUpdater:
    """Handles project status updates and progress comment management"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
        
        # Project integration settings
        self.project_id = (
            os.getenv("GITHUB_PROJECT_ID") or 
            os.getenv("GH_PROJECT_ID")
        )
        self.status_field_id = os.getenv("PROJECT_STATUS_FIELD_ID")
        
        # Status option IDs
        self.done_status_id = os.getenv("PROJECT_STATUS_DONE_ID")
        self.in_progress_status_id = os.getenv("PROJECT_STATUS_INPROGRESS_ID")
        self.backlog_status_id = os.getenv("PROJECT_STATUS_BACKLOG_ID")
    
    def update_project_status_safe(self, issue_number: int, status_option_id: str, status_name: str = "") -> bool:
        """
        Update project status with comprehensive error handling.
        
        Args:
            issue_number: Issue number to update
            status_option_id: Project status option ID
            status_name: Human-readable status name for logging
            
        Returns:
            True if successful, False otherwise
        """
        if not self.project_id or not self.status_field_id or not status_option_id:
            print("Project status update skipped (missing configuration)")
            return False
        
        try:
            node_id = get_issue_node_id(self.owner, self.repo, issue_number)
            item_id = add_item_to_project(self.project_id, node_id)
            set_project_single_select(self.project_id, item_id, self.status_field_id, status_option_id)
            
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
    
    def mark_task_as_done(self, issue_number: int) -> bool:
        """Mark a task as done in the project"""
        if not self.done_status_id:
            print("No DONE status ID configured")
            return False
        return self.update_project_status_safe(issue_number, self.done_status_id, "Done")
    
    def mark_task_as_in_progress(self, issue_number: int) -> bool:
        """Mark a task as in progress in the project"""
        if not self.in_progress_status_id:
            print("No IN_PROGRESS status ID configured")
            return False
        return self.update_project_status_safe(issue_number, self.in_progress_status_id, "In Progress")
    
    def mark_parent_as_done(self, parent_issue_number: int) -> bool:
        """Mark parent issue as done when all tasks are completed"""
        return self.mark_task_as_done(parent_issue_number)
    
    def add_implementation_label(self, issue_number: int) -> bool:
        """
        Add 'bot:implement' label to issue to trigger development.
        
        Args:
            issue_number: Issue number to label
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current labels
            current_issue = rest_request("GET", f"/repos/{self.owner}/{self.repo}/issues/{issue_number}")
            current_labels = {label["name"] for label in current_issue.get("labels", [])}
            
            # Add bot:implement if not already present
            if "bot:implement" not in current_labels:
                current_labels.add("bot:implement")
                
                # Update labels
                rest_request("PATCH", f"/repos/{self.owner}/{self.repo}/issues/{issue_number}", json={
                    "labels": list(current_labels)
                })
                
                print(f"Added 'bot:implement' label to #{issue_number}")
                return True
            else:
                print(f"Task #{issue_number} already has 'bot:implement' label")
                return True
                
        except Exception as e:
            print(f"Warning: Could not update labels for #{issue_number}: {e}")
            return False
    
    def post_progress_comment(self, issue_number: int, message: str) -> bool:
        """
        Post progress comment with error handling.
        
        Args:
            issue_number: Issue number to comment on
            message: Comment message
            
        Returns:
            True if successful, False otherwise
        """
        try:
            post_issue_comment(self.owner, self.repo, issue_number, message)
            return True
        except Exception as e:
            print(f"Warning: Could not post comment to #{issue_number}: {e}")
            return False
    
    def create_parent_progress_comment(self, 
                                     parent_number: int,
                                     completed_task: int, 
                                     next_task: Dict,
                                     remaining_count: int) -> str:
        """Create progress comment for parent issue"""
        next_task_number = next_task.get("number")
        next_task_title = next_task.get("title", "No title")
        
        return f"""Progress Update: Task #{completed_task} completed!

**Next Task**: #{next_task_number} - {next_task_title}
**Remaining Tasks**: {remaining_count}
**Status**: Automatically started next task with `bot:implement` label

The development pipeline will continue automatically."""
    
    def create_next_task_comment(self, 
                               task_number: int,
                               completed_task: int, 
                               parent_number: int) -> str:
        """Create comment for next task being started"""
        return f"""Development Started: This task has been automatically selected as the next priority.

**Triggered by**: Completion of #{completed_task}
**Parent Issue**: #{parent_number}
**Position in Queue**: Next in line

The bot will begin implementation shortly."""
    
    def create_completion_comment(self, parent_number: int) -> str:
        """Create comment for parent when all tasks are completed"""
        return f"""All tasks completed! Parent issue #{parent_number} ready to close.

**Status**: All child tasks have been successfully implemented and merged.
**Next Steps**: Review the complete implementation and close this parent issue when satisfied.

The automated development pipeline has finished processing this issue."""
    
    def post_completion_updates(self, 
                              parent_number: int,
                              completed_task: int,
                              next_task: Optional[Dict] = None,
                              remaining_count: int = 0) -> bool:
        """
        Post comprehensive progress updates to relevant issues.
        
        Args:
            parent_number: Parent issue number
            completed_task: Just completed task number  
            next_task: Next task to be started (if any)
            remaining_count: Number of remaining tasks
            
        Returns:
            True if all updates successful, False otherwise
        """
        success = True
        
        if next_task:
            # Case: More tasks remaining
            next_task_number = next_task.get("number")
            
            # Comment on parent issue
            parent_comment = self.create_parent_progress_comment(
                parent_number, completed_task, next_task, remaining_count
            )
            if not self.post_progress_comment(parent_number, parent_comment):
                success = False
            
            # Comment on next task
            task_comment = self.create_next_task_comment(
                next_task_number, completed_task, parent_number
            )
            if not self.post_progress_comment(next_task_number, task_comment):
                success = False
        
        else:
            # Case: All tasks completed
            completion_comment = self.create_completion_comment(parent_number)
            if not self.post_progress_comment(parent_number, completion_comment):
                success = False
        
        return success
    
    def get_project_integration_status(self) -> Dict:
        """Get status of project integration configuration"""
        return {
            "project_integration_enabled": bool(self.project_id and self.status_field_id),
            "project_id": self.project_id,
            "status_field_id": self.status_field_id,
            "done_status_available": bool(self.done_status_id),
            "in_progress_status_available": bool(self.in_progress_status_id),
            "backlog_status_available": bool(self.backlog_status_id),
        }
    
    def execute_task_transition(self, 
                              completed_task: int,
                              parent_number: int,
                              next_task: Optional[Dict] = None,
                              remaining_tasks: List[Dict] = None) -> bool:
        """
        Execute complete task transition workflow.
        
        Args:
            completed_task: Task that was just completed
            parent_number: Parent issue number
            next_task: Next task to start (if any)
            remaining_tasks: List of all remaining tasks
            
        Returns:
            True if transition successful, False otherwise
        """
        success = True
        remaining_count = len(remaining_tasks) if remaining_tasks else 0
        
        # Update project statuses
        if next_task:
            next_task_number = next_task.get("number")
            
            # Start next task
            if not self.add_implementation_label(next_task_number):
                success = False
            
            if not self.mark_task_as_in_progress(next_task_number):
                success = False
        
        else:
            # Mark parent as done if no more tasks
            if not self.mark_parent_as_done(parent_number):
                success = False
        
        # Post progress comments
        if not self.post_completion_updates(parent_number, completed_task, next_task, remaining_count):
            success = False
        
        return success