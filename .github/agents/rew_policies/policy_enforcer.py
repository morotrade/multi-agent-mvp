#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Policy enforcement logic for AI Reviewer
"""
import os
import re
from typing import Dict, Optional

from utils.github_api import graphql_request, get_issue_node_id, add_item_to_project, set_project_single_select, get_repo_info


class PolicyEnforcer:
    """Handles policy enforcement and project status updates"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
        
        # Project integration settings
        self.project_id = os.getenv("GH_PROJECT_ID") or os.getenv("GITHUB_PROJECT_ID")
        self.status_field_id = os.getenv("PROJECT_STATUS_FIELD_ID")
        self.in_review_option_id = os.getenv("PROJECT_STATUS_INREVIEW_ID")
    
    def determine_must_fix(self, policy_name: str, blockers: int, importants: int) -> bool:
        """
        Determine if PR must be fixed based on policy and issue counts.
        
        Args:
            policy_name: 'strict', 'lenient', or 'essential-only'
            blockers: Number of blocking issues
            importants: Number of important issues
            
        Returns:
            True if PR must be fixed before merge
        """
        if policy_name == "lenient":
            return False  # Lenient policy never requires fixes
        elif policy_name == "essential-only":
            return blockers > 0  # Only blockers require fixes
        elif policy_name == "strict":
            return blockers > 0 or importants > 0  # Both blockers and importants require fixes
        else:
            # Unknown policy, default to essential-only
            return blockers > 0
    
    def calculate_exit_code(self, policy_name: str, blockers: int, importants: int) -> int:
        """
        Calculate exit code for CI/CD based on policy and findings.
        
        Args:
            policy_name: Review policy
            blockers: Number of blocking issues
            importants: Number of important issues
            
        Returns:
            0 for success, 1 for failure
        """
        if policy_name == "lenient":
            return 0  # Always pass
        elif policy_name == "essential-only":
            return 1 if blockers > 0 else 0
        elif policy_name == "strict":
            return 1 if (blockers > 0 or importants > 0) else 0
        else:
            # Unknown policy, default to essential-only
            return 1 if blockers > 0 else 0
    
    def extract_source_issue_from_pr_body(self, pr_body: str) -> Optional[int]:
        """
        Extract issue number from PR body using common patterns.
        Looks for 'Closes #123', 'Fixes #456', etc.
        """
        if not pr_body:
            return None
            
        pattern = r"(?:close[sd]?|fixe[sd]?|resolve[sd]?)\s+#(\d+)"
        match = re.search(pattern, pr_body, re.IGNORECASE)
        
        if match:
            return int(match.group(1))
        
        return None
    
    def update_project_status_to_in_review(self, source_issue_number: int) -> bool:
        """
        Update GitHub Project status to 'In Review' for the source issue.
        
        Args:
            source_issue_number: Issue number to update
            
        Returns:
            True if successful, False otherwise
        """
        if not all([self.project_id, self.status_field_id, self.in_review_option_id]):
            print("Project integration disabled (missing env vars)")
            return False
        
        try:
            # Get issue node ID
            node_id = get_issue_node_id(self.owner, self.repo, source_issue_number)
            
            # Add item to project (idempotent operation)
            item_id = add_item_to_project(self.project_id, node_id)
            
            # Set status to 'In Review'
            set_project_single_select(
                self.project_id, 
                item_id, 
                self.status_field_id, 
                self.in_review_option_id
            )
            
            print(f"Project status set to 'In Review' for issue #{source_issue_number}")
            return True
            
        except Exception as e:
            print(f"Project update failed (non-blocking): {e}")
            return False
    
    def enforce_policy_and_get_exit_code(self, 
                                        policy_name: str, 
                                        blockers: int, 
                                        importants: int,
                                        suggestions: int) -> int:
        """
        Log policy enforcement decision and return appropriate exit code.
        
        Args:
            policy_name: Review policy name
            blockers: Blocker count
            importants: Important issues count  
            suggestions: Suggestions count
            
        Returns:
            Exit code for the process
        """
        exit_code = self.calculate_exit_code(policy_name, blockers, importants)
        
        if policy_name == "lenient":
            print(f"Policy: lenient - always pass (exit 0)")
        elif policy_name == "essential-only":
            print(f"Policy: essential-only - exit {exit_code} (blockers={blockers})")
        elif policy_name == "strict":
            print(f"Policy: strict - exit {exit_code} (blockers={blockers}, importants={importants})")
        else:
            print(f"Policy: unknown '{policy_name}' - defaulting to essential-only, exit {exit_code}")
        
        return exit_code
