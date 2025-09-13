#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project root detection and path scope validation for AI Reviewer
"""
import os
import re
from typing import Dict, List, Tuple, Set, Optional

from utils.issue_parsing import slugify


class ProjectDetector:
    """Handles project root detection and path scope validation"""
    
    def __init__(self, 
                 base_dir: str = None,
                 tag_name: str = None,
                 enforce_scope: bool = None):
        self.base_dir = base_dir or os.getenv("PROJECT_ROOT_BASE", "projects")
        self.tag_name = tag_name or os.getenv("PROJECT_ROOT_TAG", "project")
        self.enforce_scope = enforce_scope if enforce_scope is not None else os.getenv("ENFORCE_PROJECT_ROOT", "0") == "1"
    
    def detect_project_tag_from_text(self, text: str) -> Optional[str]:
        """
        Extract project tag from text using various patterns.
        Looks for: 'project: name', '[project: name]', etc.
        """
        if not text:
            return None
        
        # Common patterns for project tags
        pattern = rf"(?im)(?:^|\s)(?:{re.escape(self.tag_name)}\s*:\s*|\[{re.escape(self.tag_name)}:\s*)([a-z0-9._\-\s]{{1,50}})\]?"
        match = re.search(pattern, text)
        
        if match:
            return slugify(match.group(1))
        
        return None
    
    def compute_project_root(self, pr_data: Dict, files_data: List[Dict], pr_labels: Set[str]) -> str:
        """
        Compute project root using priority rules:
        1. Label containing 'project: <tag>' 
        2. PR body/title containing project tag
        3. Common first-level directory from files
        4. Fallback to projects/pr-<number>
        """
        pr_number = pr_data.get("number", 0)
        
        # 1. Check labels for project tag
        tag = None
        tag_prefix = f"{self.tag_name.lower()}:"
        
        for label in pr_labels:
            label_lower = label.lower()
            if label_lower.startswith(tag_prefix):
                tag = slugify(label_lower.split(":", 1)[1])
                break
        
        # 2. Check PR body and title
        if not tag:
            body = pr_data.get("body", "")
            title = pr_data.get("title", "")
            
            tag = (self.detect_project_tag_from_text(body) or 
                   self.detect_project_tag_from_text(title))
        
        if tag:
            return f"{self.base_dir}/{tag}"
        
        # 3. Try to infer from common file path prefix
        paths = [f.get("filename", "") for f in files_data if f.get("filename")]
        first_levels = set()
        
        for path in paths:
            if "/" in path:
                first_level = path.split("/", 1)[0]
                if first_level:
                    first_levels.add(first_level)
        
        # If all files share the same top-level directory, use it
        if len(first_levels) == 1:
            return list(first_levels)[0]
        
        # 4. Fallback to PR-specific directory
        return f"{self.base_dir}/pr-{pr_number}"
    
    def validate_files_under_root(self, files_data: List[Dict], project_root: str) -> Tuple[bool, List[str]]:
        """
        Check if all files are under the project root.
        Returns (all_valid, offending_files).
        """
        offenders = []
        root_normalized = project_root.rstrip("/") + "/"
        
        for file_data in files_data:
            filename = file_data.get("filename", "")
            if filename and not filename.startswith(root_normalized):
                offenders.append(filename)
        
        return len(offenders) == 0, offenders
    
    def create_scope_violation_finding(self, project_root: str, offenders: List[str]) -> Dict:
        """Create a structured finding for scope violations"""
        level = "BLOCKER" if self.enforce_scope else "IMPORTANT"
        
        # Show up to 5 offenders for readability
        offender_list = ", ".join(offenders[:5])
        if len(offenders) > 5:
            offender_list += f" (and {len(offenders) - 5} more)"
        
        message = f"Files modified outside enforced project root `{project_root}`"
        suggestion = f"Move all changes under `{project_root}`. Offending files: {offender_list}"
        
        if self.enforce_scope:
            suggestion += " (ENFORCEMENT: This violation blocks the PR)"
        
        return {
            "level": level,
            "file": project_root,
            "line": None,
            "message": message,
            "suggestion": suggestion
        }
    
    def get_scope_summary_note(self, project_root: str, offenders: List[str]) -> str:
        """Generate summary note for scope violations"""
        offender_preview = ", ".join(offenders[:10])
        if len(offenders) > 10:
            offender_preview += f" (and {len(offenders) - 10} more)"
        
        note = f"Files outside project root `{project_root}`: {offender_preview}"
        
        if self.enforce_scope:
            note += "\n**ENFORCEMENT**: This violation is treated as a BLOCKER."
        
        return note
