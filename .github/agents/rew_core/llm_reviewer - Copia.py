#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM reviewer integration - prompts, parsing, and review execution
"""
import json
import re
import time
from typing import Dict, List, Optional

from utils.llm_providers import call_llm_api, get_preferred_model


class LLMReviewer:
    """Handles LLM-based code review with robust parsing and retry logic"""
    
    def __init__(self, model: Optional[str] = None, max_tokens: int = 4000, max_retries: int = 2):
        self.model = model or get_preferred_model("reviewer")
        self.max_tokens = max_tokens
        self.max_retries = max_retries
    
    def create_review_prompt(self, pr_data: Dict, files_data: List[Dict], project_root: str) -> str:
        """Create standardized prompt for LLM review"""
        title = pr_data.get("title", "")
        body = pr_data.get("body", "")
        
        # Collect diff content with size limit
        diff_sections = []
        total_size = 0
        max_diff_size = 50000  # 50KB limit for diff content
        
        for file_data in files_data:
            filename = file_data.get("filename", "")
            patch = file_data.get("patch", "")
            
            if patch:
                section = f"=== {filename} ===\n{patch}"
                if total_size + len(section) > max_diff_size:
                    diff_sections.append(f"... (remaining files truncated due to size limit)")
                    break
                diff_sections.append(section)
                total_size += len(section)
        
        diff_content = "\n\n".join(diff_sections) if diff_sections else "No changes detected"
        
        prompt = f"""# AI Code Reviewer Task

You are reviewing a Pull Request. Analyze the code changes and provide feedback in JSON format.

## PR Details
Title: {title}
Description: {body}

## Path Scope (VERY IMPORTANT)
- Project root: `{project_root}`
- All analysis and any suggested changes MUST remain strictly under this root.
- Do NOT suggest moving/renaming files outside this root.

## Code Changes
{diff_content}

## Instructions
Analyze the changes and respond with ONLY a JSON object containing:

```json
{{
  "blockers": <number>,
  "importants": <number>, 
  "suggestions": <number>,
  "findings": [
    {{
      "level": "BLOCKER|IMPORTANT|SUGGESTION",
      "file": "path/to/file",
      "line": <number or null>,
      "message": "Description of the issue",
      "suggestion": "How to fix it"
    }}
  ],
  "summary": "Brief overall assessment",
  "patch": "<optional unified diff strictly under {project_root}>",
  "suggested_patches": ["<optional unified diff 1>", "<optional unified diff 2>"]
}}
```

## Evaluation Criteria
- BLOCKER: Critical issues that prevent merge (security, functionality breaking)
- IMPORTANT: Significant issues that should be addressed (performance, maintainability)
- SUGGESTION: Minor improvements or best practices

Focus on:
- Security vulnerabilities
- Logic errors
- Performance issues
- Code quality and maintainability
- Best practices adherence

### Patch Guidance (if any)
- If you provide a `patch` or `suggested_patches`, use a proper unified diff:
  * Use headers like `--- a/{project_root}/...` and `+++ b/{project_root}/...`
  * Include at least one `@@ hunk @@`
  * Ensure paths stay under `{project_root}`
  * Keep patches minimal and focused on fixing findings

"""
        return prompt
    
    def parse_llm_response(self, raw_response: str) -> Dict:
        """
        Robust parsing of LLM response with fallback handling.
        Accepts JSON "naked" or inside ```json ... ``` fences.
        Normalizes patches by removing fence blocks.
        """
        def strip_fences(s: str) -> str:
            """Remove fenced code block markers from strings"""
            text = s.strip()
            # Remove opening fence
            text = re.sub(r'^\s*```(?:diff|patch|json)?\s*', '', text)
            # Remove closing fence  
            text = re.sub(r'\s*```\s*$', '', text)
            return text.strip()
        
        try:
            # Try to extract JSON from fenced block first
            json_match = re.search(r'```json\s*(.*?)\s*```', raw_response, re.DOTALL | re.IGNORECASE)
            json_str = json_match.group(1) if json_match else raw_response.strip()
            
            data = json.loads(json_str)
            
            # Normalize response structure
            result = {
                "blockers": int(data.get("blockers", 0) or 0),
                "importants": int(data.get("importants", 0) or 0),
                "suggestions": int(data.get("suggestions", 0) or 0),
                "findings": data.get("findings", []) or [],
                "summary": str(data.get("summary", "No summary provided") or "No summary provided"),
                "patches": []
            }
            
            # Handle single patch
            if isinstance(data.get("patch"), str) and data["patch"].strip():
                result["patches"].append(strip_fences(data["patch"]))
            
            # Handle multiple patches
            if isinstance(data.get("suggested_patches"), list):
                for patch in data["suggested_patches"]:
                    if isinstance(patch, str) and patch.strip():
                        result["patches"].append(strip_fences(patch))
            
            # Cap patch sizes to prevent oversized comments
            capped_patches = []
            for patch in result["patches"]:
                # Reasonable limit to avoid GitHub comment limits
                capped_patches.append(patch[:120000])
            result["patches"] = capped_patches
            
            return result
            
        except Exception as e:
            print(f"JSON parsing failed: {e}")
            
            # Fallback: simple pattern matching for counts
            blockers = len(re.findall(r'BLOCKER', raw_response, re.I))
            importants = len(re.findall(r'IMPORTANT', raw_response, re.I))
            suggestions = len(re.findall(r'SUGGESTION', raw_response, re.I))
            
            return {
                "blockers": blockers,
                "importants": importants,
                "suggestions": suggestions,
                "findings": [{
                    "level": "IMPORTANT",
                    "file": "",
                    "line": None,
                    "message": "LLM response parsing failed",
                    "suggestion": "Check LLM configuration and try manual review"
                }],
                "summary": "Parsing error occurred. Raw response available for manual review.",
                "patches": []
            }
    
    def run_review(self, pr_data: Dict, files_data: List[Dict], project_root: str) -> Dict:
        """
        Execute LLM review with retry logic and error handling.
        Returns structured review result.
        """
        prompt = self.create_review_prompt(pr_data, files_data, project_root)
        
        print(f"Running LLM review with model: {self.model}")
        
        # Retry logic for LLM calls
        for attempt in range(self.max_retries + 1):
            try:
                raw_response = call_llm_api(
                    prompt, 
                    model=self.model, 
                    max_tokens=self.max_tokens
                )
                
                result = self.parse_llm_response(raw_response)
                
                print(f"LLM review completed: {result['blockers']} blockers, "
                      f"{result['importants']} important, {result['suggestions']} suggestions")
                
                return result
                
            except Exception as e:
                if attempt < self.max_retries:
                    print(f"LLM attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(2)  # Brief delay before retry
                else:
                    print(f"LLM review failed after {self.max_retries + 1} attempts: {e}")
                    raise
        
        # Fallback - should not reach here due to retry logic
        return self.create_fallback_result(str(e) if 'e' in locals() else "Unknown error")
    
    def create_fallback_result(self, error_msg: str) -> Dict:
        """Create fallback result when LLM review fails completely"""
        return {
            "blockers": 0,
            "importants": 1,
            "suggestions": 0,
            "findings": [{
                "level": "IMPORTANT",
                "file": "",
                "line": None,
                "message": f"AI review failed: {error_msg[:100]}",
                "suggestion": "Manual review recommended due to AI reviewer failure"
            }],
            "patches": [],
            "summary": "Automated review unavailable - manual review required"
        }
    
    def filter_patches_under_root(self, patches: List[str], project_root: str) -> List[str]:
        """
        Filter patches to only include those modifying files under project_root.
        Uses simple criteria: must contain header +++ b/<root>/... or --- a/<root>/...
        """
        if not patches:
            return []
        
        root_prefix = project_root.rstrip("/") + "/"
        valid_patches = []
        
        for diff in patches:
            # Check for file headers under project root
            has_valid_header = (
                re.search(rf"^\+\+\+ b/{re.escape(root_prefix)}", diff, flags=re.M) or
                re.search(rf"^--- a/{re.escape(root_prefix)}", diff, flags=re.M)
            )
            
            if has_valid_header:
                valid_patches.append(diff)
        
        return valid_patches