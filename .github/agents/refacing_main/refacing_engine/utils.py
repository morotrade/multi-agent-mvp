"""
Utility functions for the refacing engine
"""
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Dict


def sha256_bytes(data: bytes) -> str:
    """Calculate SHA256 hash for content verification"""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def command_exists(command: str) -> bool:
    """Check if a command exists in PATH (cross-platform)"""
    return shutil.which(command) is not None


def get_language_tag(file_path: str) -> str:
    """Get language tag for syntax highlighting"""
    ext_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.go': 'go',
        '.rs': 'rust',
        '.cpp': 'cpp',
        '.c': 'c',
        '.php': 'php',
        '.rb': 'ruby',
        '.sh': 'bash',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.json': 'json',
        '.xml': 'xml',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.md': 'markdown'
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext, 'text')


def estimate_tokens(text: str) -> int:
    """Rough token estimation (4 chars ≈ 1 token)"""
    return len(text) // 4


def get_repo_root() -> Path:
    """Get git repository root directory"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], 
            capture_output=True, text=True, check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        raise RuntimeError("Not in a git repository or git not available")


def is_path_under_repo(file_path: Path, repo_root: Path = None) -> bool:
    """Check if file path is under repository root"""
    if repo_root is None:
        try:
            repo_root = get_repo_root()
        except RuntimeError:
            return False
    
    try:
        file_path.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def freeze_keep_blocks(content: str, blocks: Dict[str, str]) -> tuple[str, Dict[str, str]]:
    """
    Replace KEEP blocks with unique placeholders to avoid formatter changes.
    
    Returns:
        Tuple of (frozen_content, token_mapping)
    """
    if not blocks:
        return content, {}
    
    frozen = content
    mapping = {}
    
    for i, (block_id, block_content) in enumerate(blocks.items(), 1):
        token = f"__KEEP_BLOCK_{i}_{block_id}__"
        frozen = frozen.replace(block_content, token)
        mapping[token] = block_content
    
    return frozen, mapping


def thaw_keep_blocks(content: str, mapping: Dict[str, str]) -> str:
    """Restore original KEEP blocks after formatting"""
    if not mapping:
        return content
    
    thawed = content
    for token, block_content in mapping.items():
        thawed = thawed.replace(token, block_content)
    
    return thawed


def safe_git_operation(operation: callable, *args, **kwargs) -> bool:
    """
    Safely execute git operations with error handling.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        operation(*args, **kwargs)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Warning: Git operation failed: {e}")
        return False
    except Exception as e:
        print(f"Warning: Unexpected error in git operation: {e}")
        return False


def clean_json_response(raw_response: str) -> str:
    """Clean LLM response to extract valid JSON"""
    cleaned = raw_response.strip()
    
    # Remove markdown code fences if present
    if cleaned.startswith('```json'):
        cleaned = cleaned[7:]
    elif cleaned.startswith('```'):
        cleaned = cleaned[3:]
    
    if cleaned.endswith('```'):
        cleaned = cleaned[:-3]
    
    # Find JSON object boundaries
    start = cleaned.find('{')
    end = cleaned.rfind('}') + 1
    
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in response")
    
    return cleaned[start:end].strip()


def ensure_newline_ending(content: str) -> str:
    """Ensure content ends with a single newline"""
    content = content.rstrip('\n\r')
    return content + '\n'