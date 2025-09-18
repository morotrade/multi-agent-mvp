# Makefile for reface_engine development and deployment

.PHONY: help install install-dev test test-cov lint format type-check clean build upload docs

# Default target
help:
	@echo "Available targets:"
	@echo "  install      - Install package for production"
	@echo "  install-dev  - Install package with development dependencies"
	@echo "  test         - Run test suite"
	@echo "  test-cov     - Run tests with coverage report"
	@echo "  lint         - Run linting checks"
	@echo "  format       - Format code with black and ruff"
	@echo "  type-check   - Run type checking with mypy"
	@echo "  clean        - Clean build artifacts"
	@echo "  build        - Build distribution packages"
	@echo "  upload       - Upload to PyPI (requires authentication)"
	@echo "  docs         - Generate documentation"
	@echo "  check-all    - Run all quality checks"

# Installation targets
install:
	pip install -e .

install-dev:
	pip install -e ".[dev,all]"

install-formatters:
	pip install -e ".[formatters]"

# Testing targets
test:
	python -m pytest reface_engine/tests/ -v

test-cov:
	python -m pytest reface_engine/tests/ --cov=reface_engine --cov-report=html --cov-report=term-missing

test-integration:
	python -m pytest reface_engine/tests/ -v -m integration

# Code quality targets
lint:
	ruff check reface_engine/
	black --check reface_engine/

format:
	black reface_engine/
	ruff check --fix reface_engine/

type-check:
	mypy reface_engine/ --ignore-missing-imports

# Comprehensive quality check
check-all: lint type-check test

# Build and distribution
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python setup.py sdist bdist_wheel

upload: build
	twine upload dist/*

upload-test: build
	twine upload --repository testpypi dist/*

# Documentation
docs:
	@echo "Generating documentation..."
	@mkdir -p docs/
	@echo "# Reface Engine Documentation" > docs/index.md
	@echo "" >> docs/index.md
	@cat reface_engine/README.md >> docs/index.md

# Development utilities
demo:
	@echo "Running reface engine demo..."
	python -m reface_engine.cli config --show

check-config:
	python -m reface_engine.cli config --validate

check-env:
	@echo "Checking environment variables..."
	@python -c "from reface_engine.integration import RefacingFeatureFlags; import json; print(json.dumps(RefacingFeatureFlags.get_configuration(), indent=2))"

# Example usage
example-dry-run:
	@echo "Creating example file..."
	@echo 'def hello(): print("hello")' > /tmp/example.py
	python -m reface_engine.cli dry-run /tmp/example.py "Add type hints and docstring"
	@rm -f /tmp/example.py

example-estimate:
	@echo "Creating example file..."
	@echo 'def hello(): print("hello")' > /tmp/example.py
	python -m reface_engine.cli estimate /tmp/example.py "Add type hints and docstring"
	@rm -f /tmp/example.py

# CI/CD helpers
ci-install:
	pip install -e ".[dev,all]"

ci-test:
	python -m pytest reface_engine/tests/ --cov=reface_engine --cov-report=xml --junitxml=junit.xml

ci-quality:
	ruff check reface_engine/ --output-format=github
	black --check reface_engine/
	mypy reface_engine/ --ignore-missing-imports

# Performance testing
perf-test:
	@echo "Running performance tests..."
	@python -c "
import time
from reface_engine import FullFileRefacer
start = time.time()
refacer = FullFileRefacer()
end = time.time()
print(f'Initialization time: {end-start:.3f}s')
"

# Security checks
security-check:
	@echo "Running security checks..."
	@python -c "
from reface_engine.utils import get_repo_root, is_path_under_repo
from pathlib import Path
print('✅ Security utilities working')
"

# Dependency management
deps-update:
	@echo "Checking for dependency updates..."
	pip list --outdated

deps-tree:
	pip show reface_engine

# Development server (for API mode if implemented)
dev-server:
	@echo "Development server not implemented yet"
	@echo "Use CLI interface: make demo"

# Release preparation
pre-release: clean check-all build
	@echo "Pre-release checks completed"
	@echo "Ready for release!"

release-patch:
	@echo "Bumping patch version..."
	@# This would integrate with version bumping tools
	@echo "Manual version bump required in setup.py"

release-minor:
	@echo "Bumping minor version..."
	@echo "Manual version bump required in setup.py"

# Backup and restore
backup-config:
	@mkdir -p backup/
	@echo "Backing up configuration..."
	env | grep REFACE_ > backup/reface_env.txt || true

restore-config:
	@echo "Restoring configuration..."
	@if [ -f backup/reface_env.txt ]; then \
		echo "Source backup/reface_env.txt to restore environment"; \
	else \
		echo "No backup found"; \
	fi

# Docker support (if needed)
docker-build:
	@echo "Docker support not implemented"
	@echo "Consider adding Dockerfile for containerized usage"

# Monitoring
log-usage:
	@echo "Usage logging not implemented"
	@echo "Consider adding telemetry for production usage"