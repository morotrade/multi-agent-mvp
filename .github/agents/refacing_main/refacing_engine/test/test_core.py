"""
Tests for core refacing functionality
"""
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from reface_engine.core import RefaceContract, FullFileRefacer
from reface_engine.exceptions import RefaceError, LowConfidenceError, BaseChangedError


class TestRefaceContract:
    """Test RefaceContract data structure"""
    
    def test_valid_contract(self):
        """Test valid contract creation"""
        contract = RefaceContract(
            file_path="test.py",
            pre_hash="sha256:abc123",
            new_content="print('hello')",
            changelog=["Added print statement"],
            confidence=0.9
        )
        
        assert contract.file_path == "test.py"
        assert contract.pre_hash == "sha256:abc123"
        assert contract.new_content == "print('hello')"
        assert contract.changelog == ["Added print statement"]
        assert contract.confidence == 0.9
    
    def test_default_confidence(self):
        """Test default confidence value"""
        contract = RefaceContract(
            file_path="test.py",
            pre_hash="sha256:abc123",
            new_content="print('hello')",
            changelog=["Added print statement"]
        )
        
        assert contract.confidence == 0.8
    
    def test_invalid_file_path(self):
        """Test invalid file path validation"""
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            RefaceContract(
                file_path="",
                pre_hash="sha256:abc123",
                new_content="print('hello')",
                changelog=["Added print statement"]
            )
    
    def test_invalid_confidence(self):
        """Test invalid confidence validation"""
        with pytest.raises(ValueError, match="confidence must be a number between 0.0 and 1.0"):
            RefaceContract(
                file_path="test.py",
                pre_hash="sha256:abc123",
                new_content="print('hello')",
                changelog=["Added print statement"],
                confidence=1.5
            )
    
    def test_invalid_changelog(self):
        """Test invalid changelog validation"""
        with pytest.raises(ValueError, match="changelog must be a list"):
            RefaceContract(
                file_path="test.py",
                pre_hash="sha256:abc123",
                new_content="print('hello')",
                changelog="Not a list"
            )


class TestFullFileRefacer:
    """Test FullFileRefacer main orchestrator"""
    
    def test_init(self):
        """Test refacer initialization"""
        refacer = FullFileRefacer(
            model="test-model",
            min_confidence=0.9,
            enable_auto_format=False
        )
        
        assert refacer.model == "test-model"
        assert refacer.validator.min_confidence == 0.9
        assert refacer.validator.enable_auto_format == False
    
    def test_default_init(self):
        """Test refacer with default values"""
        refacer = FullFileRefacer()
        
        assert refacer.model == "gpt-4o-mini"
        assert refacer.validator.min_confidence == 0.75
        assert refacer.validator.enable_auto_format == True
    
    @patch('reface_engine.core.ContextBuilder')
    @patch('reface_engine.core.FileRewriter')
    @patch('reface_engine.core.ValidatorApplier')
    def test_reface_file_success(self, mock_validator, mock_rewriter, mock_context):
        """Test successful file refacing"""
        # Setup mocks
        mock_context_instance = Mock()
        mock_context.return_value = mock_context_instance
        mock_context_instance.build.return_value = "mock context"
        
        mock_rewriter_instance = Mock()
        mock_rewriter.return_value = mock_rewriter_instance
        
        mock_contract = RefaceContract(
            file_path="test.py",
            pre_hash="sha256:abc123",
            new_content="print('hello')",
            changelog=["Added print statement"],
            confidence=0.9
        )
        mock_rewriter_instance.generate.return_value = mock_contract
        
        mock_validator_instance = Mock()
        mock_validator.return_value = mock_validator_instance
        mock_validator_instance.check_and_apply.return_value = True
        
        # Test
        refacer = FullFileRefacer()
        result = refacer.reface_file(
            file_path="test.py",
            requirements="Add hello world",
            review_history=["Make it simple"],
            style_guide="PEP 8"
        )
        
        assert result == True
        mock_context_instance.build.assert_called_once()
        mock_rewriter_instance.generate.assert_called_once()
        mock_validator_instance.check_and_apply.assert_called_once()
    
    @patch('reface_engine.core.ContextBuilder')
    @patch('reface_engine.core.FileRewriter')
    @patch('reface_engine.core.ValidatorApplier')
    def test_reface_file_with_retry(self, mock_validator, mock_rewriter, mock_context):
        """Test file refacing with base change retry"""
        # Setup mocks
        mock_context_instance = Mock()
        mock_context.return_value = mock_context_instance
        mock_context_instance.build.return_value = "mock context"
        
        mock_rewriter_instance = Mock()
        mock_rewriter.return_value = mock_rewriter_instance
        mock_contract = RefaceContract(
            file_path="test.py",
            pre_hash="sha256:abc123",
            new_content="print('hello')",
            changelog=["Added print statement"],
            confidence=0.9
        )
        mock_rewriter_instance.generate.return_value = mock_contract
        
        mock_validator_instance = Mock()
        mock_validator.return_value = mock_validator_instance
        # First call raises BaseChangedError, second succeeds
        mock_validator_instance.check_and_apply.side_effect = [
            BaseChangedError("test.py", "old_hash", "new_hash"),
            True
        ]
        
        # Test
        refacer = FullFileRefacer(max_retries=1)
        result = refacer.reface_file(
            file_path="test.py",
            requirements="Add hello world"
        )
        
        assert result == True
        assert mock_validator_instance.check_and_apply.call_count == 2
        assert mock_context_instance.build.call_count == 2  # Called again on retry
    
    @patch('reface_engine.core.ContextBuilder')
    @patch('reface_engine.core.FileRewriter')
    @patch('reface_engine.core.ValidatorApplier')
    def test_reface_file_max_retries_exceeded(self, mock_validator, mock_rewriter, mock_context):
        """Test file refacing when max retries exceeded"""
        # Setup mocks
        mock_context_instance = Mock()
        mock_context.return_value = mock_context_instance
        mock_context_instance.build.return_value = "mock context"
        
        mock_rewriter_instance = Mock()
        mock_rewriter.return_value = mock_rewriter_instance
        mock_contract = RefaceContract(
            file_path="test.py",
            pre_hash="sha256:abc123",
            new_content="print('hello')",
            changelog=["Added print statement"],
            confidence=0.9
        )
        mock_rewriter_instance.generate.return_value = mock_contract
        
        mock_validator_instance = Mock()
        mock_validator.return_value = mock_validator_instance
        # Always raises BaseChangedError
        mock_validator_instance.check_and_apply.side_effect = BaseChangedError(
            "test.py", "old_hash", "new_hash"
        )
        
        # Test
        refacer = FullFileRefacer(max_retries=1)
        
        with pytest.raises(BaseChangedError):
            refacer.reface_file(
                file_path="test.py",
                requirements="Add hello world"
            )
        
        assert mock_validator_instance.check_and_apply.call_count == 2  # Initial + 1 retry
    
    def test_estimate_cost(self):
        """Test cost estimation functionality"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write("# Test file\nprint('hello')\n")
            tmp_path = tmp.name
        
        try:
            refacer = FullFileRefacer()
            
            with patch.object(refacer.rewriter, 'estimate_generation_cost') as mock_estimate:
                mock_estimate.return_value = {
                    'input_tokens': 100,
                    'estimated_output_tokens': 50,
                    'total_estimated_tokens': 150,
                    'model': 'test-model'
                }
                
                estimate = refacer.estimate_cost(
                    file_path=tmp_path,
                    requirements="Add type hints",
                    review_history=["Use proper types"]
                )
                
                assert 'input_tokens' in estimate
                assert 'file_path' in estimate
                assert 'review_count' in estimate
                assert estimate['review_count'] == 1
                
        finally:
            Path(tmp_path).unlink()
    
    def test_dry_run(self):
        """Test dry run functionality"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
            tmp.write("# Test file\nprint('hello')\n")
            tmp_path = tmp.name
        
        try:
            refacer = FullFileRefacer()
            
            with patch.object(refacer.rewriter, 'generate') as mock_generate:
                mock_contract = RefaceContract(
                    file_path=tmp_path,
                    pre_hash="sha256:abc123",
                    new_content="# Test file\nprint('hello world')\n",
                    changelog=["Changed greeting"],
                    confidence=0.85
                )
                mock_generate.return_value = mock_contract
                
                result = refacer.dry_run(
                    file_path=tmp_path,
                    requirements="Change greeting"
                )
                
                assert result['success'] == True
                assert result['confidence'] == 0.85
                assert result['changelog'] == ["Changed greeting"]
                assert result['meets_confidence_threshold'] == True
                
        finally:
            Path(tmp_path).unlink()


@pytest.fixture
def sample_python_file():
    """Create a temporary Python file for testing"""
    content = '''"""
Sample Python module for testing
"""

def hello(name: str = "World") -> str:
    """Say hello to someone"""
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(hello())
'''
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    
    yield tmp_path
    
    # Cleanup
    Path(tmp_path).unlink(missing_ok=True)


class TestIntegrationScenarios:
    """Integration tests for common scenarios"""
    
    def test_python_file_basic_refacing(self, sample_python_file):
        """Test basic Python file refacing"""
        # This would require actual LLM integration, so we'll mock it
        refacer = FullFileRefacer()
        
        with patch.object(refacer.rewriter, 'generate') as mock_generate:
            # Mock a realistic contract
            new_content = '''"""
Sample Python module for testing - enhanced version
"""
from typing import Optional

def hello(name: Optional[str] = "World") -> str:
    """Say hello to someone
    
    Args:
        name: The name to greet (default: "World")
        
    Returns:
        A greeting string
    """
    if not name:
        name = "World"
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(hello())
'''
            
            mock_contract = RefaceContract(
                file_path=sample_python_file,
                pre_hash="sha256:test123",
                new_content=new_content,
                changelog=[
                    "Added typing imports",
                    "Enhanced docstring with Args/Returns",
                    "Added input validation"
                ],
                confidence=0.9
            )
            mock_generate.return_value = mock_contract
            
            # Mock validation to avoid actual file operations
            with patch.object(refacer.validator, 'check_and_apply', return_value=True):
                result = refacer.reface_file(
                    file_path=sample_python_file,
                    requirements="Add type hints and improve docstrings",
                    review_history=["Use proper typing", "Add validation"]
                )
                
                assert result == True