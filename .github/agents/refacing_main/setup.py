"""
Setup configuration for reface_engine package
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
README_PATH = Path(__file__).parent / "reface_engine" / "README.md"
long_description = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""

setup(
    name="reface_engine",
    version="1.0.0",
    description="Production-ready full file refacing engine using LLMs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="AI Development Team",
    author_email="dev@example.com",
    url="https://github.com/yourusername/reface_engine",
    
    # Package configuration
    packages=find_packages(),
    python_requires=">=3.8",
    
    # Dependencies
    install_requires=[
        "httpx>=0.27.0",
        "pathlib>=1.0.1",
    ],
    
    # Optional dependencies
    extras_require={
        "openai": ["openai>=1.40.0"],
        "anthropic": ["anthropic>=0.36.0"],
        "gemini": ["google-generativeai>=0.7.0"],
        "all": [
            "openai>=1.40.0",
            "anthropic>=0.36.0", 
            "google-generativeai>=0.7.0"
        ],
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
            "mypy>=1.0.0",
        ],
        "formatters": [
            "black>=23.0.0",
            "ruff>=0.1.0",
        ]
    },
    
    # CLI entry points
    entry_points={
        "console_scripts": [
            "reface=reface_engine.cli:main",
        ],
    },
    
    # Package metadata
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Text Processing :: Linguistic",
    ],
    
    # Keywords for discoverability
    keywords=[
        "llm", "refactoring", "code-generation", "ai", "automation",
        "file-rewriting", "code-improvement", "developer-tools"
    ],
    
    # Include package data
    include_package_data=True,
    package_data={
        "reface_engine": [
            "README.md",
            "py.typed",  # Type hints marker
        ],
        "reface_engine.tests": [
            "data/*",
            "*.py",
        ],
    },
    
    # Project URLs
    project_urls={
        "Bug Reports": "https://github.com/yourusername/reface_engine/issues",
        "Source": "https://github.com/yourusername/reface_engine",
        "Documentation": "https://reface-engine.readthedocs.io/",
    },
    
    # Zip safety
    zip_safe=False,
)