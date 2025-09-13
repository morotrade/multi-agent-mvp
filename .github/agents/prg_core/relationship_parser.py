#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Issue relationship parsing for Progress Manager
"""
import re
from typing import Optional, Dict, Tuple, Any

from utils.github_api import get_issue, get_repo_info


class RelationshipParser:
    """Parses issue relationships and closing patterns"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
    
    def extract_closing_issue_from_pr(self, pr: Dict) -> Optional[int]:
        """
        Extract 'Closes #<n>' issue number from PR body using enhanced pattern matching.
        
        Args:
            pr: PR dictionary
            
        Returns:
            Issue number if found, None otherwise
        """
        body = pr.get("body") or ""
        
        if not body.strip():
            return None
        
        # Multiple patterns to catch various closing keywords and formats
        patterns = [
            # Standard GitHub closing keywords
            r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b",
            # With explicit "issue" keyword
            r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:issue\s+)?#(\d+)\b",
            # Issue number followed by closing keyword
            r"(?i)#(\d+)\s+(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b",
            # GitHub's alternative formats
            r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+(?:https://github\.com/[^/]+/[^/]+/issues/)?(\d+)\b",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                issue_number = int(match.group(1))
                print(f"Found closing pattern: issue #{issue_number}")
                return issue_number
        
        return None
    
    def extract_parent_from_issue(self, issue: Dict) -> Optional[int]:
        """
        Extract parent issue number from issue body.
        
        Args:
            issue: Issue dictionary
            
        Returns:
            Parent issue number if found, None otherwise
        """
        body = issue.get("body") or ""
        
        if not body.strip():
            return None
        
        # Patterns for parent references
        patterns = [
            # **Parent**: #123 format (common in task issues)
            r"\*\*Parent\*\*\s*:\s*#(\d+)\b",
            # Parent: #123 format
            r"(?i)\bParent\s*:\s*#(\d+)\b",
            # Parent issue #123
            r"(?i)\bParent\s+issue\s*:\s*#(\d+)\b",
            # Created from #123
            r"(?i)\bCreated\s+from\s+#(\d+)\b",
            # Task from #123
            r"(?i)\bTask\s+from\s+#(\d+)\b",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                parent_number = int(match.group(1))
                print(f"Found parent reference: issue #{parent_number}")
                return parent_number
        
        return None
    
    def get_issue_safe(self, issue_number: int) -> Optional[Dict]:
        """
        Safely get issue details with error handling.
        
        Args:
            issue_number: Issue number to fetch
            
        Returns:
            Issue dictionary if successful, None otherwise
        """
        try:
            return get_issue(self.owner, self.repo, issue_number)
        except Exception as e:
            print(f"Warning: Could not fetch issue #{issue_number}: {e}")
            return None
    
    def analyze_pr_issue_chain(self, pr: Dict) -> Tuple[Optional[int], Optional[int], Optional[Dict]]:
        """
        Analyze the complete PR -> Issue -> Parent chain.
        
        Args:
            pr: PR dictionary
            
        Returns:
            Tuple of (closing_issue_number, parent_issue_number, parent_issue_dict)
        """
        # Step 1: Extract closing issue from PR
        closing_issue_number = self.extract_closing_issue_from_pr(pr)
        if not closing_issue_number:
            print("PR does not close any issue")
            return None, None, None
        
        # Step 2: Get the closing issue details
        closing_issue = self.get_issue_safe(closing_issue_number)
        if not closing_issue:
            print(f"Could not fetch closing issue #{closing_issue_number}")
            return closing_issue_number, None, None
        
        # Step 3: Extract parent from closing issue
        parent_issue_number = self.extract_parent_from_issue(closing_issue)
        if not parent_issue_number:
            print(f"Issue #{closing_issue_number} has no parent reference")
            return closing_issue_number, None, None
        
        # Step 4: Get parent issue details
        parent_issue = self.get_issue_safe(parent_issue_number)
        if not parent_issue:
            print(f"Could not fetch parent issue #{parent_issue_number}")
            return closing_issue_number, parent_issue_number, None
        
        return closing_issue_number, parent_issue_number, parent_issue
    
    def validate_issue_hierarchy(self, closing_issue_number: int, parent_issue_number: int) -> bool:
        """
        Validate that the issue hierarchy makes sense.
        
        Args:
            closing_issue_number: The issue being closed
            parent_issue_number: The supposed parent issue
            
        Returns:
            True if hierarchy is valid, False otherwise
        """
        if not closing_issue_number or not parent_issue_number:
            return False
        
        # Parent should be different from child
        if closing_issue_number == parent_issue_number:
            print(f"Warning: Issue #{closing_issue_number} references itself as parent")
            return False
        
        # Parent should typically have a higher number (created first) 
        # But this is not a strict requirement, just a warning
        if parent_issue_number > closing_issue_number:
            print(f"Notice: Parent #{parent_issue_number} has higher number than child #{closing_issue_number}")
        
        return True
    
    def get_relationship_summary(self, closing_issue: Optional[int], parent_issue: Optional[int]) -> str:
        """Generate human-readable summary of issue relationships"""
        if not closing_issue:
            return "No closing issue found"
        
        if not parent_issue:
            return f"Issue #{closing_issue} closes but has no parent"
        
        return f"Issue #{closing_issue} (child of #{parent_issue}) is being closed"
    
    def detect_relationship_patterns(self, issue_body: str) -> Dict[str, any]:
        """
        Detect various relationship patterns in issue body.
        
        Args:
            issue_body: Issue body text
            
        Returns:
            Dictionary with detected patterns and metadata
        """
        patterns = {
            "has_parent": bool(self.extract_parent_from_issue({"body": issue_body})),
            "mentions_issues": len(re.findall(r"#(\d+)", issue_body)),
            "has_task_markers": bool(re.search(r"(?i)\b(?:task|subtask|sub-task)\b", issue_body)),
            "has_sprint_markers": bool(re.search(r"(?i)\b(?:sprint|milestone|phase)\b", issue_body)),
            "has_dependency_markers": bool(re.search(r"(?i)\b(?:depends?\s+on|blocked\s+by|requires?)\b", issue_body)),
        }
        
        # Extract all issue references
        issue_refs = [int(match) for match in re.findall(r"#(\d+)", issue_body)]
        patterns["referenced_issues"] = issue_refs
        
        return patterns
