# -*- coding: utf-8 -*-
"""
File path validation and security guards
"""
import re
import fnmatch
from typing import List
from pathlib import PurePosixPath

def get_whitelist_patterns() -> List[str]:
    """File patterns that are allowed to be modified"""
    return [
        "src/**","lib/**","utils/**","app/**","components/**",
        "projects/**",  # CRITICAL: Allow projects directory
        "**/*.py","**/*.js","**/*.ts","**/*.jsx","**/*.tsx",
        "**/*.java","**/*.go","**/*.rs","**/*.php","**/*.rb",
        "**/*.css","**/*.scss","**/*.html","**/*.vue","**/*.svelte",
        "tests/**","test/**","__tests__/**","spec/**",
        "docs/**","documentation/**",
        "*.md","*.txt","*.rst","*.yml","*.yaml","*.json",
        "LICENSE*","README*","CHANGELOG*","CONTRIBUTING*",
        "package.json","requirements.txt","Cargo.toml","go.mod"
    ]

def get_denylist_patterns() -> List[str]:
    """File patterns that are never allowed to be modified"""
    return [
        ".github/**",".git/**","infra/**","infrastructure/**",
        "deploy/**","deployment/**","k8s/**","terraform/**",
        "**/*.env","**/.env.*","**/secrets/**","**/secret/**",
        "**/id_rsa*","**/*.key","**/*.pem","**/*.p12","**/*.jks",
        "ssh/*","**/ssh/**",".aws/**","config/secrets/**",
        "**/credentials*","**/*credential*","**/token*",
        "**/docker-compose*.yml","**/Dockerfile*","**/*.dockerfile",
        "node_modules/**","vendor/**","venv/**","__pycache__/**",
        "*.log","**/*.log","logs/**","tmp/**","temp/**"
    ]

def paths_from_unified_diff(diff: str) -> List[str]:
    """Extract file paths from unified diff"""
    files = []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, flags=re.M):
        path = m.group(1).split("\t")[0].strip()
        files.append(path)
    return list(set(files))

def is_path_allowed(path: str) -> bool:
    """Check if path matches whitelist patterns"""
    return any(fnmatch.fnmatch(path, p) for p in get_whitelist_patterns())

def is_path_denied(path: str) -> bool:
    """Check if path matches denylist patterns"""
    return any(fnmatch.fnmatch(path, p) for p in get_denylist_patterns())

def is_path_safe(path: str) -> bool:
    """Reject absolute paths and path traversal (..). Enforce POSIX-ish cleanliness."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return False
    p = PurePosixPath(path)
    if str(p).startswith(("/", "\\")) or p.is_absolute():
        return False
    # Disallow parent-directory refs and empty segments
    return all(part not in ("..", "") for part in p.parts)

def validate_diff_files(diff_content: str) -> None:
    """Validate that diff only touches allowed files"""
    files = paths_from_unified_diff(diff_content)
    violations = []
    
    for p in files:
        if not is_path_safe(p):
            violations.append(f"{p} (unsafe path)")
        if not is_path_allowed(p):
            violations.append(f"{p} (not in whitelist)")
        if is_path_denied(p):
            violations.append(f"{p} (in denylist)")
    
    if violations:
        raise Exception(f"Diff contains unauthorized files: {violations}")
