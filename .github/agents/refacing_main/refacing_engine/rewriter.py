"""
LLM-based file rewriter with robust JSON parsing
"""
import json
from typing import TYPE_CHECKING

from .exceptions import ContractValidationError
from .utils import clean_json_response

if TYPE_CHECKING:
    from .core import RefaceContract

# Import LLM provider with fallback
try:
    from utils.llm_providers import call_llm_api
except ImportError:
    try:
        from llm_providers import call_llm_api
    except ImportError:
        raise ImportError(
            "LLM provider not found. Please ensure 'llm_providers' module is available "
            "or install required dependencies."
        )


class FileRewriter:
    """LLM-based complete file rewriter with contract generation"""
    
    def __init__(self, model: str = "gpt-4o-mini", max_tokens: int = 8000, temperature: float = 0.1):
        """
        Initialize file rewriter.
        
        Args:
            model: LLM model to use
            max_tokens: Maximum tokens for generation
            temperature: LLM temperature (lower = more deterministic)
        """
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
    
    def generate(self, context: str) -> 'RefaceContract':
        """
        Generate complete file rewrite using LLM.
        
        Args:
            context: Complete context string for LLM
            
        Returns:
            RefaceContract with rewrite details
            
        Raises:
            ContractValidationError: If LLM output is invalid
            RuntimeError: If generation fails
        """
        # Import here to avoid circular imports
        from .core import RefaceContract
        
        # Enhanced prompt for JSON output
        json_prompt = f"""{context}

CRITICAL: Your response must be ONLY valid JSON. No explanations, no markdown, just JSON."""
        
        try:
            # Call LLM with temperature support
            raw_response = self._call_llm_with_fallback(json_prompt)
            
            # Parse and validate contract
            contract = self._parse_and_validate_response(raw_response, RefaceContract)
            
            print(f"✅ Generated rewrite contract with {len(contract.changelog)} changes")
            print(f"🎯 Confidence: {contract.confidence:.2f}")
            
            return contract
            
        except json.JSONDecodeError as e:
            # One retry with stricter instruction
            print("⚠️ JSON parse failed, retrying with stricter prompt...")
            try:
                retry_prompt = context + "\n\nReturn ONLY raw JSON object. No markdown, no explanations."
                raw_response = self._call_llm_with_fallback(retry_prompt)
                contract = self._parse_and_validate_response(raw_response, RefaceContract)
                return contract
            except json.JSONDecodeError:
                raise ContractValidationError(f"LLM returned invalid JSON after retry: {e}")
                
        except Exception as e:
            raise RuntimeError(f"File rewrite generation failed: {e}")
    
    def _call_llm_with_fallback(self, prompt: str) -> str:
        """Call LLM with temperature fallback for compatibility"""
        try:
            # Try with temperature first
            return call_llm_api(
                prompt,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
        except TypeError:
            # Fallback for APIs that don't support temperature
            return call_llm_api(
                prompt,
                model=self.model,
                max_tokens=self.max_tokens
            )
    
    def _parse_and_validate_response(self, raw_response: str, contract_class) -> 'RefaceContract':
        """Parse LLM response and validate contract structure"""
        if not raw_response or not raw_response.strip():
            raise ContractValidationError("Empty response from LLM")
        
        # Clean and parse JSON
        cleaned_response = clean_json_response(raw_response)
        
        try:
            contract_data = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            raise ContractValidationError(f"Invalid JSON structure: {e}")
        
        # Validate contract structure
        if not isinstance(contract_data, dict):
            raise ContractValidationError("JSON root must be an object")
        
        required_keys = {'file_path', 'pre_hash', 'new_content', 'changelog'}
        missing_keys = required_keys - set(contract_data.keys())
        if missing_keys:
            raise ContractValidationError(f"Missing required keys: {missing_keys}")
        
        # Validate data types
        self._validate_contract_types(contract_data)
        
        # Apply defaults for optional fields
        contract_data.setdefault('confidence', 0.8)
        
        # Ensure confidence is in valid range
        confidence = contract_data['confidence']
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            contract_data['confidence'] = 0.8
        
        # Validate content isn't empty
        if not contract_data['new_content'].strip():
            raise ContractValidationError("new_content cannot be empty")
        
        # Ensure changelog is a list of strings
        changelog = contract_data['changelog']
        if not isinstance(changelog, list):
            contract_data['changelog'] = [str(changelog)] if changelog else []
        else:
            contract_data['changelog'] = [str(item) for item in changelog if item]
        
        return contract_class(**contract_data)
    
    def _validate_contract_types(self, contract_data: dict) -> None:
        """Validate contract field types"""
        type_validations = {
            'file_path': str,
            'pre_hash': str,
            'new_content': str,
            'changelog': list
        }
        
        for field, expected_type in type_validations.items():
            if field in contract_data and not isinstance(contract_data[field], expected_type):
                raise ContractValidationError(
                    f"Field '{field}' must be {expected_type.__name__}, "
                    f"got {type(contract_data[field]).__name__}"
                )
    
    def estimate_generation_cost(self, context: str) -> dict:
        """Estimate token cost for generation (for monitoring/budgeting)"""
        from .utils import estimate_tokens
        
        input_tokens = estimate_tokens(context)
        estimated_output_tokens = min(self.max_tokens, input_tokens // 2)  # Conservative estimate
        
        return {
            'input_tokens': input_tokens,
            'estimated_output_tokens': estimated_output_tokens,
            'total_estimated_tokens': input_tokens + estimated_output_tokens,
            'model': self.model
        }