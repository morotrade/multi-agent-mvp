#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diff generation, validation and application for AI Developer
"""
import os
import re
from typing import Optional

from utils import (
    call_llm_api, 
    get_preferred_model,
    extract_single_diff,
    validate_diff_files,
    apply_diff_resilient
)
from .path_isolation import enforce_diff_under_root


class DiffProcessor:
    """Handles LLM diff generation, validation and application"""
    
    def __init__(self, model: Optional[str] = None, max_tokens: int = 4000, temperature: float = 0.15):
        self.model = model or self._get_default_model()
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        # System prompt ensuring unified diff output
        self.system_prompt = """You are an expert software engineer bot.
You MUST output exactly ONE unified diff (GNU unified format) inside a single fenced block (```diff ... ```).
Only touch files inside the enforced project root provided in the instructions.
Do not include explanations outside the fenced block."""
    
    def _get_default_model(self) -> str:
        """Get default model from env or utils"""
        return os.getenv("DEVELOPER_MODEL") or get_preferred_model("developer")
    
    def generate_diff(self, prompt: str) -> str:
        """
        Generate unified diff from LLM based on prompt.
        Returns validated diff text ready for application.
        """
        print(f"🤖 Calling LLM model: {self.model}")
        
        # Call LLM API with temperature support fallback
        try:
            raw_response = call_llm_api(
                f"{self.system_prompt}\n\n{prompt}",
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
        except TypeError:
            # Some versions don't accept 'temperature'
            raw_response = call_llm_api(
                f"{self.system_prompt}\n\n{prompt}",
                model=self.model,
                max_tokens=self.max_tokens
            )
        
        if not raw_response or "```" not in raw_response:
            raise RuntimeError(
                "LLM returned empty/invalid content. Expected ONE ```diff ...``` block with unified diff."
            )
        
        # Extract single diff block from response
        diff = extract_single_diff(raw_response)
        if not diff.strip():
            raise RuntimeError(
                "Empty diff parsed from LLM response. Expected valid unified diff format."
            )
        
        return diff
    
    def validate_and_enforce_paths(self, diff: str, project_root: str) -> None:
        """
        Validate diff against security rules and project root isolation.
        Raises RuntimeError if validation fails.
        """
        # First: validate against global whitelist/denylist
        validate_diff_files(diff)
        
        # Second: enforce project root isolation
        enforce_diff_under_root(diff, project_root)
        
        print(f"✅ Diff validation passed for project root: {project_root}")
    
    def apply_diff(self, diff: str) -> bool:
        """
        Apply diff to working directory using resilient method.
        Returns True if successful, False otherwise.
        """
        return apply_diff_resilient(diff)
    
    def process_full_cycle(self, prompt: str, project_root: str) -> str:
        """
        Complete cycle: generate -> validate -> return diff.
        The diff still needs to be applied separately by caller.
        """
        # Generate diff from LLM
        diff = self.generate_diff(prompt)
        
        # Validate paths and security
        self.validate_and_enforce_paths(diff, project_root)
        
        return diff
    
    @staticmethod
    def sanitize_error_for_comment(error_text: str) -> str:
        """Sanitize error text for safe GitHub comment posting"""
        if not error_text:
            return ""
        
        # Remove potentially dangerous shell injection patterns
        sanitized = re.sub(r'[;&|><`]', '', str(error_text))
        # Evita ping accidentali: trasforma @ in full-width ＠
        sanitized = sanitized.replace("@", "＠")
        
        # Limit length for readability
        if len(sanitized) > 2000:
            sanitized = sanitized[:2000] + "... (truncated)"
        
        return sanitized
