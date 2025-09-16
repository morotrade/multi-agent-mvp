#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task and sprint creation with GitHub integration for AI Analyzer
"""
import os
from typing import Dict, List, Tuple, Optional

from utils.github_api import (
    get_repo_info, create_issue, add_labels, ensure_label_exists,
    get_issue_node_id, add_item_to_project, set_project_single_select,
    post_issue_comment
)


class TaskCreator:
    """Handles creation of tasks, sprints, and project integration"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
        
        # Project integration settings
        self.project_id = (
            os.getenv("GITHUB_PROJECT_ID") or 
            os.getenv("GH_PROJECT_ID")
        )
        self.status_field_id = os.getenv("PROJECT_STATUS_FIELD_ID")
        self.backlog_id = os.getenv("PROJECT_STATUS_BACKLOG_ID")
    
    def ensure_standard_labels(self) -> None:
        """Create standard labels used by analyzer if they don't exist"""
        standard_labels = [
            ("task", "0075ca", "Implementation task created by analyzer"),
            ("sprint", "7057ff", "Sprint container for grouped tasks"),
            ("policy:essential-only", "1f77b4", "Review policy: essential-only"),
            ("policy:strict", "1f77b4", "Review policy: strict"),
            ("policy:lenient", "1f77b4", "Review policy: lenient"),
            ("complexity:low", "ff7f0e", "Estimated complexity: low"),
            ("complexity:medium", "ff7f0e", "Estimated complexity: medium"),
            ("complexity:high", "ff7f0e", "Estimated complexity: high"),
            ("priority:low", "28a745", "Priority: low"),
            ("priority:medium", "ffc107", "Priority: medium"), 
            ("priority:high", "dc3545", "Priority: high"),
            ("bot:implement", "0e8a16", "Ready for AI developer implementation")
            ("need-rewiew", "d73a4a", "PR awaiting reviewer")
        ]
        
        for name, color, description in standard_labels:
            try:
                ensure_label_exists(self.owner, self.repo, name, color, description)
            except Exception as e:
                print(f"Failed to create label '{name}': {e}")
    
    def create_sprint_issue(self, sprint_data: Dict, parent_issue_number: int) -> Optional[int]:
        """
        Create sprint issue from sprint data.
        
        Args:
            sprint_data: Sprint information from plan
            parent_issue_number: Parent issue number
            
        Returns:
            Sprint issue number if successful, None otherwise
        """
        try:
            sprint_title = f"[Sprint] {sprint_data.get('name', 'Sprint 1')}"
            sprint_body = self._build_sprint_body(sprint_data, parent_issue_number)
            sprint_labels = self._build_sprint_labels(sprint_data)
            
            sprint_issue = create_issue(
                self.owner, self.repo, 
                sprint_title, sprint_body, 
                labels=sprint_labels
            )
            
            sprint_number = sprint_issue["number"]
            print(f"Created sprint: #{sprint_number} — {sprint_title}")
            
            # Link to project if available
            self._add_to_project_safe(sprint_number, self.backlog_id)
            
            return sprint_number
            
        except Exception as e:
            print(f"Sprint creation failed: {e}")
            return None
    
    def _build_sprint_body(self, sprint_data: Dict, parent_issue_number: int) -> str:
        """Build sprint issue body"""
        lines = []
        lines.append(f"**Goal**: {sprint_data.get('goal', 'Implementation phase')}")
        lines.append(f"**Duration**: {sprint_data.get('duration', 'TBD')}")
        lines.append(f"**Priority**: {sprint_data.get('priority', 'medium')}")
        lines.append("")
        lines.append(f"**Parent Issue**: #{parent_issue_number}")
        lines.append("")
        lines.append("This sprint contains the initial implementation tasks for the parent issue.")
        
        return "\n".join(lines)
    
    def _build_sprint_labels(self, sprint_data: Dict) -> List[str]:
        """Build sprint labels list"""
        labels = ["sprint"]
        
        priority = sprint_data.get("priority", "medium")
        if priority in ["low", "medium", "high"]:
            labels.append(f"priority:{priority}")
        
        return labels
    
    def create_task_issues(self, tasks: List[Dict], parent_issue_number: int) -> Tuple[List[int], List[int]]:
        """
        Create task issues from task list.
        
        Args:
            tasks: List of task dictionaries from plan
            parent_issue_number: Parent issue number
            
        Returns:
            Tuple of (created_task_numbers, failed_task_indices)
        """
        created_tasks = []
        failed_tasks = []
        
        for i, task in enumerate(tasks, 1):
            try:
                task_number = self._create_single_task(task, i, parent_issue_number)
                if task_number:
                    created_tasks.append(task_number)
                else:
                    failed_tasks.append(i)
                    
            except Exception as e:
                print(f"Task {i} creation failed: {e}")
                failed_tasks.append(i)
        
        print(f"Task creation complete: {len(created_tasks)} successful, {len(failed_tasks)} failed")
        return created_tasks, failed_tasks
    
    def _create_single_task(self, task: Dict, index: int, parent_issue_number: int) -> Optional[int]:
        """Create a single task issue"""
        task_title = task.get("title") or f"Task {index}"
        task_body = self._build_task_body(task, parent_issue_number)
        task_labels = self._build_task_labels(task)
        
        # Create task issue
        task_issue = create_issue(
            self.owner, self.repo,
            task_title, task_body,
            labels=task_labels
        )
        
        task_number = task_issue["number"]
        print(f"Created task #{task_number}: {task_title}")
        
        # Link to project
        self._add_to_project_safe(task_number, self.backlog_id)
        
        return task_number
    
    def _build_task_body(self, task: Dict, parent_issue_number: int) -> str:
        """Build comprehensive task issue body"""
        lines = []
        
        # Description
        if task.get("description"):
            lines.append(task["description"])
            lines.append("")
        
        # Acceptance criteria
        acceptance = task.get("acceptance", [])
        if acceptance:
            lines.append("**Acceptance Criteria**:")
            for criterion in acceptance:
                lines.append(f"- {criterion}")
            lines.append("")
        
        # Files to modify
        paths = task.get("paths", [])
        if paths:
            lines.append("**Files to modify**:")
            for path in paths:
                lines.append(f"- `{path}`")
            lines.append("")
        
        # Dependencies
        depends_on = task.get("depends_on", [])
        if depends_on:
            lines.append("**Dependencies**:")
            for dep in depends_on:
                lines.append(f"- {dep}")
            lines.append("")
        
        # Estimated effort
        estimated_hours = task.get("estimated_hours")
        if estimated_hours:
            lines.append(f"**Estimated effort**: {estimated_hours} hours")
            lines.append("")
        
        # Parent reference
        lines.append(f"**Parent**: #{parent_issue_number}")
        
        return "\n".join(lines).strip() or f"Implementation task from #{parent_issue_number}"
    
    def _build_task_labels(self, task: Dict) -> List[str]:
        """Build task labels list"""
        # Start with base task label
        labels = ["task"]
        
        # Add custom labels from task
        custom_labels = task.get("labels", [])
        if custom_labels:
            labels.extend(custom_labels)
        
        # Add priority label
        priority = task.get("priority", "medium")
        if priority in ["low", "medium", "high"]:
            labels.append(f"priority:{priority}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_labels = []
        for label in labels:
            if label not in seen:
                seen.add(label)
                unique_labels.append(label)
        
        return unique_labels
    
    def apply_policy_and_complexity_labels(self, issue_number: int, plan: Dict, issue_analysis: Dict) -> None:
        """Apply policy and complexity labels to parent issue"""
        labels_to_add = []
        
        # Policy label
        policy = plan.get("policy", "essential-only")
        policy_label = f"policy:{policy}"
        labels_to_add.append(policy_label)
        
        # Complexity label
        complexity = plan.get("complexity", issue_analysis.get("final_complexity", "medium"))
        complexity_label = f"complexity:{complexity}"
        labels_to_add.append(complexity_label)
        
        # Project tag label (if available)
        project_tag = issue_analysis.get("project_tag")
        if project_tag:
            labels_to_add.append(project_tag)
        
        try:
            # Ensure labels exist first
            label_definitions = [
                (policy_label, "1f77b4", f"Review policy: {policy}"),
                (complexity_label, "ff7f0e", f"Estimated complexity: {complexity}")
            ]
            
            if project_tag:
                label_definitions.append((project_tag, "0e8a16", f"Project tag: {project_tag}"))
            
            for name, color, description in label_definitions:
                ensure_label_exists(self.owner, self.repo, name, color, description)
            
            # Apply labels
            add_labels(self.owner, self.repo, issue_number, labels_to_add)
            print(f"Applied labels to #{issue_number}: {', '.join(labels_to_add)}")
            
        except Exception as e:
            print(f"Label application failed for #{issue_number}: {e}")
    
    def auto_start_first_task(self, created_tasks: List[int], parent_issue_number: int) -> bool:
        """
        Auto-start the first created task by adding bot:implement label.
        
        Args:
            created_tasks: List of created task numbers
            parent_issue_number: Parent issue for error reporting
            
        Returns:
            True if successful, False otherwise
        """
        if not created_tasks:
            return False
        
        first_task = created_tasks[0]
        
        try:
            add_labels(self.owner, self.repo, first_task, ["bot:implement"])
            print(f"Auto-started first task: #{first_task}")
            return True
            
        except Exception as e:
            error_msg = f"Could not auto-start task #{first_task}: `{e}`"
            print(error_msg)
            
            # Report error to parent issue
            try:
                post_issue_comment(self.owner, self.repo, parent_issue_number, error_msg)
            except Exception:
                pass  # Don't fail if comment posting fails
            
            return False
    
    def _add_to_project_safe(self, issue_number: int, status_option_id: Optional[str]) -> bool:
        """
        Safely add issue to project with error handling.
        
        Args:
            issue_number: Issue number to add
            status_option_id: Project status option ID
            
        Returns:
            True if successful, False otherwise
        """
        if not self.project_id:
            print("Project integration disabled (no GITHUB_PROJECT_ID/GH_PROJECT_ID)")
            return False
        
        try:
            node_id = get_issue_node_id(self.owner, self.repo, issue_number)
            item_id = add_item_to_project(self.project_id, node_id)
            
            if self.status_field_id and status_option_id:
                set_project_single_select(
                    self.project_id, item_id, 
                    self.status_field_id, status_option_id
                )
            
            print(f"Issue #{issue_number} linked to project")
            return True
            
        except Exception as e:
            error_msg = str(e).lower()
            if "scope" in error_msg or "permission" in error_msg:
                print(f"Project linking requires GH_CLASSIC_TOKEN with 'project' scope for #{issue_number}")
            else:
                print(f"Project linking failed for #{issue_number}: {e}")
            
            return False
    
    def create_execution_summary(self, 
                                created_tasks: List[int],
                                failed_tasks: List[int],
                                sprint_number: Optional[int],
                                plan: Dict) -> str:
        """Create execution summary message"""
        lines = []
        
        # Basic results
        policy = plan.get("policy", "essential-only")
        complexity = plan.get("complexity", "medium")
        
        lines.append("## Analysis Complete")
        lines.append(f"**Policy**: {policy}")
        lines.append(f"**Complexity**: {complexity}")
        lines.append(f"**Sprints created**: {1 if sprint_number else 0}")
        lines.append(f"**Tasks created**: {len(created_tasks)}")
        
        if failed_tasks:
            lines.append(f"**Failed tasks**: {len(failed_tasks)}")
        
        # Next steps
        if created_tasks:
            lines.append("")
            lines.append("## Next Steps:")
            lines.append(f"- First task #{created_tasks[0]} is auto-labeled for `bot:implement`")
            lines.append("- Add `bot:implement` label to other tasks to trigger development")
            lines.append("- Tasks will be processed sequentially as PRs are completed")
        
        # Project integration note
        if not os.getenv("GH_CLASSIC_TOKEN"):
            lines.append("")
            lines.append("**Note**: Set `GH_CLASSIC_TOKEN` for full project integration")
        
        return "\n".join(lines)
