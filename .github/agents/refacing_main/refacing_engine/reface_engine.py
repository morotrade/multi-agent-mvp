"""
Intelligent context building for LLM-based file refacing
"""
from pathlib import Path
from typing import List

from .keep_blocks import KEEPBlockValidator
from .utils import sha256_bytes, get_language_tag, estimate_tokens


class ContextBuilder:
    """Builds intelligent, structured context for LLM file refacing"""
    
    def __init__(self, max_reviews: int = 3, max_tokens: int = 8000, enable_keep_blocks: bool = True):
        """
        Initialize context builder.
        
        Args:
            max_reviews: Maximum number of reviews to include
            max_tokens: Maximum token budget for context
            enable_keep_blocks: Whether to include KEEP blocks instructions
        """
        self.max_reviews = max_reviews
        self.max_tokens = max_tokens
        self.enable_keep_blocks = enable_keep_blocks
    
    def build(self, file_path: str, requirements: str, reviews: List[str], 
              style_guide: str = "") -> str:
        """
        Build optimized context for full file rewrite.
        
        Args:
            file_path: Path to file being refaced
            requirements: Core requirements/changes needed
            reviews: List of review comments/feedback
            style_guide: Style and formatting guidelines
            
        Returns:
            Complete context string for LLM
        """
        # Load current file and calculate hash
        src_path = Path(file_path)
        if not src_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        src_content = src_path.read_text(encoding="utf-8")
        base_hash = sha256_bytes(src_content.encode("utf-8"))
        
        # Filter and consolidate reviews
        top_reviews = self._pick_top_reviews(reviews, self.max_reviews)
        consolidated_reviews = self._consolidate_reviews(top_reviews)
        
        # Build KEEP blocks instruction if enabled
        keep_blocks_instruction = ""
        if self.enable_keep_blocks:
            keep_blocks_instruction = self._build_keep_blocks_instruction(src_content)
        
        # Build main context
        context = self._build_main_context(
            file_path=file_path,
            src_content=src_content,
            base_hash=base_hash,
            requirements=requirements,
            consolidated_reviews=consolidated_reviews,
            style_guide=style_guide,
            keep_blocks_instruction=keep_blocks_instruction
        )
        
        # Check token budget and compress if needed
        if estimate_tokens(context) > self.max_tokens:
            context = self._compress_context(
                file_path=file_path,
                src_content=src_content,
                base_hash=base_hash,
                requirements=requirements,
                consolidated_reviews=consolidated_reviews
            )
        
        return context
    
    def _build_keep_blocks_instruction(self, src_content: str) -> str:
        """Build KEEP blocks instruction section"""
        try:
            keep_blocks = KEEPBlockValidator.extract_keep_blocks(src_content)
            if not keep_blocks:
                return ""
            
            return f"""
## KEEP BLOCKS (CRITICAL - DO NOT MODIFY)
The file contains {len(keep_blocks)} KEEP blocks that must be preserved EXACTLY:
{', '.join(keep_blocks.keys())}

NEVER modify content between # >>> KEEP:id and # <<< KEEP:id markers.
These blocks contain critical code that must remain unchanged.
"""
        except ValueError as e:
            return f"""
## KEEP BLOCKS WARNING
KEEP block syntax error detected: {e}
Please preserve any existing # >>> KEEP: and # <<< KEEP: markers exactly.
"""
    
    def _build_main_context(self, file_path: str, src_content: str, base_hash: str,
                           requirements: str, consolidated_reviews: str, style_guide: str,
                           keep_blocks_instruction: str) -> str:
        """Build the main context template"""
        language_tag = get_language_tag(file_path)
        
        return f"""# TASK: Complete File Rewrite

## FILE: {file_path}

## CURRENT STATE (AUTHORITATIVE)
```{language_tag}
{src_content}
```

## BASE HASH (CRITICAL)
{base_hash}

## REQUIREMENTS (CRITICAL PRIORITY)
{requirements}

## CONSOLIDATED FEEDBACK (HIGH PRIORITY)
{consolidated_reviews}

## STYLE CONSTRAINTS (MEDIUM PRIORITY)
{style_guide or "Follow language-specific best practices and industry standards"}
{keep_blocks_instruction}
## OUTPUT CONTRACT (MANDATORY)
Return ONLY a JSON object with these exact keys:
{{
  "file_path": "{file_path}",
  "pre_hash": "{base_hash}",
  "new_content": "<COMPLETE FILE CONTENT>",
  "changelog": ["Change 1", "Change 2", ...],
  "confidence": 0.8
}}

## CRITICAL RULES
1. new_content MUST be the COMPLETE file (not diff, not partial)
2. pre_hash MUST equal "{base_hash}" (proves you saw the right base)
3. Preserve all existing functionality unless explicitly asked to change
4. Add comprehensive docstrings and type hints where appropriate
5. Ensure syntactic correctness and follow language conventions
6. Minimize unnecessary changes to reduce diff noise
7. NEVER modify KEEP blocks if present

## VALIDATION PIPELINE
Your output will be:
1. Hash-verified against base file
2. Syntax checked with language-specific tools
3. Auto-formatted with standard formatters
4. KEEP blocks validated for exact preservation
5. Tested for basic functionality
6. Applied atomically with git commit

Generate the JSON response now:"""
    
    def _pick_top_reviews(self, reviews: List[str], limit: int) -> List[str]:
        """Select most relevant reviews by recency and specificity"""
        if not reviews:
            return []
        
        # Score reviews based on recency and content quality
        scored_reviews = []
        recent_reviews = reviews[-10:]  # Last 10 reviews max
        
        for i, review in enumerate(recent_reviews):
            if not review or not review.strip():
                continue
            
            # Score by recency (more recent = higher score)
            recency_score = (len(recent_reviews) - i) / len(recent_reviews)
            
            # Score by specificity (longer, actionable content = higher score)
            specificity_score = min(len(review.strip()) / 500, 1.0)
            
            # Bonus for actionable keywords
            actionable_keywords = [
                'fix', 'add', 'remove', 'change', 'implement', 'refactor',
                'update', 'improve', 'validate', 'check', 'ensure'
            ]
            actionable_score = sum(1 for keyword in actionable_keywords 
                                 if keyword.lower() in review.lower()) / len(actionable_keywords)
            
            total_score = (recency_score * 0.5) + (specificity_score * 0.3) + (actionable_score * 0.2)
            scored_reviews.append((review, total_score))
        
        # Sort by score and take top N
        scored_reviews.sort(key=lambda x: x[1], reverse=True)
        return [review for review, _ in scored_reviews[:limit]]
    
    def _consolidate_reviews(self, reviews: List[str]) -> str:
        """Consolidate multiple reviews into clear instructions"""
        if not reviews:
            return "No specific feedback to address."
        
        if len(reviews) == 1:
            return reviews[0].strip()
        
        # Group and prioritize feedback
        consolidated = "Multiple feedback items to address:\n\n"
        
        for i, review in enumerate(reviews, 1):
            # Clean and extract actionable items
            cleaned_review = self._clean_review_text(review)
            if cleaned_review:
                consolidated += f"{i}. {cleaned_review}\n\n"
        
        return consolidated.strip()
    
    def _clean_review_text(self, review: str) -> str:
        """Clean and extract actionable content from review"""
        if not review:
            return ""
        
        # Remove markdown artifacts and clean formatting
        cleaned = review.strip()
        
        # Remove common review prefixes
        prefixes_to_remove = [
            "Review comment:", "Feedback:", "Issue:", "Problem:", 
            "Suggestion:", "Note:", "TODO:", "FIXME:"
        ]
        
        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()
        
        # Truncate if too long but preserve meaning
        if len(cleaned) > 300:
            # Try to break at sentence boundary
            sentences = cleaned.split('. ')
            truncated = ""
            for sentence in sentences:
                if len(truncated + sentence) < 280:
                    truncated += sentence + ". "
                else:
                    break
            
            if truncated:
                cleaned = truncated.strip()
            else:
                cleaned = cleaned[:280] + "..."
        
        return cleaned
    
    def _compress_context(self, file_path: str, src_content: str, base_hash: str,
                         requirements: str, consolidated_reviews: str) -> str:
        """Compress context when it exceeds token budget"""
        language_tag = get_language_tag(file_path)
        
        # Aggressive compression - focus on essentials
        compressed_content = src_content
        if len(src_content) > 2000:
            # Show beginning and end of file with middle truncated
            lines = src_content.split('\n')
            if len(lines) > 50:
                preserved_lines = lines[:25] + ["# ... (middle truncated) ..."] + lines[-25:]
                compressed_content = '\n'.join(preserved_lines)
        
        compressed_reviews = consolidated_reviews
        if len(consolidated_reviews) > 500:
            compressed_reviews = consolidated_reviews[:500] + "...(truncated)"
        
        return f"""# TASK: Complete File Rewrite
## FILE: {file_path}
## CURRENT STATE:
```{language_tag}
{compressed_content}
```
## BASE HASH: {base_hash}
## REQUIREMENTS: {requirements}
## FEEDBACK: {compressed_reviews}
## OUTPUT: JSON with file_path, pre_hash="{base_hash}", new_content, changelog, confidence"""