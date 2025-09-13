"""
Core modules for AI Developer
"""
from .git_operations import GitOperations
from .github_client import GitHubClient
from .diff_processor import DiffProcessor
from .path_isolation import (
    compute_project_root_for_issue,
    compute_project_root_for_pr,
    enforce_diff_under_root,
    ensure_dir
)

__all__ = [
    'GitOperations',
    'GitHubClient', 
    'DiffProcessor',
    'compute_project_root_for_issue',
    'compute_project_root_for_pr',
    'enforce_diff_under_root',
    'ensure_dir'
]