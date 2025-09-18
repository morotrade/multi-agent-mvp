"""
Configuration management for the refacing engine
"""
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class RefacingConfig:
    """Configuration class for refacing engine"""
    
    # Core settings
    enabled: bool = False
    model: str = "gpt-4o-mini"
    min_confidence: float = 0.75
    max_retries: int = 1
    max_file_size: int = 1_000_000  # 1MB
    
    # Feature flags
    auto_format: bool = True
    keep_blocks: bool = True
    syntax_validation: bool = True
    git_commit: bool = True
    
    # Context building
    max_context_tokens: int = 8000
    max_reviews: int = 3
    
    # Supported file extensions
    supported_extensions: List[str] = field(default_factory=lambda: [
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.go', '.rs', '.php', '.rb'
    ])
    
    # Formatter configurations
    formatters: Dict[str, Dict] = field(default_factory=lambda: {
        'python': {
            'tools': ['ruff', 'black'],
            'timeout': 30
        },
        'javascript': {
            'tools': ['prettier'],
            'timeout': 30
        },
        'typescript': {
            'tools': ['prettier', 'tsc'],
            'timeout': 60
        }
    })
    
    # Validator configurations
    validators: Dict[str, Dict] = field(default_factory=lambda: {
        'python': {
            'tools': ['ast'],
            'timeout': 10
        },
        'javascript': {
            'tools': ['node', 'eslint'],
            'timeout': 30
        },
        'typescript': {
            'tools': ['tsc', 'eslint'],
            'timeout': 60
        }
    })
    
    @classmethod
    def from_environment(cls) -> 'RefacingConfig':
        """Create configuration from environment variables"""
        return cls(
            enabled=_env_bool('REFACE_ENABLED', 'REFACE_STRATEGY'),
            model=_env_str('REFACE_MODEL', 'gpt-4o-mini'),
            min_confidence=_env_float('REFACE_MIN_CONFIDENCE', 0.75),
            max_retries=_env_int('REFACE_MAX_RETRIES', 1),
            max_file_size=_env_int('REFACE_MAX_FILE_SIZE', 1_000_000),
            
            auto_format=_env_bool('REFACE_AUTO_FORMAT', default=True),
            keep_blocks=_env_bool('REFACE_KEEP_BLOCKS', default=True),
            syntax_validation=_env_bool('REFACE_SYNTAX_VALIDATION', default=True),
            git_commit=_env_bool('REFACE_GIT_COMMIT', default=True),
            
            max_context_tokens=_env_int('REFACE_MAX_CONTEXT_TOKENS', 8000),
            max_reviews=_env_int('REFACE_MAX_REVIEWS', 3),
        )
    
    def is_file_supported(self, file_path: str) -> bool:
        """Check if file extension is supported"""
        from pathlib import Path
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions
    
    def get_formatter_config(self, language: str) -> Dict:
        """Get formatter configuration for language"""
        return self.formatters.get(language.lower(), {})
    
    def get_validator_config(self, language: str) -> Dict:
        """Get validator configuration for language"""
        return self.validators.get(language.lower(), {})
    
    def to_dict(self) -> Dict:
        """Convert configuration to dictionary"""
        from dataclasses import asdict
        return asdict(self)
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of issues"""
        issues = []
        
        if not isinstance(self.min_confidence, (int, float)) or not (0.0 <= self.min_confidence <= 1.0):
            issues.append("min_confidence must be between 0.0 and 1.0")
        
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            issues.append("max_retries must be a non-negative integer")
        
        if not isinstance(self.max_file_size, int) or self.max_file_size <= 0:
            issues.append("max_file_size must be a positive integer")
        
        if not isinstance(self.max_context_tokens, int) or self.max_context_tokens <= 0:
            issues.append("max_context_tokens must be a positive integer")
        
        if not isinstance(self.max_reviews, int) or self.max_reviews < 0:
            issues.append("max_reviews must be a non-negative integer")
        
        if not self.model or not isinstance(self.model, str):
            issues.append("model must be a non-empty string")
        
        return issues


def _env_bool(key: str, fallback_key: str = None, default: bool = False) -> bool:
    """Get boolean from environment with fallback"""
    value = os.getenv(key)
    if value is None and fallback_key:
        value = os.getenv(fallback_key)
    
    if value is None:
        return default
    
    return str(value).lower() in ('true', '1', 'yes', 'on', 'full')


def _env_str(key: str, default: str = '') -> str:
    """Get string from environment"""
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    """Get integer from environment"""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float = 0.0) -> float:
    """Get float from environment"""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# Global configuration instance
_global_config: Optional[RefacingConfig] = None


def get_config() -> RefacingConfig:
    """Get global configuration instance"""
    global _global_config
    if _global_config is None:
        _global_config = RefacingConfig.from_environment()
    return _global_config


def set_config(config: RefacingConfig) -> None:
    """Set global configuration instance"""
    global _global_config
    _global_config = config


def reset_config() -> None:
    """Reset global configuration to environment defaults"""
    global _global_config
    _global_config = None


# Configuration presets for common scenarios
DEVELOPMENT_CONFIG = RefacingConfig(
    enabled=True,
    model="gpt-4o-mini",
    min_confidence=0.7,  # Lower threshold for development
    max_retries=2,
    auto_format=True,
    keep_blocks=True,
    git_commit=True
)

PRODUCTION_CONFIG = RefacingConfig(
    enabled=True,
    model="gpt-4o",  # More capable model for production
    min_confidence=0.8,  # Higher threshold for production
    max_retries=1,
    auto_format=True,
    keep_blocks=True,
    git_commit=True
)

CONSERVATIVE_CONFIG = RefacingConfig(
    enabled=True,
    model="gpt-4o-mini",
    min_confidence=0.9,  # Very high threshold
    max_retries=0,  # No retries
    auto_format=False,  # Manual formatting
    keep_blocks=True,
    git_commit=False  # Manual commits
)

EXPERIMENTAL_CONFIG = RefacingConfig(
    enabled=True,
    model="gpt-4o",
    min_confidence=0.6,  # Lower threshold for experimentation
    max_retries=3,
    auto_format=True,
    keep_blocks=True,
    git_commit=True,
    max_context_tokens=12000,  # Larger context
    max_reviews=5
)


def apply_preset(preset_name: str) -> None:
    """Apply a configuration preset"""
    presets = {
        'development': DEVELOPMENT_CONFIG,
        'production': PRODUCTION_CONFIG,
        'conservative': CONSERVATIVE_CONFIG,
        'experimental': EXPERIMENTAL_CONFIG
    }
    
    if preset_name.lower() not in presets:
        raise ValueError(f"Unknown preset: {preset_name}. Available: {list(presets.keys())}")
    
    set_config(presets[preset_name.lower()])


def print_current_config() -> None:
    """Print current configuration for debugging"""
    config = get_config()
    print("🔧 Current Refacing Configuration:")
    print(f"  Enabled: {config.enabled}")
    print(f"  Model: {config.model}")
    print(f"  Min Confidence: {config.min_confidence}")
    print(f"  Max Retries: {config.max_retries}")
    print(f"  Auto Format: {config.auto_format}")
    print(f"  KEEP Blocks: {config.keep_blocks}")
    print(f"  Max File Size: {config.max_file_size:,} bytes")
    print(f"  Supported Extensions: {config.supported_extensions}")
    
    issues = config.validate()
    if issues:
        print("⚠️ Configuration Issues:")
        for issue in issues:
            print(f"  - {issue}")