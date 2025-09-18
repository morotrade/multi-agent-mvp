"""
File validation and atomic application with multi-language support
"""
import ast
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .exceptions import (
    BaseChangedError, LowConfidenceError, PathMismatchError, 
    OversizeOutputError, UnsafePathError, SyntaxValidationError
)
from .keep_blocks import KEEPBlockValidator
from .utils import (
    sha256_bytes, command_exists, get_repo_root, is_path_under_repo,
    freeze_keep_blocks, thaw_keep_blocks, safe_git_operation, ensure_newline_ending
)

if TYPE_CHECKING:
    from .core import RefaceContract


class ValidatorApplier:
    """Validates and applies file rewrites with atomic operations"""
    
    def __init__(self, 
                 enable_auto_format: bool = True, 
                 min_confidence: float = 0.75,
                 enable_keep_blocks: bool = True,
                 max_file_size: int = 1_000_000):
        """
        Initialize validator and applier.
        
        Args:
            enable_auto_format: Whether to auto-format after generation
            min_confidence: Minimum confidence threshold
            enable_keep_blocks: Whether to validate KEEP blocks
            max_file_size: Maximum file size in bytes (1MB default)
        """
        self.enable_auto_format = enable_auto_format
        self.min_confidence = min_confidence
        self.enable_keep_blocks = enable_keep_blocks
        self.max_file_size = max_file_size
    
    def check_and_apply(self, contract: 'RefaceContract', expected_path: Optional[Path] = None) -> bool:
        """
        Validate contract and apply changes atomically.
        
        Args:
            contract: RefaceContract from LLM
            expected_path: Expected file path for security validation
            
        Returns:
            True if successful
            
        Raises:
            Various RefaceError subclasses for different failure modes
        """
        # 1. Confidence gate
        if contract.confidence < self.min_confidence:
            raise LowConfidenceError(contract.confidence, self.min_confidence)
        
        # 2. Path security validation
        file_path = Path(contract.file_path).resolve()
        self._validate_path_security(file_path, expected_path)
        
        # 3. Size gate
        content_size = len(contract.new_content.encode('utf-8'))
        if content_size > self.max_file_size:
            raise OversizeOutputError(content_size, self.max_file_size)
        
        # 4. Pre-image verification
        original_content = self._verify_and_get_original(file_path, contract.pre_hash)
        
        # 5. KEEP blocks validation (if enabled)
        if self.enable_keep_blocks:
            KEEPBlockValidator.validate_keep_blocks_preserved(
                original_content, contract.new_content
            )
        
        # 6. Syntax validation
        self._validate_syntax(file_path, contract.new_content)
        
        # 7. Auto-formatting (optional) with KEEP blocks protection
        formatted_content = self._apply_formatting(file_path, contract.new_content)
        
        # 8. Final KEEP blocks validation (post-format)
        if self.enable_keep_blocks:
            KEEPBlockValidator.validate_keep_blocks_preserved(
                original_content, formatted_content
            )
        
        # 9. Atomic file replacement
        self._atomic_write(file_path, formatted_content)
        
        # 10. Smoke tests
        self._run_smoke_tests(file_path)
        
        # 11. Git operations (if changes exist)
        self._git_commit_if_changed(file_path, contract.changelog)
        
        return True
    
    def _validate_path_security(self, file_path: Path, expected_path: Optional[Path]) -> None:
        """Validate path security constraints"""
        # Path hijack protection
        if expected_path is not None and file_path != expected_path.resolve():
            raise PathMismatchError(str(file_path), str(expected_path))
        
        # Repository boundary enforcement
        if not is_path_under_repo(file_path):
            raise UnsafePathError(str(file_path))
    
    def _verify_and_get_original(self, file_path: Path, expected_hash: str) -> str:
        """Verify file hasn't changed and return original content"""
        try:
            original_content = file_path.read_text(encoding='utf-8')
            current_hash = sha256_bytes(original_content.encode('utf-8'))
            
            if current_hash != expected_hash:
                raise BaseChangedError(str(file_path), expected_hash, current_hash)
            
            return original_content
            
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {file_path}")
    
    def _validate_syntax(self, file_path: Path, content: str) -> None:
        """Validate syntax using language-specific tools"""
        ext = file_path.suffix.lower()
        
        try:
            if ext == '.py':
                self._validate_python_syntax(file_path, content)
            elif ext in ['.js', '.jsx']:
                self._validate_javascript_syntax(file_path, content)
            elif ext in ['.ts', '.tsx']:
                self._validate_typescript_syntax(file_path, content)
            # Add more language validators as needed
            
        except SyntaxError as e:
            raise SyntaxValidationError(str(file_path), str(e))
        except Exception as e:
            raise SyntaxValidationError(str(file_path), f"Validation failed: {e}")
    
    def _validate_python_syntax(self, file_path: Path, content: str) -> None:
        """Validate Python syntax using AST parsing"""
        try:
            ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            raise SyntaxError(f"Python syntax error: {e}")
    
    def _validate_javascript_syntax(self, file_path: Path, content: str) -> None:
        """Validate JavaScript syntax"""
        # Create temporary file for validation
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
        
        try:
            # Try Node.js syntax check first
            if command_exists('node'):
                result = subprocess.run([
                    'node', '--check', tmp_path
                ], capture_output=True, text=True, timeout=30)
                
                if result.returncode != 0:
                    raise SyntaxError(f"JavaScript syntax error: {result.stderr}")
            
            # Fallback to ESLint if available
            elif command_exists('eslint'):
                result = subprocess.run([
                    'eslint', '--stdin', '--stdin-filename', str(file_path)
                ], input=content, text=True, capture_output=True, timeout=30)
                
                if result.returncode > 1:  # eslint returns 1 for linting errors, >1 for fatal
                    raise SyntaxError(f"JavaScript syntax error: {result.stdout}")
        
        finally:
            os.unlink(tmp_path)
    
    def _validate_typescript_syntax(self, file_path: Path, content: str) -> None:
        """Validate TypeScript syntax"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
        
        try:
            # Try TypeScript compiler if available and tsconfig exists
            if (file_path.parent / "tsconfig.json").exists() and command_exists('tsc'):
                result = subprocess.run([
                    'tsc', '--noEmit', '--pretty', 'false', '--skipLibCheck', tmp_path
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    raise SyntaxError(f"TypeScript syntax error: {result.stderr}")
            
            # Fallback to ESLint
            elif command_exists('eslint'):
                result = subprocess.run([
                    'eslint', '--stdin', '--stdin-filename', str(file_path)
                ], input=content, text=True, capture_output=True, timeout=30)
                
                if result.returncode > 1:
                    raise SyntaxError(f"TypeScript syntax error: {result.stdout}")
        
        finally:
            os.unlink(tmp_path)
    
    def _apply_formatting(self, file_path: Path, content: str) -> str:
        """Apply auto-formatting with KEEP blocks protection"""
        if not self.enable_auto_format:
            return content
        
        # Protect KEEP blocks during formatting
        if self.enable_keep_blocks:
            keep_blocks = KEEPBlockValidator.extract_keep_blocks(content)
            frozen_content, mapping = freeze_keep_blocks(content, keep_blocks)
        else:
            frozen_content, mapping = content, {}
        
        # Apply language-specific formatting
        ext = file_path.suffix.lower()
        
        try:
            if ext == '.py':
                formatted = self._format_python(frozen_content)
            elif ext in ['.js', '.jsx', '.ts', '.tsx']:
                formatted = self._format_javascript(frozen_content, file_path)
            else:
                formatted = frozen_content  # No formatter available
        except Exception as e:
            print(f"Warning: Formatting failed for {file_path}: {e}")
            formatted = frozen_content
        
        # Restore KEEP blocks
        if mapping:
            formatted = thaw_keep_blocks(formatted, mapping)
        
        return formatted
    
    def _format_python(self, content: str) -> str:
        """Format Python code using black and ruff"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
        
        try:
            # Apply ruff fixes first
            if command_exists('ruff'):
                subprocess.run(['ruff', 'check', '--fix', tmp_path], 
                             capture_output=True, check=False, timeout=30)
            
            # Apply black formatting
            if command_exists('black'):
                subprocess.run(['black', '--quiet', tmp_path], 
                             capture_output=True, check=False, timeout=30)
            
            # Read formatted content
            with open(tmp_path, 'r', encoding='utf-8') as f:
                return f.read()
        
        finally:
            os.unlink(tmp_path)
        
        return content
    
    def _format_javascript(self, content: str, file_path: Path) -> str:
        """Format JavaScript/TypeScript using prettier"""
        if not command_exists('prettier'):
            return content
        
        ext = file_path.suffix.lower()
        stdin_filename = f"temp{ext}"
        
        try:
            result = subprocess.run([
                'prettier', '--stdin-filepath', stdin_filename
            ], input=content, text=True, capture_output=True, timeout=30)
            
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        
        return content
    
    def _atomic_write(self, file_path: Path, content: str) -> None:
        """Write file atomically to prevent corruption"""
        # Ensure content ends with newline
        content = ensure_newline_ending(content)
        
        # Use NamedTemporaryFile in same directory for true atomicity
        dir_path = file_path.parent
        
        with tempfile.NamedTemporaryFile('w', delete=False, dir=dir_path, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())  # Force write to disk
            tmp_name = tmp.name
        
        # Atomic rename
        os.replace(tmp_name, file_path)
    
    def _run_smoke_tests(self, file_path: Path) -> None:
        """Run basic smoke tests if available"""
        ext = file_path.suffix.lower()
        
        try:
            if ext == '.py':
                # Use AST parsing for Python (safe, no execution)
                with open(file_path, 'r', encoding='utf-8') as f:
                    ast.parse(f.read(), filename=str(file_path))
        except Exception as e:
            print(f"Warning: Smoke test failed for {file_path}: {e}")
    
    def _git_commit_if_changed(self, file_path: Path, changelog: list) -> None:
        """Commit changes to git only if there are actual changes"""
        def commit_operation():
            # Add file to git
            subprocess.run(['git', 'add', str(file_path)], check=True, timeout=30)
            
            # Check if there are any changes staged
            no_changes = subprocess.run([
                'git', 'diff', '--cached', '--quiet', '--', str(file_path)
            ], timeout=30).returncode == 0
            
            if no_changes:
                print(f"No changes detected in {file_path}, skipping commit")
                return
            
            # Create commit message
            changelog_summary = "; ".join(changelog[:3])  # First 3 items
            if len(changelog) > 3:
                changelog_summary += f" (and {len(changelog) - 3} more)"
            
            commit_message = f"reface: {file_path.name} - {changelog_summary}"
            
            # Commit
            subprocess.run(['git', 'commit', '-m', commit_message], check=True, timeout=30)
            print(f"Committed changes to {file_path}")
        
        if not safe_git_operation(commit_operation):
            print(f"Warning: Git commit failed for {file_path}")