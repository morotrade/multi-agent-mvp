"""
Utils module - GitHub + LLM helpers for MultiAgent workflows
"""

# Import e re-export di tutte le funzioni
from .diff_processing import (
    extract_single_diff, apply_diff_resilient, apply_diff_manually
)

from .file_validation import (
    get_whitelist_patterns, get_denylist_patterns, paths_from_unified_diff,
    is_path_allowed, is_path_denied, validate_diff_files
)

from .github_api import (
    get_github_headers, get_github_graphql_headers,
    post_issue_comment, create_issue, add_labels, add_labels_to_issue,
    ensure_label_exists, get_issue_node_id, get_issue,
    add_item_to_project, set_project_single_select, get_repo_language,
    get_token, get_repo_info, rest_request, graphql_request,
    get_pr, get_pr_files, get_pr_comments, update_comment,
    create_pr, get_pr_labels, remove_label, get_repo_details,
    get_default_branch
)

from .issue_parsing import (
    slugify, resolve_project_tag, extract_requirements_from_issue,
    format_issue_summary
)

from .llm_providers import (
    call_llm_api, call_openai_api, call_anthropic_api, call_gemini_api,
    get_preferred_model
)

from .system_info import (
    validate_environment, get_system_info
)

# Re-export everything
__all__ = [
    # Diff processing
    'extract_single_diff', 'apply_diff_resilient', 'apply_diff_manually',
    
    # File validation
    'get_whitelist_patterns', 'get_denylist_patterns', 'paths_from_unified_diff',
    'is_path_allowed', 'is_path_denied', 'validate_diff_files',
    
    # GitHub API
    'get_github_headers', 'get_github_graphql_headers',
    'post_issue_comment', 'create_issue', 'add_labels', 'add_labels_to_issue',
    'ensure_label_exists', 'get_issue_node_id', 'get_issue',
    'add_item_to_project', 'set_project_single_select', 'get_repo_language',
    'get_token', 'get_repo_info', 'rest_request', 'graphql_request',
    'get_pr', 'get_pr_files', 'get_pr_comments', 'update_comment',
    'create_pr', 'get_pr_labels', 'remove_label', 'get_repo_details',
    'get_default_branch',
    
    # Issue parsing
    'slugify', 'resolve_project_tag', 'extract_requirements_from_issue',
    'format_issue_summary',
    
    # LLM providers
    'call_llm_api', 'call_openai_api', 'call_anthropic_api', 'call_gemini_api',
    'get_preferred_model',
    
    # System info
    'validate_environment', 'get_system_info'
]