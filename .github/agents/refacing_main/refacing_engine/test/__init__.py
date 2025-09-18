"""
Test suite for reface_engine module
"""

# Test configuration
TEST_MODEL = "gpt-4o-mini"
TEST_CONFIDENCE = 0.7
TEST_TIMEOUT = 30

# Test data directory
from pathlib import Path
TEST_DATA_DIR = Path(__file__).parent / "data"
TEST_OUTPUT_DIR = Path(__file__).parent / "output"

# Ensure test directories exist
TEST_DATA_DIR.mkdir(exist_ok=True)
TEST_OUTPUT_DIR.mkdir(exist_ok=True)