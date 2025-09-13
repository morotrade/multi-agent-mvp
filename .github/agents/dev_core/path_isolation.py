#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Path isolation and project root management for AI Developer
"""
import os
import re
from typing import List

from utils import resolve_project_tag, slugify


def compute_project_root_for_issue(issue_number: int, issue_title: str, issue_body: str) -> str:
    """
    Compute isolated project root for issue implementation.
    Priority: PROJECT_ROOT env > project tag > slug-based path
    """
    override = os.getenv("PROJECT_ROOT")
    if override:
        return override.strip().strip("/").replace("\\", "/")
    
    # Try to extract project tag from issue body
    tag = resolve_project_tag(issue_body) or ""
    if tag:
        return f"projects/{tag}"
    
    # Fallback to slug-based path
    slug = slugify(issue_title or f"issue-{issue_number}")
    return f"projects/issue-{issue_number}-{slug}"


def compute_project_root_for_pr(pr_number: int, pr_body: str) -> str:
    """
    Compute isolated project root for PR fixes.
    Priority: PROJECT_ROOT env > project tag > pr-based path
    """
    override = os.getenv("PROJECT_ROOT")
    if override:
        return override.strip().strip("/").replace("\\", "/")
    
    # Try to extract project tag from PR body
    tag = resolve_project_tag(pr_body or "") or ""
    if tag:
        return f"projects/{tag}"
    
    return f"projects/pr-{pr_number}"


def ensure_dir(path: str) -> None:
    """Ensure directory exists"""
    os.makedirs(path, exist_ok=True)


def enforce_diff_under_root(diff_text: str, project_root: str) -> None:
    """
    Oltre a validate_diff_files(whitelist/denylist), imponiamo che TUTTI i path
    tocchino project_root (o siano file consentiti tipo README.md a radice progetto)
    """
    # Raccogli i path dal diff usando regex per +++ b/path
    paths = re.findall(r"^\+\+\+ b/(.+)$", diff_text, flags=re.M)
    violations = []
    
    project_root_normalized = project_root.rstrip("/")
    
    for path in paths:
        path_normalized = path.strip().lstrip("./")
        
        # Check if path is under project root or is an allowed root-level file
        allowed_conditions = [
            path_normalized.startswith(project_root_normalized + "/"),
            path_normalized == f"{project_root_normalized}/README.md",
            path_normalized == "README.md"  # Allow root README
        ]
        
        if not any(allowed_conditions):
            violations.append(path_normalized)
    
    if violations:
        raise RuntimeError(
            f"Diff contains files outside project root '{project_root}': {violations}"
        )


def extract_project_paths_from_diff(diff_text: str) -> List[str]:
    """Extract all file paths from a unified diff"""
    return re.findall(r"^\+\+\+ b/(.+)$", diff_text, flags=re.M)
