#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sticky comment management for AI Reviewer
"""
import time
from typing import Dict, List, Optional

from utils.github_api import get_pr_comments, post_issue_comment, update_comment, get_repo_info


class CommentManager:
    """Manages sticky review comments with anchoring and updates"""
    
    def __init__(self, sticky_tag_template: str = "<!-- AI-REVIEWER:PR-{n} -->"):
        self.sticky_tag_template = sticky_tag_template
    
    def get_sticky_tag(self, pr_number: int) -> str:
        """Generate sticky tag for PR"""
        return self.sticky_tag_template.format(n=pr_number)
    
    def format_findings_markdown(self, findings: List[Dict]) -> str:
        """Format findings as structured markdown"""
        if not findings:
            return "_No specific issues found._"
        
        # Group findings by severity level
        sections = {"BLOCKER": [], "IMPORTANT": [], "SUGGESTION": []}
        
        for finding in findings:
            level = finding.get("level", "SUGGESTION").upper()
            if level not in sections:
                level = "SUGGESTION"
            
            file_info = finding.get("file", "")
            line_info = f":{finding['line']}" if finding.get("line") else ""
            location = f"`{file_info}{line_info}`" if file_info else "General"
            
            message = finding.get("message", "No message")
            suggestion = finding.get("suggestion", "")
            
            item = f"**{location}**: {message}"
            if suggestion:
                item += f"\n  *Suggestion*: {suggestion}"
            
            sections[level].append(item)
        
        # Build markdown sections
        markdown_parts = []
        emoji_map = {"BLOCKER": "🚫", "IMPORTANT": "⚠️", "SUGGESTION": "💡"}
        
        for level in ["BLOCKER", "IMPORTANT", "SUGGESTION"]:
            if sections[level]:
                emoji = emoji_map[level]
                header = f"\n#### {emoji} {level}\n"
                items = "\n".join(f"- {item}" for item in sections[level])
                markdown_parts.append(header + items)
        
        return "\n".join(markdown_parts)
    
    def create_sticky_comment_body(self, 
                                   pr_number: int,
                                   result: Dict, 
                                   project_root: str,
                                   filtered_patches: List[str],
                                   total_patches: int,
                                   timestamp: Optional[str] = None) -> str:
        """Create complete sticky comment body with all sections"""
        
        tag = self.get_sticky_tag(pr_number)
        timestamp = timestamp or time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        
        blockers = result["blockers"]
        importants = result["importants"]
        suggestions = result["suggestions"]
        findings_md = self.format_findings_markdown(result["findings"])
        summary = result["summary"]
        
        # Header section
        header = f"""### 🤖 AI Code Review
{tag}
<!-- reviewer:sticky:start -->

**Last Updated**: {timestamp}

#### 📂 Project Root
`{project_root}`

#### 📊 Summary
{summary}

#### 🎯 Issue Counts
- **🚫 BLOCKER**: {blockers}
- **⚠️ IMPORTANT**: {importants}  
- **💡 SUGGESTION**: {suggestions}
"""
        
        # Findings section
        findings_section = f"""
#### 🔍 Detailed Findings
{findings_md}
"""
        
        # Patches section (optional)
        patches_section = ""
        if filtered_patches:
            patch_chunks = []
            for i, diff in enumerate(filtered_patches[:3], start=1):  # Max 3 patches displayed
                # Truncate very long patches
                snippet = diff[:120000]
                patch_chunks.append(f"**Patch {i}**\n\n```diff\n{snippet}\n```")
            
            patches_md = "\n\n".join(patch_chunks)
            patch_count_note = f" (showing {len(patch_chunks)}/{total_patches})" if total_patches > 3 else ""
            
            patches_section = f"""

#### 🔧 Suggested Patches{patch_count_note}
The following unified diffs stay under the project root and can be applied by the developer:

{patches_md}"""
        elif total_patches > 0:
            # Had patches but all were filtered out
            patches_section = f"""

#### 🔧 Suggested Patches
{total_patches} patches were suggested but filtered out (outside project root `{project_root}`)."""
        
        # Footer section
        footer = """

---
> 🔄 **Auto-Review Loop**: This comment updates automatically when you push changes to this branch.  
> 🏷️ **Labels**: `need-fix` = blockers to resolve, `ready-to-merge` = all clear!

<!-- reviewer:sticky:end -->"""
        
        # Combine all sections
        full_body = header + findings_section + patches_section + footer
        
        # Ensure we don't exceed GitHub's comment size limits
        if len(full_body) > 65000:
            full_body = full_body[:64500] + "\n\n... (truncated by reviewer)\n" + footer
        
        return full_body
    
    def find_existing_sticky_comment(self, pr_number: int) -> Optional[Dict]:
        """Find existing sticky comment for this PR"""
        tag = self.get_sticky_tag(pr_number)
        
        try:
            owner, repo = get_repo_info()
            comments = get_pr_comments(owner, repo, pr_number)
            
            for comment in comments:
                if tag in comment.get("body", ""):
                    return comment
                    
        except Exception as e:
            print(f"Failed to fetch existing comments: {e}")
        
        return None
    
    def upsert_sticky_comment(self, pr_number: int, body: str) -> None:
        """Update existing sticky comment or create new one"""
        existing = self.find_existing_sticky_comment(pr_number)
        owner, repo = get_repo_info()
        
        try:
            if existing:
                update_comment(owner, repo, existing["id"], body)
                print("📝 Updated sticky comment")
            else:
                post_issue_comment(owner, repo, pr_number, body)
                print("📝 Created sticky comment")
                
        except Exception as e:
            print(f"Failed to upsert sticky comment: {e}")
            raise
    
    def create_and_post_sticky_comment(self,
                                       pr_number: int,
                                       result: Dict,
                                       project_root: str,
                                       filtered_patches: List[str],
                                       total_patches: int) -> None:
        """Create and post/update sticky comment with review results"""
        
        body = self.create_sticky_comment_body(
            pr_number=pr_number,
            result=result,
            project_root=project_root,
            filtered_patches=filtered_patches,
            total_patches=total_patches
        )
        
        self.upsert_sticky_comment(pr_number, body)
