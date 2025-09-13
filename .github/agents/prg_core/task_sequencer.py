#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Task sequencing and sibling detection for Progress Manager
"""
from typing import List, Dict, Optional

from utils.github_api import rest_request, get_repo_info


class TaskSequencer:
    """Handles sibling task detection and next task selection logic"""
    
    def __init__(self):
        self.owner, self.repo = get_repo_info()
    
    def find_sibling_tasks(self, parent_issue_number: int, exclude_issue: Optional[int] = None) -> List[Dict]:
        """
        Find open issues that reference the same parent issue.
        Uses GitHub Search API with multiple query strategies.
        
        Args:
            parent_issue_number: Parent issue number to search for
            exclude_issue: Issue number to exclude from results (e.g., just closed issue)
            
        Returns:
            List of sibling issue dictionaries
        """
        try:
            # Multiple search strategies to catch different reference formats
            queries = [
                f'repo:{self.owner}/{self.repo} is:issue is:open in:body "Parent: #{parent_issue_number}"',
                f'repo:{self.owner}/{self.repo} is:issue is:open in:body "parent #{parent_issue_number}"',
                f'repo:{self.owner}/{self.repo} is:issue is:open in:body "**Parent**: #{parent_issue_number}"',
                f'repo:{self.owner}/{self.repo} is:issue is:open in:body "#{parent_issue_number}"',
            ]
            
            all_results = []
            for query in queries:
                try:
                    siblings = self._execute_search_query(query)
                    all_results.extend(siblings)
                except Exception as e:
                    print(f"Search query failed: {query[:50]}... - {e}")
                    continue
            
            # Deduplicate and filter results
            unique_siblings = self._deduplicate_and_filter(all_results, parent_issue_number, exclude_issue)
            
            print(f"Found {len(unique_siblings)} sibling tasks for parent #{parent_issue_number}")
            return unique_siblings
            
        except Exception as e:
            print(f"Warning: Sibling search failed: {e}")
            return []
    
    def _execute_search_query(self, query: str) -> List[Dict]:
        """Execute a single search query and return results"""
        response = rest_request("GET", f"/search/issues", params={
            "q": query,     # httpx/requests gestiscono encoding dei params
            "per_page": 100
        })
        
        if response and isinstance(response, dict):
            return response.get("items", [])
        
        return []
    
    def _deduplicate_and_filter(self, results: List[Dict], parent_number: int, exclude_issue: Optional[int]) -> List[Dict]:
        """
        Deduplicate results and filter out invalid siblings.
        
        Args:
            results: Raw search results
            parent_number: Parent issue number for validation
            exclude_issue: Issue to exclude from results
            
        Returns:
            Filtered and deduplicated list
        """
        seen_numbers = set()
        valid_siblings = []
        
        for item in results:
            issue_number = item.get("number")
            
            # Skip if no number or already seen
            if not issue_number or issue_number in seen_numbers:
                continue
            
            # Skip if this is the excluded issue
            if exclude_issue and issue_number == exclude_issue:
                continue
            
            # Skip if this is the parent issue itself
            if issue_number == parent_number:
                continue
            
            # Validate that this is actually a sibling by checking body
            if self._validate_sibling_relationship(item, parent_number):
                seen_numbers.add(issue_number)
                valid_siblings.append(item)
        
        return valid_siblings
    
    def _validate_sibling_relationship(self, issue: Dict, parent_number: int) -> bool:
        """
        Validate that an issue is actually a sibling by checking its body for parent reference.
        
        Args:
            issue: Issue dictionary from search results
            parent_number: Expected parent issue number
            
        Returns:
            True if valid sibling, False otherwise
        """
        body = issue.get("body") or ""
        
        # Look for explicit parent references
        import re
        patterns = [
            rf"\*\*Parent\*\*\s*:\s*#{parent_number}\b",
            rf"(?i)\bParent\s*:\s*#{parent_number}\b",
            rf"(?i)\bParent\s+issue\s*:\s*#{parent_number}\b",
            rf"(?i)\bTask\s+from\s+#{parent_number}\b",
        ]
        
        for pattern in patterns:
            if re.search(pattern, body):
                return True
        
        # Also check title for parent references (less common but possible)
        title = issue.get("title") or ""
        if f"#{parent_number}" in title:
            return True
        
        return False
    
    def select_next_task(self, sibling_tasks: List[Dict], strategy: str = "oldest_first") -> Optional[Dict]:
        """
        Select the next task to execute from available siblings.
        
        Args:
            sibling_tasks: List of sibling task issues
            strategy: Selection strategy ('oldest_first', 'newest_first', 'priority_based')
            
        Returns:
            Next task issue dictionary or None if no tasks available
        """
        if not sibling_tasks:
            return None
        
        if strategy == "oldest_first":
            # Select task with lowest number (oldest)
            return min(sibling_tasks, key=lambda x: x.get("number", float('inf')))
        
        elif strategy == "newest_first":
            # Select task with highest number (newest)
            return max(sibling_tasks, key=lambda x: x.get("number", 0))
        
        elif strategy == "priority_based":
            # Select based on priority labels, fallback to oldest
            return self._select_by_priority(sibling_tasks)
        
        else:
            # Default to oldest first
            print(f"Unknown strategy '{strategy}', using oldest_first")
            return self.select_next_task(sibling_tasks, "oldest_first")
    
    def _select_by_priority(self, tasks: List[Dict]) -> Optional[Dict]:
        """
        Select task based on priority labels with fallback to oldest.
        
        Priority order: high -> medium -> low -> unlabeled
        """
        # Group tasks by priority
        priority_groups = {
            "high": [],
            "medium": [],
            "low": [],
            "unlabeled": []
        }
        
        for task in tasks:
            labels = task.get("labels", [])
            label_names = {label.get("name", "").lower() for label in labels if isinstance(label, dict)}
            
            # Determine priority from labels
            if "priority:high" in label_names or "high priority" in label_names:
                priority_groups["high"].append(task)
            elif "priority:medium" in label_names or "medium priority" in label_names:
                priority_groups["medium"].append(task)
            elif "priority:low" in label_names or "low priority" in label_names:
                priority_groups["low"].append(task)
            else:
                priority_groups["unlabeled"].append(task)
        
        # Select from highest priority group available
        for priority in ["high", "medium", "low", "unlabeled"]:
            group = priority_groups[priority]
            if group:
                # Within same priority, select oldest (lowest number)
                selected = min(group, key=lambda x: x.get("number", float('inf')))
                print(f"Selected task by priority: {priority}")
                return selected
        
        return None
    
    def analyze_task_dependencies(self, tasks: List[Dict]) -> Dict:
        """
        Analyze dependencies between tasks to optimize sequencing.
        
        Args:
            tasks: List of sibling tasks
            
        Returns:
            Dictionary with dependency analysis results
        """
        analysis = {
            "total_tasks": len(tasks),
            "has_dependencies": False,
            "blocking_tasks": [],
            "blocked_tasks": [],
            "independent_tasks": [],
            "dependency_chains": []
        }
        
        if not tasks:
            return analysis
        
        # Simple dependency analysis based on task body content
        import re
        for task in tasks:
            task_number = task.get("number")
            body = task.get("body", "")
            title = task.get("title", "")
            
            # Look for dependency keywords
            dependency_patterns = [
                r"(?i)\bdepends?\s+on\s+#(\d+)",
                r"(?i)\bblocked\s+by\s+#(\d+)",
                r"(?i)\brequires?\s+#(\d+)",
                r"(?i)\bafter\s+#(\d+)",
            ]
            
            blocking_patterns = [
                r"(?i)\bblocks?\s+#(\d+)",
                r"(?i)\brequired\s+by\s+#(\d+)",
                r"(?i)\bbefore\s+#(\d+)",
            ]
            
            # Check for dependencies (this task depends on others)
            for pattern in dependency_patterns:
                matches = re.findall(pattern, body + " " + title)
                if matches:
                    analysis["has_dependencies"] = True
                    analysis["blocked_tasks"].append({
                        "task": task_number,
                        "depends_on": [int(m) for m in matches]
                    })
                    break
            
            # Check for blocking relationships (this task blocks others)
            for pattern in blocking_patterns:
                matches = re.findall(pattern, body + " " + title)
                if matches:
                    analysis["has_dependencies"] = True
                    analysis["blocking_tasks"].append({
                        "task": task_number,
                        "blocks": [int(m) for m in matches]
                    })
                    break
            
            # If no dependencies found, mark as independent
            if (task_number not in [item["task"] for item in analysis["blocked_tasks"]] and
                task_number not in [item["task"] for item in analysis["blocking_tasks"]]):
                analysis["independent_tasks"].append(task_number)
        
        return analysis
    
    def get_sequencing_recommendation(self, tasks: List[Dict]) -> Dict:
        """
        Get comprehensive recommendation for task sequencing.
        
        Args:
            tasks: List of sibling tasks
            
        Returns:
            Dictionary with sequencing recommendations
        """
        if not tasks:
            return {"recommendation": "no_tasks", "next_task": None, "rationale": "No tasks available"}
        
        dependency_analysis = self.analyze_task_dependencies(tasks)
        
        # If no dependencies, use priority-based selection
        if not dependency_analysis["has_dependencies"]:
            next_task = self.select_next_task(tasks, "priority_based")
            return {
                "recommendation": "priority_based",
                "next_task": next_task,
                "rationale": "No dependencies detected, selecting by priority and age",
                "alternative_tasks": [t for t in tasks if t != next_task]
            }
        
        # If there are dependencies, prioritize unblocked tasks
        independent_numbers = set(dependency_analysis["independent_tasks"])
        independent_tasks = [t for t in tasks if t.get("number") in independent_numbers]
        
        if independent_tasks:
            next_task = self.select_next_task(independent_tasks, "priority_based")
            return {
                "recommendation": "dependency_aware",
                "next_task": next_task,
                "rationale": f"Selected from {len(independent_tasks)} independent tasks to avoid blocking",
                "dependencies_found": dependency_analysis["has_dependencies"]
            }
        
        # If all tasks have dependencies, select oldest and warn
        next_task = self.select_next_task(tasks, "oldest_first")
        return {
            "recommendation": "fallback_oldest",
            "next_task": next_task,
            "rationale": "All tasks have dependencies, selecting oldest with warning",
            "warning": "Potential dependency conflicts detected"
        }
