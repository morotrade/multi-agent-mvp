"""
Integration layer for existing systems and feature flags
"""
import os
from typing import List, Optional, Dict, Any

from .core import FullFileRefacer
from .exceptions import RefaceError


class EnhancedPRFixMode:
    """Enhanced PR fix mode with full refacing strategy option"""
    
    def __init__(self, 
                 use_refacing: Optional[bool] = None,
                 model: str = "gpt-4o-mini",
                 **reface_kwargs):
        """
        Initialize enhanced PR fix mode.
        
        Args:
            use_refacing: Whether to use refacing strategy (None = auto-detect from env)
            model: LLM model for refacing
            **reface_kwargs: Additional arguments for FullFileRefacer
        """
        # Check environment variable for strategy selection
        if use_refacing is None:
            use_refacing = os.getenv("REFACE_STRATEGY", "").lower() in ("full", "true", "1")
        
        self.use_refacing = use_refacing
        self.model = model
        
        if self.use_refacing:
            self.refacer = FullFileRefacer(model=model, **reface_kwargs)
            print("🔄 Using FULL REFACING strategy")
        else:
            print("📝 Using traditional diff strategy")
    
    def process_pr_fix(self, 
                      pr_number: int, 
                      file_path: str, 
                      requirements: str, 
                      review_history: List[str],
                      style_guide: str = "") -> Dict[str, Any]:
        """
        Process PR fix using selected strategy.
        
        Args:
            pr_number: Pull request number
            file_path: Path to file being fixed
            requirements: Fix requirements
            review_history: List of review comments
            style_guide: Style guidelines
            
        Returns:
            Dictionary with processing results
        """
        if self.use_refacing:
            return self._process_with_refacing(
                pr_number, file_path, requirements, review_history, style_guide
            )
        else:
            return self._process_with_diff(
                pr_number, file_path, requirements, review_history, style_guide
            )
    
    def _process_with_refacing(self, 
                              pr_number: int, 
                              file_path: str, 
                              requirements: str, 
                              review_history: List[str],
                              style_guide: str) -> Dict[str, Any]:
        """Process using full refacing strategy"""
        try:
            success = self.refacer.reface_file(
                file_path=file_path,
                requirements=requirements,
                review_history=review_history,
                style_guide=style_guide
            )
            
            return {
                'success': success,
                'strategy': 'refacing',
                'pr_number': pr_number,
                'file_path': file_path,
                'message': 'File successfully refaced' if success else 'Refacing failed'
            }
            
        except RefaceError as e:
            return {
                'success': False,
                'strategy': 'refacing',
                'pr_number': pr_number,
                'file_path': file_path,
                'error': str(e),
                'error_type': type(e).__name__
            }
        except Exception as e:
            return {
                'success': False,
                'strategy': 'refacing',
                'pr_number': pr_number,
                'file_path': file_path,
                'error': f'Unexpected error: {e}',
                'error_type': 'UnexpectedError'
            }
    
    def _process_with_diff(self, 
                          pr_number: int, 
                          file_path: str, 
                          requirements: str, 
                          review_history: List[str],
                          style_guide: str) -> Dict[str, Any]:
        """Process using traditional diff strategy (fallback)"""
        print("⚠️ Traditional diff strategy not implemented in this module")
        print("    This would integrate with your existing diff-based implementation")
        
        return {
            'success': False,
            'strategy': 'diff',
            'pr_number': pr_number,
            'file_path': file_path,
            'message': 'Traditional diff strategy not implemented',
            'requires_integration': True
        }
    
    def should_use_refacing_for_file(self, file_path: str) -> bool:
        """
        Determine if refacing should be used for a specific file.
        
        Returns:
            True if refacing is recommended for this file
        """
        if not self.use_refacing:
            return False
        
        # File-specific heuristics
        from pathlib import Path
        path = Path(file_path)
        
        # Size-based decision
        try:
            if path.exists():
                file_size = path.stat().st_size
                # Use refacing for medium-sized files (better than diff for substantial changes)
                if file_size > 10000:  # 10KB+
                    return True
                # Skip refacing for very large files
                if file_size > 100000:  # 100KB+
                    return False
        except Exception:
            pass
        
        # Extension-based decision
        refacing_friendly_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go'}
        if path.suffix.lower() in refacing_friendly_extensions:
            return True
        
        return False
    
    def get_strategy_recommendation(self, 
                                  file_path: str, 
                                  requirements: str, 
                                  review_history: List[str]) -> Dict[str, Any]:
        """
        Get strategy recommendation with reasoning.
        
        Returns:
            Dictionary with recommendation and reasoning
        """
        # Analyze characteristics
        characteristics = {
            'file_exists': os.path.exists(file_path),
            'file_size': 0,
            'review_count': len(review_history),
            'requirements_complexity': len(requirements),
            'file_extension': Path(file_path).suffix.lower()
        }
        
        try:
            if characteristics['file_exists']:
                characteristics['file_size'] = os.path.getsize(file_path)
        except Exception:
            pass
        
        # Decision logic
        score = 0
        reasons = []
        
        # Size factor
        if characteristics['file_size'] > 5000:
            score += 2
            reasons.append("Large file benefits from complete rewrite")
        elif characteristics['file_size'] > 1000:
            score += 1
            reasons.append("Medium file suitable for refacing")
        
        # Review complexity factor
        if characteristics['review_count'] > 3:
            score += 2
            reasons.append("Multiple reviews suggest complex changes")
        elif characteristics['review_count'] > 1:
            score += 1
            reasons.append("Multiple reviews present")
        
        # Requirements complexity factor
        if characteristics['requirements_complexity'] > 500:
            score += 1
            reasons.append("Complex requirements")
        
        # Language support factor
        supported_extensions = {'.py', '.js', '.ts', '.jsx', '.tsx'}
        if characteristics['file_extension'] in supported_extensions:
            score += 1
            reasons.append(f"Good language support for {characteristics['file_extension']}")
        
        # Make recommendation
        recommend_refacing = score >= 3 and self.use_refacing
        
        return {
            'recommend_refacing': recommend_refacing,
            'confidence_score': min(score / 6, 1.0),  # Normalize to 0-1
            'reasons': reasons,
            'characteristics': characteristics,
            'current_strategy': 'refacing' if self.use_refacing else 'diff'
        }


class RefacingFeatureFlags:
    """Feature flag management for refacing functionality"""
    
    @staticmethod
    def is_enabled() -> bool:
        """Check if refacing is globally enabled"""
        return os.getenv("REFACE_STRATEGY", "").lower() in ("full", "true", "1")
    
    @staticmethod
    def get_model() -> str:
        """Get configured model for refacing"""
        return os.getenv("REFACE_MODEL", "gpt-4o-mini")
    
    @staticmethod
    def get_confidence_threshold() -> float:
        """Get confidence threshold from environment"""
        try:
            return float(os.getenv("REFACE_MIN_CONFIDENCE", "0.75"))
        except (ValueError, TypeError):
            return 0.75
    
    @staticmethod
    def is_auto_format_enabled() -> bool:
        """Check if auto-formatting is enabled"""
        return os.getenv("REFACE_AUTO_FORMAT", "true").lower() in ("true", "1", "yes")
    
    @staticmethod
    def is_keep_blocks_enabled() -> bool:
        """Check if KEEP blocks validation is enabled"""
        return os.getenv("REFACE_KEEP_BLOCKS", "true").lower() in ("true", "1", "yes")
    
    @staticmethod
    def get_max_file_size() -> int:
        """Get maximum file size for refacing"""
        try:
            return int(os.getenv("REFACE_MAX_FILE_SIZE", "1000000"))  # 1MB default
        except (ValueError, TypeError):
            return 1000000
    
    @staticmethod
    def get_configuration() -> Dict[str, Any]:
        """Get complete configuration dictionary"""
        return {
            'enabled': RefacingFeatureFlags.is_enabled(),
            'model': RefacingFeatureFlags.get_model(),
            'min_confidence': RefacingFeatureFlags.get_confidence_threshold(),
            'auto_format': RefacingFeatureFlags.is_auto_format_enabled(),
            'keep_blocks': RefacingFeatureFlags.is_keep_blocks_enabled(),
            'max_file_size': RefacingFeatureFlags.get_max_file_size()
        }


def integrate_with_existing_system():
    """
    Example integration function showing how to replace existing diff logic
    with refacing strategy.
    
    This function demonstrates the integration pattern but should be adapted
    to your specific system architecture.
    """
    
    # Example: Replace fragile diff application
    def enhanced_pr_fix_flow(pr_number: int, file_paths: List[str], 
                            reviewer_findings: str, **kwargs):
        """Enhanced PR fix flow with refacing support"""
        
        # Initialize enhanced mode
        enhanced_mode = EnhancedPRFixMode()
        
        results = []
        
        for file_path in file_paths:
            # Get strategy recommendation
            recommendation = enhanced_mode.get_strategy_recommendation(
                file_path=file_path,
                requirements=reviewer_findings,
                review_history=kwargs.get('review_history', [])
            )
            
            print(f"📊 Strategy for {file_path}: "
                  f"{'refacing' if recommendation['recommend_refacing'] else 'diff'} "
                  f"(confidence: {recommendation['confidence_score']:.2f})")
            
            # Process with recommended strategy
            result = enhanced_mode.process_pr_fix(
                pr_number=pr_number,
                file_path=file_path,
                requirements=reviewer_findings,
                review_history=kwargs.get('review_history', []),
                style_guide=kwargs.get('style_guide', '')
            )
            
            results.append(result)
        
        return results
    
    return enhanced_pr_fix_flow


# Backward compatibility helpers
def migrate_from_diff_approach():
    """
    Helper function to migrate from diff-based approach to refacing.
    
    Provides guidance and utilities for migration.
    """
    migration_guide = {
        'environment_variables': {
            'REFACE_STRATEGY': 'Set to "full" to enable refacing',
            'REFACE_MODEL': 'LLM model to use (default: gpt-4o-mini)',
            'REFACE_MIN_CONFIDENCE': 'Minimum confidence threshold (default: 0.75)',
            'REFACE_AUTO_FORMAT': 'Enable auto-formatting (default: true)',
            'REFACE_KEEP_BLOCKS': 'Enable KEEP blocks validation (default: true)'
        },
        
        'code_changes': {
            'replace_diff_generation': 'Use FullFileRefacer.reface_file() instead of diff generation',
            'remove_diff_application': 'Atomic file operations handled internally',
            'update_error_handling': 'Catch RefaceError subclasses for specific failure modes',
            'add_confidence_handling': 'Handle LowConfidenceError for manual review cases'
        },
        
        'benefits': [
            'Eliminates diff application failures',
            'Better handling of complex changes',
            'Automatic syntax validation',
            'Built-in formatting',
            'KEEP blocks preservation',
            'Atomic operations with rollback'
        ],
        
        'gradual_migration': {
            'phase_1': 'Enable for specific file types (.py files)',
            'phase_2': 'Expand to JavaScript/TypeScript files',
            'phase_3': 'Full rollout with fallback to diff',
            'phase_4': 'Remove diff-based approach'
        }
    }
    
    return migration_guide