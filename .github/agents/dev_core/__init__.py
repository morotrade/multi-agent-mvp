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
from .guards import enforce_all
from .prompt_blocks import (
    constraints_block, diff_format_block, files_list_block, findings_block, snapshots_block
)
from .snapshots import collect_snapshots
from .errors import comment_with_llm_preview
from .diff_helpers import normalize_diff_headers_against_fs

__all__ = [
    'GitOperations',
    'GitHubClient', 
    'DiffProcessor',
    'compute_project_root_for_issue',
    'compute_project_root_for_pr',
    'enforce_diff_under_root',
    'ensure_dir',
    "enforce_all",
    "constraints_block", "diff_format_block", "files_list_block", "findings_block", "snapshots_block",
    "collect_snapshots",
    "comment_with_llm_preview",
    "comment_with_llm_preview",
    "normalize_diff_headers_against_fs",
]
