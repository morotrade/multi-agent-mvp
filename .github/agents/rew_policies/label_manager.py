#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Label management for AI Reviewer
"""
from typing import Set, List

from utils.github_api import get_pr_labels, add_labels, remove_label, get_repo_info


class LabelManager:
    """Handles PR label operations for reviewer workflow"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
    
    def get_pr_labels_set(self, pr_number: int) -> Set[str]:
        """Get PR labels as lowercase set for easy checking"""
        try:
            labels_data = get_pr_labels(self.owner, self.repo, pr_number)
            return {label["name"].lower() for label in labels_data}
        except Exception:
            return set()
    
    def detect_policy_from_labels(self, pr_labels: Set[str]) -> str:
        """
        Detect review policy from PR labels.
        Returns: 'strict', 'lenient', or 'essential-only' (default)
        """
        if "policy:strict" in pr_labels:
            return "strict"
        elif "policy:lenient" in pr_labels:
            return "lenient"
        else:
            return "essential-only"
    
    def apply_review_labels(self, pr_number: int, must_fix: bool) -> None:
        """
        Apply appropriate labels based on review results.
        
        Args:
            pr_number: PR number
            must_fix: Whether PR has issues that must be fixed
        """
        if must_fix:
            # Add need-fix, remove ready-to-merge
            self._add_label_safe(pr_number, "need-fix")
            self._remove_label_safe(pr_number, "ready-to-merge")
            print("Applied label: need-fix")
        else:
            # Remove need-fix, add ready-to-merge
            self._remove_label_safe(pr_number, "need-fix")
            self._add_label_safe(pr_number, "ready-to-merge")
            print("Applied label: ready-to-merge")
    
    def _add_label_safe(self, pr_number: int, label: str) -> None:
        """Add label with error handling"""
        try:
            add_labels(self.owner, self.repo, pr_number, [label])
        except Exception as e:
            print(f"Failed to add label '{label}': {e}")
    
    def _remove_label_safe(self, pr_number: int, label: str) -> None:
        """Remove label with error handling"""
        try:
            remove_label(self.owner, self.repo, pr_number, label)
        except Exception as e:
            print(f"Failed to remove label '{label}': {e}")
    
    def ensure_policy_labels_exist(self) -> None:
        """Create standard policy labels if they don't exist"""
        from utils.github_api import ensure_label_exists
        
        policy_labels = [
            ("policy:strict", "D73A49", "Strict review policy - fail on IMPORTANT+ issues"),
            ("policy:lenient", "28A745", "Lenient review policy - always pass"),
            ("need-fix", "D73A49", "PR has issues that must be addressed"),
            ("ready-to-merge", "28A745", "PR passed review and is ready to merge")
        ]
        
        for name, color, description in policy_labels:
            try:
                ensure_label_exists(self.owner, self.repo, name, color, description)
            except Exception as e:
                print(f"Failed to create label '{name}': {e}")
