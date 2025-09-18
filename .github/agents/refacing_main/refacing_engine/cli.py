"""
Command-line interface for the refacing engine
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import FullFileRefacer, RefaceError
from .config import get_config, apply_preset, print_current_config
from .integration import RefacingFeatureFlags


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser"""
    parser = argparse.ArgumentParser(
        description="Full File Refacing Engine - Rewrite files using LLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic refacing
  python -m reface_engine.cli reface src/utils.py "Add type hints and docstrings"
  
  # With review history
  python -m reface_engine.cli reface src/utils.py "Fix issues" \\
    --review "Add validation" --review "Fix naming"
  
  # Dry run to see what would change
  python -m reface_engine.cli dry-run src/utils.py "Add type hints"
  
  # Cost estimation
  python -m reface_engine.cli estimate src/utils.py "Add type hints"
  
  # Configuration management
  python -m reface_engine.cli config --show
  python -m reface_engine.cli config --preset production
        """
    )
    
    # Global options
    parser.add_argument('--model', help='LLM model to use')
    parser.add_argument('--confidence', type=float, help='Minimum confidence threshold (0.0-1.0)')
    parser.add_argument('--no-format', action='store_true', help='Disable auto-formatting')
    parser.add_argument('--no-keep-blocks', action='store_true', help='Disable KEEP blocks validation')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    # Subcommands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Reface command
    reface_parser = subparsers.add_parser('reface', help='Reface a file')
    reface_parser.add_argument('file_path', help='Path to file to reface')
    reface_parser.add_argument('requirements', help='Requirements/changes needed')
    reface_parser.add_argument('--review', action='append', default=[], 
                              help='Review comment (can be used multiple times)')
    reface_parser.add_argument('--style-guide', help='Style guide/constraints')
    reface_parser.add_argument('--force', action='store_true', 
                              help='Force execution even with low confidence')
    
    # Dry run command
    dry_run_parser = subparsers.add_parser('dry-run', help='Dry run without applying changes')
    dry_run_parser.add_argument('file_path', help='Path to file to analyze')
    dry_run_parser.add_argument('requirements', help='Requirements/changes needed')
    dry_run_parser.add_argument('--review', action='append', default=[],
                               help='Review comment (can be used multiple times)')
    dry_run_parser.add_argument('--style-guide', help='Style guide/constraints')
    
    # Estimate command
    estimate_parser = subparsers.add_parser('estimate', help='Estimate costs')
    estimate_parser.add_argument('file_path', help='Path to file to analyze')
    estimate_parser.add_argument('requirements', help='Requirements/changes needed')
    estimate_parser.add_argument('--review', action='append', default=[],
                                help='Review comment (can be used multiple times)')
    estimate_parser.add_argument('--style-guide', help='Style guide/constraints')
    
    # Configuration command
    config_parser = subparsers.add_parser('config', help='Configuration management')
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument('--show', action='store_true', help='Show current configuration')
    config_group.add_argument('--preset', choices=['development', 'production', 'conservative', 'experimental'],
                             help='Apply configuration preset')
    config_group.add_argument('--validate', action='store_true', help='Validate current configuration')
    
    # Check command
    check_parser = subparsers.add_parser('check', help='Check file compatibility')
    check_parser.add_argument('file_path', help='Path to file to check')
    check_parser.add_argument('--requirements', help='Optional requirements for analysis')
    
    return parser


def cmd_reface(args: argparse.Namespace) -> int:
    """Execute reface command"""
    try:
        # Create refacer with configuration
        config = get_config()
        
        # Override config with command line args
        kwargs = {}
        if args.model:
            kwargs['model'] = args.model
        if args.confidence is not None:
            kwargs['min_confidence'] = args.confidence
        if args.no_format:
            kwargs['enable_auto_format'] = False
        if args.no_keep_blocks:
            kwargs['enable_keep_blocks'] = False
        
        refacer = FullFileRefacer(**kwargs)
        
        # Force mode overrides confidence threshold
        if args.force:
            refacer.validator.min_confidence = 0.0
        
        if args.verbose:
            print(f"🔧 Refacing {args.file_path}")
            print(f"📝 Requirements: {args.requirements}")
            if args.review:
                print(f"📋 Reviews: {len(args.review)} items")
        
        success = refacer.reface_file(
            file_path=args.file_path,
            requirements=args.requirements,
            review_history=args.review,
            style_guide=args.style_guide or ""
        )
        
        if success:
            print("✅ File successfully refaced")
            return 0
        else:
            print("❌ Refacing failed")
            return 1
            
    except RefaceError as e:
        print(f"❌ Refacing error: {e}")
        return 1
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Execute dry run command"""
    try:
        config = get_config()
        
        kwargs = {}
        if args.model:
            kwargs['model'] = args.model
        
        refacer = FullFileRefacer(**kwargs)
        
        result = refacer.dry_run(
            file_path=args.file_path,
            requirements=args.requirements,
            review_history=args.review,
            style_guide=args.style_guide or ""
        )
        
        if result['success']:
            print("🔍 Dry Run Results:")
            print(f"  File: {result['file_path']}")
            print(f"  Confidence: {result['confidence']:.2f}")
            print(f"  Content Length: {result['content_length']:,} chars")
            print(f"  Content Lines: {result['content_lines']:,}")
            print(f"  Meets Threshold: {result['meets_confidence_threshold']}")
            print(f"  Changes ({len(result['changelog'])}):")
            for i, change in enumerate(result['changelog'][:10], 1):
                print(f"    {i}. {change}")
            if len(result['changelog']) > 10:
                print(f"    ... and {len(result['changelog']) - 10} more")
            return 0
        else:
            print(f"❌ Dry run failed: {result['error']}")
            return 1
            
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        return 1


def cmd_estimate(args: argparse.Namespace) -> int:
    """Execute estimate command"""
    try:
        config = get_config()
        
        kwargs = {}
        if args.model:
            kwargs['model'] = args.model
        
        refacer = FullFileRefacer(**kwargs)
        
        estimate = refacer.estimate_cost(
            file_path=args.file_path,
            requirements=args.requirements,
            review_history=args.review,
            style_guide=args.style_guide or ""
        )
        
        if 'error' not in estimate:
            print("💰 Cost Estimation:")
            print(f"  File: {estimate['file_path']}")
            print(f"  Model: {estimate['model']}")
            print(f"  Input Tokens: ~{estimate['input_tokens']:,}")
            print(f"  Output Tokens: ~{estimate['estimated_output_tokens']:,}")
            print(f"  Total Tokens: ~{estimate['total_estimated_tokens']:,}")
            print(f"  Review Count: {estimate['review_count']}")
            print(f"  Requirements Length: {estimate['requirements_length']:,} chars")
            return 0
        else:
            print(f"❌ Estimation failed: {estimate['error']}")
            return 1
            
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    """Execute config command"""
    try:
        if args.show:
            print_current_config()
            return 0
        
        elif args.preset:
            print(f"🔧 Applying preset: {args.preset}")
            apply_preset(args.preset)
            print("✅ Preset applied successfully")
            print_current_config()
            return 0
        
        elif args.validate:
            config = get_config()
            issues = config.validate()
            if issues:
                print("❌ Configuration validation failed:")
                for issue in issues:
                    print(f"  - {issue}")
                return 1
            else:
                print("✅ Configuration is valid")
                return 0
        
    except Exception as e:
        print(f"💥 Configuration error: {e}")
        return 1


def cmd_check(args: argparse.Namespace) -> int:
    """Execute check command"""
    try:
        file_path = Path(args.file_path)
        
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return 1
        
        config = get_config()
        
        # Basic file info
        file_size = file_path.stat().st_size
        file_ext = file_path.suffix.lower()
        
        print(f"📋 File Analysis: {file_path}")
        print(f"  Size: {file_size:,} bytes")
        print(f"  Extension: {file_ext}")
        
        # Support check
        is_supported = config.is_file_supported(str(file_path))
        print(f"  Supported: {'✅ Yes' if is_supported else '❌ No'}")
        
        if is_supported:
            # Language-specific info
            from .utils import get_language_tag
            language = get_language_tag(str(file_path))
            print(f"  Language: {language}")
            
            formatter_config = config.get_formatter_config(language)
            validator_config = config.get_validator_config(language)
            
            print(f"  Formatters: {formatter_config.get('tools', [])}")
            print(f"  Validators: {validator_config.get('tools', [])}")
        
        # Size compatibility
        if file_size > config.max_file_size:
            print(f"  ⚠️  File exceeds max size ({config.max_file_size:,} bytes)")
        
        # KEEP blocks analysis
        if config.keep_blocks:
            try:
                content = file_path.read_text(encoding='utf-8')
                from .keep_blocks import KEEPBlockValidator
                
                keep_blocks = KEEPBlockValidator.extract_keep_blocks(content)
                if keep_blocks:
                    print(f"  KEEP Blocks: {len(keep_blocks)} found")
                    for block_id in keep_blocks:
                        print(f"    - {block_id}")
                else:
                    print(f"  KEEP Blocks: None")
                    
            except Exception as e:
                print(f"  KEEP Blocks: Error analyzing ({e})")
        
        # Refacing recommendation
        if args.requirements:
            from .integration import EnhancedPRFixMode
            enhanced_mode = EnhancedPRFixMode(use_refacing=True)
            
            recommendation = enhanced_mode.get_strategy_recommendation(
                file_path=str(file_path),
                requirements=args.requirements,
                review_history=[]
            )
            
            print(f"\n🎯 Refacing Recommendation:")
            print(f"  Recommended: {'✅ Yes' if recommendation['recommend_refacing'] else '❌ No'}")
            print(f"  Confidence: {recommendation['confidence_score']:.2f}")
            print(f"  Reasons:")
            for reason in recommendation['reasons']:
                print(f"    - {reason}")
        
        return 0
        
    except Exception as e:
        print(f"💥 Check failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point"""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Set up verbose logging if requested
    if hasattr(args, 'verbose') and args.verbose:
        import logging
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    
    # Route to command handlers
    command_handlers = {
        'reface': cmd_reface,
        'dry-run': cmd_dry_run,
        'estimate': cmd_estimate,
        'config': cmd_config,
        'check': cmd_check
    }
    
    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"❌ Unknown command: {args.command}")
        return 1


if __name__ == '__main__':
    sys.exit(main())