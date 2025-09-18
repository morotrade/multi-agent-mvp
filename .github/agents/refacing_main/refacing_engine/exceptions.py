"""
Exception hierarchy for the refacing engine
"""


class RefaceError(Exception):
    """Base exception for all refacing operations"""
    pass


class BaseChangedError(RefaceError):
    """Raised when the base file has changed since context was built"""
    
    def __init__(self, file_path: str, expected_hash: str, current_hash: str):
        self.file_path = file_path
        self.expected_hash = expected_hash
        self.current_hash = current_hash
        super().__init__(
            f"BASE_CHANGED: File {file_path} was modified since context was built. "
            f"Expected hash {expected_hash}, but file has changed to {current_hash}."
        )


class LowConfidenceError(RefaceError):
    """Raised when LLM confidence is below threshold"""
    
    def __init__(self, confidence: float, min_confidence: float):
        self.confidence = confidence
        self.min_confidence = min_confidence
        super().__init__(
            f"LOW_CONFIDENCE: {confidence:.2f} < {min_confidence:.2f}. "
            f"Manual review required."
        )


class PathMismatchError(RefaceError):
    """Raised when contract file path doesn't match expected path"""
    
    def __init__(self, contract_path: str, expected_path: str):
        self.contract_path = contract_path
        self.expected_path = expected_path
        super().__init__(
            f"PATH_MISMATCH: contract file_path={contract_path} != expected={expected_path}"
        )


class OversizeOutputError(RefaceError):
    """Raised when generated content exceeds size limits"""
    
    def __init__(self, size: int, limit: int):
        self.size = size
        self.limit = limit
        super().__init__(
            f"OVERSIZE_OUTPUT: new_content size {size} bytes exceeds {limit} bytes limit"
        )


class KeepBlockError(RefaceError):
    """Base class for KEEP block related errors"""
    pass


class KeepBlockRemovedError(KeepBlockError):
    """Raised when a KEEP block is removed"""
    
    def __init__(self, block_id: str):
        self.block_id = block_id
        super().__init__(f"KEEP_BLOCK_REMOVED: Block '{block_id}' was removed")


class KeepBlockModifiedError(KeepBlockError):
    """Raised when a KEEP block is modified"""
    
    def __init__(self, block_id: str):
        self.block_id = block_id
        super().__init__(f"KEEP_BLOCK_MODIFIED: Block '{block_id}' was modified")


class SyntaxValidationError(RefaceError):
    """Raised when syntax validation fails"""
    
    def __init__(self, file_path: str, error_message: str):
        self.file_path = file_path
        self.error_message = error_message
        super().__init__(f"Syntax error in {file_path}: {error_message}")


class UnsafePathError(RefaceError):
    """Raised when file path is outside repository boundaries"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(f"UNSAFE_PATH: {file_path} not under repo or not a git repo")


class ContractValidationError(RefaceError):
    """Raised when LLM contract is invalid"""
    
    def __init__(self, message: str):
        super().__init__(f"Invalid contract: {message}")