# -*- coding: utf-8 -*-
"""
Full File Refacing Strategy - Production Ready Implementation
Basato sullo schema di ContextBuilder → FileRewriter → Validator+Applier
"""
import json
import hashlib
import tempfile
import subprocess
import os
import shutil
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional
import re

# Import improvements for production
try:
    from utils.llm_providers import call_llm_api
except ImportError:
    try:
        from llm_providers import call_llm_api
    except ImportError:
        # Production should fail early with clear error
        raise ImportError(
            "LLM provider not found. Please ensure 'llm_providers' module is available "
            "or install required dependencies."
        )

def sha256_bytes(b: bytes) -> str:
    """Calculate SHA256 hash for content verification"""
    return "sha256:" + hashlib.sha256(b).hexdigest()

@dataclass
class RefaceContract:
    """Contract between LLM and validator"""
    file_path: str
    pre_hash: str  # Hash del file base che l'LLM ha visto
    new_content: str  # Contenuto completo nuovo
    changelog: List[str]  # Lista delle modifiche applicate
    confidence: float = 0.8  # Confidence score del modello

# KEEP blocks support
class KEEPBlockValidator:
    """Validates that KEEP blocks are preserved during refacing"""
    
    KEEP_OPEN_PATTERN = re.compile(r"# >>> KEEP:(?P<id>[A-Za-z0-9_\-]+)")
    KEEP_CLOSE_PATTERN = re.compile(r"# <<< KEEP:(?P<id>[A-Za-z0-9_\-]+)")
    
    @classmethod
    def extract_keep_blocks(cls, content: str) -> Dict[str, str]:
        """Extract KEEP blocks from content"""
        blocks = {}
        lines = content.split('\n')
        current_block_id = None
        current_block_lines = []
        
        for line in lines:
            open_match = cls.KEEP_OPEN_PATTERN.search(line)
            if open_match:
                current_block_id = open_match.group('id')
                current_block_lines = [line]
                continue
            
            if current_block_id:
                current_block_lines.append(line)
                close_match = cls.KEEP_CLOSE_PATTERN.search(line)
                if close_match and close_match.group('id') == current_block_id:
                    blocks[current_block_id] = '\n'.join(current_block_lines)
                    current_block_id = None
                    current_block_lines = []
        
        return blocks
    
    @classmethod
    def validate_keep_blocks_preserved(cls, original: str, new_content: str) -> None:
        """Validate that KEEP blocks are preserved"""
        original_blocks = cls.extract_keep_blocks(original)
        new_blocks = cls.extract_keep_blocks(new_content)
        
        for block_id, original_block in original_blocks.items():
            if block_id not in new_blocks:
                raise RuntimeError(f"KEEP_BLOCK_REMOVED: Block '{block_id}' was removed")
            if new_blocks[block_id] != original_block:
                raise RuntimeError(f"KEEP_BLOCK_MODIFIED: Block '{block_id}' was modified")

# Enhanced context builder with KEEP blocks support
class ContextBuilder:
    """Builds intelligent, structured context for LLM"""
    
    def __init__(self, max_reviews: int = 3, max_tokens: int = 8000, enable_keep_blocks: bool = True):
        self.max_reviews = max_reviews
        self.max_tokens = max_tokens
        self.enable_keep_blocks = enable_keep_blocks
    
    def build(self, file_path: str, requirements: str, reviews: List[str], 
              style_guide: str = "") -> str:
        """Build optimized context for full file rewrite"""
        
        # Load current file and calculate hash
        src_path = Path(file_path)
        src_content = src_path.read_text(encoding="utf-8")
        base_hash = sha256_bytes(src_content.encode("utf-8"))
        
        # Filter and consolidate reviews
        top_reviews = self._pick_top_reviews(reviews, self.max_reviews)
        consolidated_reviews = self._consolidate_reviews(top_reviews)
        
        # Build structured context
        # Build structured context
        keep_blocks_instruction = ""
        if self.enable_keep_blocks:
            keep_blocks = KEEPBlockValidator.extract_keep_blocks(src_content)
            if keep_blocks:
                keep_blocks_instruction = f"""
## KEEP BLOCKS (CRITICAL - DO NOT MODIFY)
The file contains {len(keep_blocks)} KEEP blocks that must be preserved EXACTLY:
{', '.join(keep_blocks.keys())}

NEVER modify content between # >>> KEEP:id and # <<< KEEP:id markers.
"""
        
        context = f"""# TASK: Complete File Rewrite

## FILE: {file_path}

## CURRENT STATE (AUTHORITATIVE)
```{self._get_language_tag(file_path)}
{src_content}
```

## BASE HASH (CRITICAL)
{base_hash}

## REQUIREMENTS (CRITICAL PRIORITY)
{requirements}

## CONSOLIDATED FEEDBACK (HIGH PRIORITY)
{consolidated_reviews}

## STYLE CONSTRAINTS (MEDIUM PRIORITY)
{style_guide or "Follow PEP 8 for Python, industry standards for other languages"}
{keep_blocks_instruction}
## OUTPUT CONTRACT (MANDATORY)
Return ONLY a JSON object with these exact keys:
{{
  "file_path": "{file_path}",
  "pre_hash": "{base_hash}",
  "new_content": "<COMPLETE FILE CONTENT>",
  "changelog": ["Change 1", "Change 2", ...],
  "confidence": 0.8
}}

## CRITICAL RULES
1. new_content MUST be the COMPLETE file (not diff, not partial)
2. pre_hash MUST equal "{base_hash}" (proves you saw the right base)
3. Preserve all existing functionality unless explicitly asked to change
4. Add comprehensive docstrings and type hints
5. Ensure syntactic correctness
6. Minimize unnecessary changes to reduce diff noise
7. NEVER modify KEEP blocks if present

## VALIDATION PIPELINE
Your output will be:
1. Hash-verified against base
2. Syntax checked with compiler
3. Auto-formatted with code formatter
4. KEEP blocks validated (if any)
5. Tested for basic functionality
6. Applied atomically

Generate the JSON response now:"""

        # Check token budget (simplified check)
        if self._estimate_tokens(context) > self.max_tokens:
            context = self._compress_context(context, file_path, consolidated_reviews)
        
        return context
    
    def _pick_top_reviews(self, reviews: List[str], limit: int) -> List[str]:
        """Select most relevant reviews by recency and specificity"""
        if not reviews:
            return []
        
        # Simple heuristic: take the most recent reviews
        # In production, add relevance scoring here
        scored_reviews = []
        for i, review in enumerate(reviews[-10:]):  # Last 10 reviews max
            # Score by recency (more recent = higher score)
            recency_score = (10 - i) / 10
            # Score by length/specificity (longer = more specific)
            specificity_score = min(len(review) / 500, 1.0)
            total_score = (recency_score * 0.7) + (specificity_score * 0.3)
            scored_reviews.append((review, total_score))
        
        # Sort by score and take top N
        scored_reviews.sort(key=lambda x: x[1], reverse=True)
        return [review for review, _ in scored_reviews[:limit]]
    
    def _consolidate_reviews(self, reviews: List[str]) -> str:
        """Consolidate multiple reviews into clear instructions"""
        if not reviews:
            return "No specific feedback to address."
        
        if len(reviews) == 1:
            return reviews[0]
        
        # Simple consolidation - in production, use semantic grouping
        consolidated = "Multiple feedback items to address:\n"
        for i, review in enumerate(reviews, 1):
            # Extract actionable items (simplified)
            actionable = self._extract_actionable_items(review)
            if actionable:
                consolidated += f"\n{i}. {actionable}"
        
        return consolidated
    
    def _extract_actionable_items(self, review: str) -> str:
        """Extract actionable items from review text"""
        # Simplified extraction for now - return truncated review
        # TODO: Implement pattern matching if needed
        return review[:200] + "..." if len(review) > 200 else review
    
    def _get_language_tag(self, file_path: str) -> str:
        """Get language tag for syntax highlighting"""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
            '.cpp': 'cpp',
            '.c': 'c'
        }
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, 'text')
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars ≈ 1 token)"""
        return len(text) // 4
    
    def _compress_context(self, context: str, file_path: str, reviews: str) -> str:
        """Compress context if too large"""
        # Simple compression - truncate reviews
        src_content = Path(file_path).read_text(encoding="utf-8")
        base_hash = sha256_bytes(src_content.encode("utf-8"))
        
        compressed_reviews = reviews[:1000] + "...(truncated)" if len(reviews) > 1000 else reviews
        
        return f"""# TASK: Complete File Rewrite
## FILE: {file_path}
## CURRENT STATE: 
```{self._get_language_tag(file_path)}
{src_content}
```
## BASE HASH: {base_hash}
## FEEDBACK: {compressed_reviews}
## OUTPUT: JSON with file_path, pre_hash="{base_hash}", new_content, changelog"""

    # --- KEEP blocks helpers (qui, perché usate da ValidatorApplier) ---
    def _freeze_keep_blocks(self, content: str):
        """Sostituisce i blocchi KEEP con placeholder univoci per evitare che il formatter li tocchi."""
        blocks = KEEPBlockValidator.extract_keep_blocks(content)
        if not blocks:
            return content, None
        frozen = content
        mapping = {}
        for i, (bid, block) in enumerate(blocks.items(), 1):
            token = f"__KEEP_BLOCK_{i}_{bid}__"
            frozen = frozen.replace(block, token)
            mapping[token] = block
        return frozen, mapping

    def _thaw_keep_blocks(self, content: str, mapping: Dict[str, str]) -> str:
        """Ripristina i blocchi KEEP originali dopo il formatting."""
        if not mapping:
            return content
        thawed = content
        for token, block in mapping.items():
            thawed = thawed.replace(token, block)
        return thawed

class FileRewriter:
    """LLM-based full file rewriter"""
    
    def __init__(self, model: str = "gpt-4o-mini", max_tokens: int = 8000):
        self.model = model
        self.max_tokens = max_tokens
    
    def generate(self, context: str) -> RefaceContract:
        """Generate complete file rewrite using LLM with robust JSON parsing"""
        
        # Enhanced prompt for JSON output
        json_prompt = f"""{context}

CRITICAL: Your response must be ONLY valid JSON. No explanations, no markdown, just JSON."""
        
        try:
            # Call LLM
            raw_response = call_llm_api(
                json_prompt, 
                model=self.model, 
                max_tokens=self.max_tokens
            )
            
            # Clean and parse JSON
            cleaned_response = self._clean_json_response(raw_response)
            contract_data = json.loads(cleaned_response)
            self._validate_contract_types(contract_data)
            
            # Validate contract structure
            required_keys = {'file_path', 'pre_hash', 'new_content', 'changelog'}
            if not all(key in contract_data for key in required_keys):
                raise ValueError(f"Missing required keys: {required_keys - set(contract_data.keys())}")
            
            return RefaceContract(**contract_data)
            
        except json.JSONDecodeError:
            # One retry with stricter instruction
            print("⚠️  JSON parse failed, retrying with stricter prompt...")
            try:
                raw_response = call_llm_api(
                    context + "\n\nReturn ONLY raw JSON object. No markdown, no explanations.",
                    model=self.model, 
                    max_tokens=self.max_tokens
                )
                cleaned_response = self._clean_json_response(raw_response)
                contract_data = json.loads(cleaned_response)
                self._validate_contract_types(contract_data)
                return RefaceContract(**contract_data)
            except json.JSONDecodeError as e:
                raise ValueError(f"LLM returned invalid JSON after retry: {e}")
                
        except Exception as e:
            raise RuntimeError(f"File rewrite generation failed: {e}")
    
    def _clean_json_response(self, raw_response: str) -> str:
        """Clean LLM response to extract valid JSON"""
        # Remove markdown code fences if present
        cleaned = raw_response.strip()
        
        # Remove ```json and ``` if present
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        if cleaned.startswith('```'):
            cleaned = cleaned[3:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        
        # Find JSON object boundaries
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        
        if start == -1 or end == 0:
            raise ValueError("No JSON object found in response")
        
        return cleaned[start:end].strip()
    
    
    @staticmethod
    def _validate_contract_types(d: dict) -> None:
        """Schema minimale per evitare sorprese di tipo."""
        required = {
            "file_path": str,
            "pre_hash": str,
            "new_content": str,
            "changelog": list,
        }
        missing = [k for k in required if k not in d]
        if missing:
            raise ValueError(f"Invalid contract: missing keys {missing}")
        for k, t in required.items():
            if not isinstance(d[k], t):
                raise ValueError(f"Invalid contract: '{k}' must be {t.__name__}")

class ValidatorApplier:
    """Validates and applies file rewrites with atomic operations"""
    
    def __init__(self, enable_auto_format: bool = True, min_confidence: float = 0.75, 
                 enable_keep_blocks: bool = True):
        self.enable_auto_format = enable_auto_format
        self.min_confidence = min_confidence
        self.enable_keep_blocks = enable_keep_blocks
    
    def check_and_apply(self, contract: RefaceContract, expected_path: Optional[Path] = None) -> bool:
        """Validate contract and apply changes atomically"""
        
        # 0. Confidence gate
        if contract.confidence < self.min_confidence:
            raise RuntimeError(
                f"LOW_CONFIDENCE: {contract.confidence:.2f} < {self.min_confidence:.2f}. "
                f"Manual review required."
            )
        
        # 0.a Path hijack protection
        file_path = Path(contract.file_path).resolve()
        if expected_path is not None and file_path != expected_path.resolve():
            raise RuntimeError(f"PATH_MISMATCH: contract file_path={file_path} != expected={expected_path}")
        
        # 0.b Repo root enforcement (hardening)
        try:
            repo_root = Path(subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], 
                capture_output=True, text=True, check=True
            ).stdout.strip())
            file_path.relative_to(repo_root)
        except (subprocess.CalledProcessError, ValueError):
            raise RuntimeError(f"UNSAFE_PATH: {file_path} not under repo or not a git repo")
        
        # 0.c Size gate (1MB limit for text files)
        if len(contract.new_content.encode('utf-8')) > 1_000_000:
            raise RuntimeError("OVERSIZE_OUTPUT: new_content exceeds 1MB limit")
        
        # 1. Pre-image verification
        if not self._verify_pre_hash(file_path, contract.pre_hash):
            raise RuntimeError(
                f"BASE_CHANGED: File {file_path} was modified since context was built. "
                f"Expected hash {contract.pre_hash}, but file has changed."
            )
        
        # Store original content for KEEP block validation
        original_content = file_path.read_text(encoding='utf-8')
        
        # 2. KEEP blocks validation (if enabled)
        if self.enable_keep_blocks:
            KEEPBlockValidator.validate_keep_blocks_preserved(original_content, contract.new_content)
        
        # 3. Syntax validation
        self._validate_syntax(file_path, contract.new_content)
        
        # 4. Auto-formatting (optional) — freeze KEEP blocks to avoid formatter changes inside them
        formatted_content = contract.new_content
        if self.enable_auto_format:
            frozen, map_back = self._freeze_keep_blocks(formatted_content) if self.enable_keep_blocks else (formatted_content, None)
            formatted = self._auto_format(file_path, frozen)
            formatted_content = self._thaw_keep_blocks(formatted, map_back) if map_back else formatted
 
        # 5. Atomic file replacement
        self._atomic_write(file_path, formatted_content)
        
        # 6. Smoke tests (if available)
        # 6. KEEP blocks validation (post-format) to ensure exact preservation
        if self.enable_keep_blocks:
            KEEPBlockValidator.validate_keep_blocks_preserved(original_content, formatted_content)

        # 7. Smoke tests (if available)
        self._run_smoke_tests(file_path)
        
        # 7. Git operations (only if changes exist)
        self._git_commit_if_changed(file_path, contract.changelog)
        
        return True
    
    def _verify_pre_hash(self, file_path: Path, expected_hash: str) -> bool:
        """Verify that file hasn't changed since context was built"""
        try:
            current_content = file_path.read_bytes()
            current_hash = sha256_bytes(current_content)
            return current_hash == expected_hash
        except FileNotFoundError:
            # File deletion should be handled explicitly, not through refacing
            return False
    
    def _validate_syntax(self, file_path: Path, content: str) -> None:
        """Validate syntax using language-specific tools"""
        
        ext = file_path.suffix.lower()
        
        # For Python, use AST parsing (safe, no execution)
        if ext == '.py':
            try:
                ast.parse(content, filename=str(file_path))
            except SyntaxError as e:
                raise SyntaxError(f"Python syntax error in {file_path}: {e}")
            return
        
        # Create temporary file for other language validation
        with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
        
        try:
            if ext == '.js':
                # Node.js syntax check
                if self._command_exists('node'):
                    result = subprocess.run([
                        'node', '--check', tmp_path
                    ], capture_output=True, text=True)
                    
                    if result.returncode != 0:
                        raise SyntaxError(f"JavaScript syntax error: {result.stderr}")
                        
                # Fallback to eslint
                elif self._command_exists('eslint'):
                    result = subprocess.run([
                        'eslint', '--stdin', '--stdin-filename', str(file_path)
                    ], input=content, text=True, capture_output=True)
                    
                    if result.returncode > 1:  # eslint returns 1 for linting errors, >1 for fatal
                        raise SyntaxError(f"JavaScript syntax error: {result.stdout}")
            
            elif ext == '.ts':
                # TypeScript check - prefer tsc if tsconfig exists
                if (file_path.parent / "tsconfig.json").exists() and self._command_exists('tsc'):
                    result = subprocess.run([
                        'tsc', '--noEmit', '--pretty', 'false', '--skipLibCheck', tmp_path
                    ], capture_output=True, text=True)
                    
                    if result.returncode != 0:
                        raise SyntaxError(f"TypeScript syntax error: {result.stderr}")
                        
                # Fallback to eslint
                elif self._command_exists('eslint'):
                    result = subprocess.run([
                        'eslint', '--stdin', '--stdin-filename', str(file_path)
                    ], input=content, text=True, capture_output=True)
                    
                    if result.returncode > 1:
                        raise SyntaxError(f"TypeScript syntax error: {result.stdout}")
            
            # Add more language validators as needed
            
        finally:
            os.unlink(tmp_path)
    
    def _auto_format(self, file_path: Path, content: str) -> str:
        """Auto-format code using language-specific formatters"""
        
        ext = file_path.suffix.lower()
        
        if ext == '.py':
            return self._format_python(content)
        elif ext in ['.js', '.ts']:
            return self._format_javascript(content, file_path)
        else:
            return content  # No formatter available
    
    def _format_python(self, content: str) -> str:
        """Format Python code using black and ruff"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, 
                                       encoding='utf-8', newline='\n') as tmp:
            tmp.write(content)
            tmp.flush()
            tmp_path = tmp.name
        
        try:
            # Apply ruff fixes
            if self._command_exists('ruff'):
                subprocess.run(['ruff', 'check', '--fix', tmp_path], 
                             capture_output=True, check=False)
            
            # Apply black formatting
            if self._command_exists('black'):
                subprocess.run(['black', tmp_path], 
                             capture_output=True, check=False)
            
            # Read formatted content
            with open(tmp_path, 'r', encoding='utf-8', newline='\n') as f:
                return f.read()
        
        finally:
            os.unlink(tmp_path)
        
        return content  # Return original if formatting fails
    
    def _format_javascript(self, content: str, file_path: Path) -> str:
        """Format JavaScript/TypeScript using prettier"""
        
        if not self._command_exists('prettier'):
            return content
        
        # Use correct file extension for prettier
        ext = file_path.suffix.lower()
        stdin_filename = f"temp{ext}"
        
        try:
            result = subprocess.run([
                'prettier', '--stdin-filepath', stdin_filename
            ], input=content, text=True, capture_output=True)
            
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        
        return content
    
    def _atomic_write(self, file_path: Path, content: str) -> None:
        """Write file atomically to prevent corruption and collisions"""
        
        # Use NamedTemporaryFile in same directory for true atomicity
        dirp = file_path.parent
        if not content.endswith("\n"):
            content = content + "\n"
        with tempfile.NamedTemporaryFile('w', delete=False, dir=dirp, encoding='utf-8', newline='\n') as tmp:
            
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())  # Force write to disk
            tmp_name = tmp.name
        
        # Atomic rename
        os.replace(tmp_name, file_path)
    
    def _run_smoke_tests(self, file_path: Path) -> None:
        """Run basic smoke tests if available"""
        
        # This is optional and should be safe (no side effects)
        ext = file_path.suffix.lower()
        
        if ext == '.py':
            # Use AST parsing instead of import (no execution)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    ast.parse(f.read(), filename=str(file_path))
                # If we reach here, syntax is valid
            except SyntaxError as e:
                print(f"Warning: Smoke test failed for {file_path}: {e}")
            except Exception as e:
                print(f"Warning: Smoke test error for {file_path}: {e}")
    
    def _git_commit_if_changed(self, file_path: Path, changelog: List[str]) -> None:
        """Commit changes to git only if there are actual changes"""
        
        try:
            # Add file to git
            subprocess.run(['git', 'add', str(file_path)], check=True)
            
            # Check if there are any changes staged
            no_changes = subprocess.run([
                'git', 'diff', '--cached', '--quiet', '--', str(file_path)
            ]).returncode == 0
            
            if no_changes:
                print(f"No changes detected in {file_path}, skipping commit")
                return
            
            # Create commit message
            changelog_summary = "; ".join(changelog[:3])  # First 3 items
            if len(changelog) > 3:
                changelog_summary += f" (and {len(changelog) - 3} more)"
            
            commit_message = f"reface: {file_path.name} - {changelog_summary}"
            
            # Commit
            subprocess.run(['git', 'commit', '-m', commit_message], check=True)
            print(f"Committed changes to {file_path}")
            
        except subprocess.CalledProcessError as e:
            print(f"Warning: Git commit failed: {e}")
            # Don't fail the entire operation for git issues
    
    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH (cross-platform)"""
        return shutil.which(command) is not None

# Main orchestrator class
class FullFileRefacer:
    """Main class that orchestrates the full refacing process"""
    
    def __init__(self, model: str = "gpt-4o-mini"):
        self.context_builder = ContextBuilder()
        self.rewriter = FileRewriter(model=model)
        self.validator = ValidatorApplier()
    
    def reface_file(self, file_path: str, requirements: str, 
                   review_history: List[str], style_guide: str = "") -> bool:
        """Execute full file refacing workflow with single retry on base change"""
        
        tried_retry = False
        
        while True:
            try:
                # 1. Build intelligent context
                print(f"🔨 Building context for {file_path}")
                context = self.context_builder.build(
                    file_path=file_path,
                    requirements=requirements,
                    reviews=review_history,
                    style_guide=style_guide
                )
                
                # 2. Generate complete file rewrite
                print(f"🤖 Generating rewrite with LLM")
                contract = self.rewriter.generate(context)
                
                print(f"📋 Generated rewrite with {len(contract.changelog)} changes")
                print(f"🎯 Confidence: {contract.confidence:.2f}")
                for change in contract.changelog:
                    print(f"  - {change}")
                
                # 3. Validate and apply
                print(f"✅ Validating and applying changes")
                success = self.validator.check_and_apply(contract, expected_path=Path(file_path))
                
                if success:
                    print(f"🎉 Successfully refaced {file_path}")
                    return True
                else:
                    print(f"❌ Failed to apply changes to {file_path}")
                    return False
                    
            except RuntimeError as e:
                error_msg = str(e)
                
                # Handle base file changed - single retry
                if "BASE_CHANGED" in error_msg and not tried_retry:
                    print(f"⚠️  Base file changed, retrying with fresh context...")
                    tried_retry = True
                    continue  # Rebuild context with new base and retry once
                
                # Handle low confidence - request human review
                elif "LOW_CONFIDENCE" in error_msg:
                    print(f"⚠️  {error_msg}")
                    print(f"📝 Manual review required for {file_path}")
                    return False
                
                # Other runtime errors
                else:
                    print(f"💥 Refacing failed for {file_path}: {e}")
                    return False
                    
            except Exception as e:
                print(f"💥 Unexpected error refacing {file_path}: {e}")
                return False

# Integration with existing system
def integrate_with_pr_fix_mode():
    """
    Example of how to integrate with existing PR fix mode
    Replace the fragile diff application with this robust approach
    """
    
    # Instead of:
    # diff = generate_diff(prompt)
    # apply_diff(diff)  # ← Fragile!
    
    # Use:
    refacer = FullFileRefacer(model="gpt-4o-mini")
    
    success = refacer.reface_file(
        file_path="projects/math_utils.py",
        requirements="Implement basic math utilities with validation",
        review_history=[
            "Add validation parameter to add() function",
            "Fix docstring formatting issues", 
            "Add proper type hints"
        ],
        style_guide="Follow PEP 8, use black formatting"
    )
    
    return success

# Feature flag integration
class EnhancedPRFixMode:
    """Enhanced PR fix mode with full refacing strategy"""
    
    def __init__(self, use_refacing: bool = None):
        # Check environment variable for strategy
        self.use_refacing = use_refacing or os.getenv("REFACE_STRATEGY") == "full"
        
        if self.use_refacing:
            self.refacer = FullFileRefacer()
            print("🔄 Using FULL REFACING strategy")
        else:
            print("📝 Using traditional diff strategy")
    
    def process_pr_fix(self, pr_number: int, file_path: str, 
                      requirements: str, review_history: List[str]) -> bool:
        """Process PR fix using selected strategy"""
        
        if self.use_refacing:
            return self.refacer.reface_file(
                file_path=file_path,
                requirements=requirements,
                review_history=review_history,
                style_guide="Follow project conventions"
            )
        else:
            # Fallback to traditional diff approach
            print("⚠️  Falling back to traditional diff approach")
            return False  # Implement your existing logic here