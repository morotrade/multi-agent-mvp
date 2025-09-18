"""
Core classes and data structures for the refacing engine
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .context import ContextBuilder
from .rewriter import FileRewriter
from .validator import ValidatorApplier
from .exceptions import BaseChangedError, RefaceError


@dataclass
class RefaceContract:
    """Contract between LLM and validator for file refacing"""
    file_path: str
    pre_hash: str  # Hash of the file base that LLM saw
    new_content: str  # Complete new file content
    changelog: List[str]  # List of changes applied
    confidence: float = 0.8  # LLM confidence score (0.0-1.0)
    
    def __post_init__(self):
        """Validate contract after initialization"""
        if not isinstance(self.file_path, str) or not self.file_path:
            raise ValueError("file_path must be a non-empty string")
        
        if not isinstance(self.pre_hash, str) or not self.pre_hash:
            raise ValueError("pre_hash must be a non-empty string")
        
        if not isinstance(self.new_content, str):
            raise ValueError("new_content must be a string")
        
        if not isinstance(self.changelog, list):
            raise ValueError("changelog must be a list")
        
        if not isinstance(self.confidence, (int, float)) or not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be a number between 0.0 and 1.0")


class FullFileRefacer:
    """Main orchestrator class for the full file refacing process"""
    
    def __init__(self, 
                 model: str = "gpt-4o-mini",
                 max_context_tokens: int = 8000,
                 min_confidence: float = 0.75,
                 enable_auto_format: bool = True,
                 enable_keep_blocks: bool = True,
                 max_retries: int = 1):
        """
        Initialize the refacing engine.
        
        Args:
            model: LLM model to use for generation
            max_context_tokens: Maximum tokens for context building
            min_confidence: Minimum confidence threshold for application
            enable_auto_format: Whether to auto-format generated content
            enable_keep_blocks: Whether to validate KEEP blocks preservation
            max_retries: Maximum retries on base file changes
        """
        self.model = model
        self.max_retries = max_retries
        
        # Initialize components
        self.context_builder = ContextBuilder(
            max_tokens=max_context_tokens,
            enable_keep_blocks=enable_keep_blocks
        )
        
        self.rewriter = FileRewriter(model=model)
        
        self.validator = ValidatorApplier(
            min_confidence=min_confidence,
            enable_auto_format=enable_auto_format,
            enable_keep_blocks=enable_keep_blocks
        )
    
    def reface_file(self, 
                   file_path: str, 
                   requirements: str, 
                   review_history: List[str] = None,
                   style_guide: str = "") -> bool:
        """
        Execute full file refacing workflow with retry on base changes.
        
        Args:
            file_path: Path to file to be refaced
            requirements: Core requirements/changes needed
            review_history: List of review comments/feedback
            style_guide: Style and formatting guidelines
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            RefaceError: For various failure modes
        """
        review_history = review_history or []
        retries_attempted = 0
        
        while retries_attempted <= self.max_retries:
            try:
                return self._execute_reface_cycle(
                    file_path=file_path,
                    requirements=requirements,
                    review_history=review_history,
                    style_guide=style_guide
                )
                
            except BaseChangedError as e:
                if retries_attempted < self.max_retries:
                    retries_attempted += 1
                    print(f"⚠️ Base file changed, retrying ({retries_attempted}/{self.max_retries})...")
                    continue
                else:
                    print(f"❌ Base file changed too many times, giving up after {self.max_retries} retries")
                    raise e
                    
            except RefaceError:
                # Other RefaceErrors should not be retried
                raise
                
            except Exception as e:
                print(f"💥 Unexpected error in refacing: {e}")
                raise RefaceError(f"Unexpected error: {e}") from e
    
    def _execute_reface_cycle(self, 
                             file_path: str, 
                             requirements: str, 
                             review_history: List[str],
                             style_guide: str) -> bool:
        """Execute a single refacing cycle"""
        
        # 1. Build intelligent context
        print(f"🔨 Building context for {file_path}")
        context = self.context_builder.build(
            file_path=file_path,
            requirements=requirements,
            reviews=review_history,
            style_guide=style_guide
        )
        
        # Log context size for monitoring
        from .utils import estimate_tokens
        token_count = estimate_tokens(context)
        print(f"📊 Context size: ~{token_count} tokens")
        
        # 2. Generate complete file rewrite
        print(f"🤖 Generating rewrite with {self.model}")
        contract = self.rewriter.generate(context)
        
        print(f"📋 Generated rewrite with {len(contract.changelog)} changes")
        print(f"🎯 Confidence: {contract.confidence:.2f}")
        for i, change in enumerate(contract.changelog[:5], 1):  # Show first 5 changes
            print(f"  {i}. {change}")
        if len(contract.changelog) > 5:
            print(f"  ... and {len(contract.changelog) - 5} more changes")
        
        # 3. Validate and apply
        print(f"✅ Validating and applying changes")
        success = self.validator.check_and_apply(contract, expected_path=Path(file_path))
        
        if success:
            print(f"🎉 Successfully refaced {file_path}")
            return True
        else:
            print(f"❌ Failed to apply changes to {file_path}")
            return False
    
    def estimate_cost(self, 
                     file_path: str, 
                     requirements: str, 
                     review_history: List[str] = None,
                     style_guide: str = "") -> dict:
        """
        Estimate the cost of refacing without actually executing it.
        
        Returns:
            Dictionary with cost estimation details
        """
        review_history = review_history or []
        
        try:
            # Build context (this is relatively cheap)
            context = self.context_builder.build(
                file_path=file_path,
                requirements=requirements,
                reviews=review_history,
                style_guide=style_guide
            )
            
            # Get cost estimation from rewriter
            cost_estimate = self.rewriter.estimate_generation_cost(context)
            
            # Add metadata
            cost_estimate.update({
                'file_path': file_path,
                'review_count': len(review_history),
                'requirements_length': len(requirements),
                'style_guide_length': len(style_guide)
            })
            
            return cost_estimate
            
        except Exception as e:
            return {
                'error': str(e),
                'file_path': file_path,
                'estimation_failed': True
            }
    
    def dry_run(self, 
               file_path: str, 
               requirements: str, 
               review_history: List[str] = None,
               style_guide: str = "") -> dict:
        """
        Perform a dry run to see what would be changed without applying.
        
        Returns:
            Dictionary with dry run results
        """
        review_history = review_history or []
        
        try:
            # Build context
            context = self.context_builder.build(
                file_path=file_path,
                requirements=requirements,
                reviews=review_history,
                style_guide=style_guide
            )
            
            # Generate contract
            contract = self.rewriter.generate(context)
            
            # Return analysis without applying
            return {
                'success': True,
                'file_path': contract.file_path,
                'confidence': contract.confidence,
                'changelog': contract.changelog,
                'content_length': len(contract.new_content),
                'content_lines': len(contract.new_content.split('\n')),
                'meets_confidence_threshold': contract.confidence >= self.validator.min_confidence
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'file_path': file_path
            }