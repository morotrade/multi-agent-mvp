# -*- coding: utf-8 -*-
"""
System information and environment validation
"""
import os
import sys
import subprocess
import shutil
from typing import Dict

def validate_environment() -> Dict[str, bool]:
    """Validate required environment setup"""
    checks = {
        "github_token": bool(os.environ.get("GITHUB_TOKEN")),
        "github_repo": bool(os.environ.get("GITHUB_REPOSITORY")),
        "git_available": bool(shutil.which("git")),
        "patch_available": bool(shutil.which("patch")),
        "llm_key_available": bool(
            os.environ.get("OPENAI_API_KEY") or 
            os.environ.get("ANTHROPIC_API_KEY") or 
            os.environ.get("GEMINI_API_KEY")
        ),
        "classic_token": bool(os.environ.get("GH_CLASSIC_TOKEN")),
    }
    
    return checks

def get_system_info() -> Dict[str, str]:
    """Get system information for debugging"""
    info = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "working_directory": os.getcwd(),
        "github_repository": os.environ.get("GITHUB_REPOSITORY", "not set"),
        "github_ref": os.environ.get("GITHUB_REF", "not set"),
        "github_event_name": os.environ.get("GITHUB_EVENT_NAME", "not set"),
    }
    
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            info["git_commit"] = result.stdout.strip()
    except Exception:
        info["git_commit"] = "unavailable"
    
    return info
