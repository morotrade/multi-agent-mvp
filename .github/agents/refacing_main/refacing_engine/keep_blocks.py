"""
KEEP blocks support for preserving critical code sections during refacing
"""
import re
from typing import Dict

from .exceptions import KeepBlockRemovedError, KeepBlockModifiedError


class KEEPBlockValidator:
    """Validates that KEEP blocks are preserved during refacing"""
    
    KEEP_OPEN_PATTERN = re.compile(r"# >>> KEEP:(?P<id>[A-Za-z0-9_\-]+)")
    KEEP_CLOSE_PATTERN = re.compile(r"# <<< KEEP:(?P<id>[A-Za-z0-9_\-]+)")
    
    @classmethod
    def extract_keep_blocks(cls, content: str) -> Dict[str, str]:
        """
        Extract KEEP blocks from content.
        
        Args:
            content: Source code content
            
        Returns:
            Dictionary mapping block_id to full block content (including markers)
        """
        blocks = {}
        lines = content.split('\n')
        current_block_id = None
        current_block_lines = []
        
        for line in lines:
            # Check for opening marker
            open_match = cls.KEEP_OPEN_PATTERN.search(line)
            if open_match:
                if current_block_id is not None:
                    # Nested KEEP blocks are not allowed
                    raise ValueError(f"Nested KEEP block found: {open_match.group('id')} inside {current_block_id}")
                
                current_block_id = open_match.group('id')
                current_block_lines = [line]
                continue
            
            # If we're inside a block, collect lines
            if current_block_id:
                current_block_lines.append(line)
                
                # Check for closing marker
                close_match = cls.KEEP_CLOSE_PATTERN.search(line)
                if close_match:
                    if close_match.group('id') != current_block_id:
                        raise ValueError(
                            f"Mismatched KEEP block: opened {current_block_id}, "
                            f"closed {close_match.group('id')}"
                        )
                    
                    # Store complete block
                    blocks[current_block_id] = '\n'.join(current_block_lines)
                    current_block_id = None
                    current_block_lines = []
        
        # Check for unclosed blocks
        if current_block_id is not None:
            raise ValueError(f"Unclosed KEEP block: {current_block_id}")
        
        return blocks
    
    @classmethod
    def validate_keep_blocks_preserved(cls, original: str, new_content: str) -> None:
        """
        Validate that KEEP blocks are preserved exactly.
        
        Args:
            original: Original file content
            new_content: New file content after refacing
            
        Raises:
            KeepBlockRemovedError: If a KEEP block was removed
            KeepBlockModifiedError: If a KEEP block was modified
        """
        try:
            original_blocks = cls.extract_keep_blocks(original)
            new_blocks = cls.extract_keep_blocks(new_content)
        except ValueError as e:
            raise ValueError(f"KEEP block validation failed: {e}")
        
        # Check for removed blocks
        for block_id in original_blocks:
            if block_id not in new_blocks:
                raise KeepBlockRemovedError(block_id)
        
        # Check for modified blocks
        for block_id, original_block in original_blocks.items():
            if block_id in new_blocks:
                if new_blocks[block_id] != original_block:
                    raise KeepBlockModifiedError(block_id)
        
        # Note: New KEEP blocks in the refaced content are allowed
        # Only preservation of existing blocks is enforced
    
    @classmethod
    def get_keep_blocks_info(cls, content: str) -> Dict[str, Dict]:
        """
        Get information about KEEP blocks in content.
        
        Returns:
            Dictionary with block info including line numbers and content length
        """
        blocks = cls.extract_keep_blocks(content)
        info = {}
        
        lines = content.split('\n')
        for block_id, block_content in blocks.items():
            block_lines = block_content.split('\n')
            
            # Find start line
            start_line = None
            for i, line in enumerate(lines):
                if cls.KEEP_OPEN_PATTERN.search(line):
                    match = cls.KEEP_OPEN_PATTERN.search(line)
                    if match.group('id') == block_id:
                        start_line = i + 1  # 1-based line numbers
                        break
            
            info[block_id] = {
                'start_line': start_line,
                'line_count': len(block_lines),
                'char_count': len(block_content),
                'content_preview': block_content[:100] + '...' if len(block_content) > 100 else block_content
            }
        
        return info
    
    @classmethod
    def validate_block_syntax(cls, content: str) -> None:
        """
        Validate KEEP block syntax without extracting content.
        
        Raises:
            ValueError: If syntax is invalid
        """
        lines = content.split('\n')
        open_blocks = {}  # block_id -> line_number
        
        for line_num, line in enumerate(lines, 1):
            # Check for opening marker
            open_match = cls.KEEP_OPEN_PATTERN.search(line)
            if open_match:
                block_id = open_match.group('id')
                if block_id in open_blocks:
                    raise ValueError(
                        f"Duplicate KEEP block ID '{block_id}' at line {line_num} "
                        f"(first occurrence at line {open_blocks[block_id]})"
                    )
                open_blocks[block_id] = line_num
                continue
            
            # Check for closing marker
            close_match = cls.KEEP_CLOSE_PATTERN.search(line)
            if close_match:
                block_id = close_match.group('id')
                if block_id not in open_blocks:
                    raise ValueError(
                        f"Closing KEEP block '{block_id}' at line {line_num} "
                        f"without corresponding opening marker"
                    )
                del open_blocks[block_id]
        
        # Check for unclosed blocks
        if open_blocks:
            unclosed = ', '.join(f"'{bid}' (line {line})" for bid, line in open_blocks.items())
            raise ValueError(f"Unclosed KEEP blocks: {unclosed}")