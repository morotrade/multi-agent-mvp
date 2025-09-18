# Full File Refacing Engine

A robust, production-ready module for complete file rewriting using Large Language Models (LLMs) with validation, atomic operations, and advanced safety features.

## 🚀 Key Features

- **Complete File Rewriting**: Generate entire file contents instead of fragile diff patches
- **Hash-based Integrity**: Verify file hasn't changed since context was built
- **KEEP Blocks Support**: Preserve critical code sections during refacing
- **Multi-language Validation**: Syntax checking for Python, JavaScript, TypeScript, and more
- **Atomic Operations**: Safe file replacement with rollback capability
- **Auto-formatting**: Integrated code formatting with formatter protection
- **Git Integration**: Smart commit handling with change detection
- **Confidence Thresholds**: Configurable quality gates for automatic vs manual review

## 📦 Installation

```bash
# Install as part of your project
pip install -e .

# Or add to requirements.txt
echo "reface_engine @ file://path/to/reface_engine" >> requirements.txt
```

## 🛠 Quick Start

### Basic Usage

```python
from reface_engine import FullFileRefacer

# Initialize the refacer
refacer = FullFileRefacer(
    model="gpt-4o-mini",
    min_confidence=0.75
)

# Reface a file
success = refacer.reface_file(
    file_path="src/utils.py",
    requirements="Add comprehensive type hints and docstrings",
    review_history=[
        "Functions need proper typing",
        "Missing docstrings for public methods",
        "Add input validation"
    ],
    style_guide="Follow PEP 8 and Google docstring format"
)

if success:
    print("✅ File successfully refaced!")
else:
    print("❌ Refacing failed - check logs")
```

### CLI Usage

```bash
# Basic refacing
python -m reface_engine.cli reface src/utils.py "Add type hints and docstrings"

# With review history
python -m reface_engine.cli reface src/utils.py "Fix issues" \
  --review "Add validation" \
  --review "Fix naming conventions"

# Dry run to preview changes
python -m reface_engine.cli dry-run src/utils.py "Add type hints"

# Cost estimation
python -m reface_engine.cli estimate src/utils.py "Add type hints"

# Configuration management
python -m reface_engine.cli config --show
python -m reface_engine.cli config --preset production
```

## 🔧 Configuration

### Environment Variables

```bash
# Core settings
export REFACE_STRATEGY="full"           # Enable refacing strategy
export REFACE_MODEL="gpt-4o-mini"       # LLM model to use
export REFACE_MIN_CONFIDENCE="0.75"     # Minimum confidence threshold

# Feature flags
export REFACE_AUTO_FORMAT="true"        # Enable auto-formatting
export REFACE_KEEP_BLOCKS="true"        # Enable KEEP blocks validation
export REFACE_GIT_COMMIT="true"         # Enable git commits

# Limits
export REFACE_MAX_FILE_SIZE="1000000"   # Max file size (1MB)
export REFACE_MAX_RETRIES="1"           # Max retries on base changes
```

### Configuration Presets

```python
from reface_engine.config import apply_preset

# Apply predefined configurations
apply_preset('development')    # Lower thresholds, more retries
apply_preset('production')     # Higher thresholds, robust settings
apply_preset('conservative')   # Very safe settings
apply_preset('experimental')   # Bleeding edge settings
```

## 🛡 KEEP Blocks

Preserve critical code sections that should never be modified:

```python
# >>> KEEP:database_connection
DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(DATABASE_URL)
# <<< KEEP:database_connection

def get_user(user_id: int):
    # This function can be refaced
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM users WHERE id = :id"),
            {"id": user_id}
        )
        return result.fetchone()
```

The KEEP block will be preserved exactly during refacing, while the function can be improved with type hints, docstrings, error handling, etc.

## 🔄 Integration with Existing Systems

### Replace Diff-based Approach

```python
# Before: Fragile diff application
# diff = generate_diff(prompt)
# apply_diff(diff)  # ← Often fails!

# After: Robust refacing
from reface_engine import FullFileRefacer

refacer = FullFileRefacer()
success = refacer.reface_file(
    file_path="target_file.py",
    requirements="Your requirements here",
    review_history=["Review comment 1", "Review comment 2"]
)
```

### Feature Flag Integration

```python
from reface_engine.integration import EnhancedPRFixMode

# Automatically detect strategy from environment
enhanced_mode = EnhancedPRFixMode()

result = enhanced_mode.process_pr_fix(
    pr_number=123,
    file_path="src/utils.py",
    requirements="Fix reviewer feedback",
    review_history=["Add validation", "Fix error handling"]
)

print(f"Strategy used: {result['strategy']}")
print(f"Success: {result['success']}")
```

## 📊 Monitoring and Cost Control

### Cost Estimation

```python
# Estimate before execution
estimate = refacer.estimate_cost(
    file_path="large_file.py",
    requirements="Major refactoring",
    review_history=multiple_reviews
)

print(f"Estimated tokens: {estimate['total_estimated_tokens']:,}")
print(f"Model: {estimate['model']}")

# Proceed only if cost is acceptable
if estimate['total_estimated_tokens'] < 10000:
    success = refacer.reface_file(...)
```

### Dry Run Analysis

```python
# Preview changes without applying
result = refacer.dry_run(
    file_path="src/utils.py",
    requirements="Add comprehensive error handling"
)

print(f"Confidence: {result['confidence']:.2f}")
print(f"Changes planned: {len(result['changelog'])}")
for change in result['changelog']:
    print(f"  - {change}")
```

## 🧪 Testing

```bash
# Run the test suite
python -m pytest reface_engine/tests/

# Run with coverage
python -m pytest reface_engine/tests/ --cov=reface_engine --cov-report=html

# Run specific test categories
python -m pytest reface_engine/tests/test_core.py -v
python -m pytest reface_engine/tests/test_keep_blocks.py -v
```

## 🔍 Troubleshooting

### Common Issues

1. **Low Confidence Errors**
   ```bash
   # Lower the threshold temporarily
   export REFACE_MIN_CONFIDENCE="0.6"
   
   # Or use force mode in CLI
   python -m reface_engine.cli reface file.py "requirements" --force
   ```

2. **Base File Changed Errors**
   ```bash
   # Automatic retry is built-in, but you can increase retries
   export REFACE_MAX_RETRIES="2"
   ```

3. **Syntax Validation Failures**
   ```bash
   # Check file syntax before refacing
   python -m reface_engine.cli check file.py
   
   # Disable validation temporarily (not recommended)
   export REFACE_SYNTAX_VALIDATION="false"
   ```

4. **Large File Issues**
   ```bash
   # Increase size limit
   export REFACE_MAX_FILE_SIZE="2000000"  # 2MB
   
   # Or split large files into smaller modules
   ```

### Debug Mode

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or use verbose CLI
python -m reface_engine.cli reface file.py "requirements" --verbose
```

## 🎯 Best Practices

1. **Start Conservative**: Use higher confidence thresholds in production
2. **Use KEEP Blocks**: Protect critical configuration and connection code
3. **Test First**: Always run dry-run on important files
4. **Monitor Costs**: Use estimation for budget planning
5. **Review Changes**: Check git diffs before committing
6. **Gradual Rollout**: Start with non-critical files

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🔗 Related Projects

- **LLM Providers**: Supports OpenAI, Anthropic, Google Gemini
- **Code Formatters**: Integrates with Black, Prettier, ESLint
- **Version Control**: Built-in Git integration
- **CI/CD**: Easy integration with GitHub Actions

---

**Need help?** Check the [examples](examples/) directory or open an issue on GitHub.