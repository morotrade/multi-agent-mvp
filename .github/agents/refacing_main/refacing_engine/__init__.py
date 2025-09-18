"""
Full File Refacing Engine - Production Ready Module

A robust system for complete file rewriting using LLMs with validation,
atomic operations, and KEEP blocks support.

Key Features:
- Intelligent context building with review consolidation
- Hash-based file integrity verification
- KEEP blocks preservation for critical code sections
- Atomic file operations with rollback capability
- Multi-language syntax validation and auto-formatting
- Git integration with smart commit handling
"""

from .core import FullFileRefacer, RefaceContract
from .context import ContextBuilder
from .rewriter import FileRewriter
from .validator import ValidatorApplier
from .keep_blocks import KEEPBlockValidator
from .integration import EnhancedPRFixMode
from .exceptions import (
    RefaceError,
    BaseChangedError,
    LowConfidenceError,
    PathMismatchError,
    OversizeOutputError,
    KeepBlockError,
    SyntaxValidationError
)

__version__ = "1.0.0"

__all__ = [
    # Core classes
    'FullFileRefacer',
    'RefaceContract',
    'ContextBuilder',
    'FileRewriter', 
    'ValidatorApplier',
    'KEEPBlockValidator',
    'EnhancedPRFixMode',
    
    # Exceptions
    'RefaceError',
    'BaseChangedError',
    'LowConfidenceError',
    'PathMismatchError',
    'OversizeOutputError',
    'KeepBlockError',
    'SyntaxValidationError',
]