# -*- coding: utf-8 -*-
"""
Issue and project parsing utilities
"""
import re
from typing import Optional, Dict, List

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+","-", text).strip("-")
    return text[:60]

def resolve_project_tag(text: str) -> Optional[str]:
    """
    Enhanced heuristic to extract project tag from issue body.
    Supported forms (case-insensitive):
      - Project: my-project
      - project-tag: alpha
      - #project(alpha) or [project:alpha]
      - Tag: alpha (as fallback, must be short slug)
    Returns a slugified string or None.
    """
    if not text or not isinstance(text, str):
        return None
    
    # Priority patterns (most specific first)
    patterns = [
        r"(?i)^\s*project\s*:\s*([A-Za-z0-9._\-\s]{1,40})\s*$",
        r"(?i)^\s*project-tag\s*:\s*([A-Za-z0-9._\-\s]{1,40})\s*$", 
        r"(?i)#project\(([A-Za-z0-9._\-\s]{1,40})\)",
        r"(?i)\[project:([A-Za-z0-9._\-\s]{1,40})\]",
        r"(?i)^\s*tag\s*:\s*([A-Za-z0-9._\-\s]{1,30})\s*$",
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.M)
        if matches:
            # Take the first match
            raw = matches[0].strip()
            if raw:
                slugified = slugify(raw)
                # Ensure it's not too short or generic
                if len(slugified) >= 2 and slugified not in ["tag", "project", "issue"]:
                    return slugified
    
    return None

def extract_requirements_from_issue(text: str) -> Dict[str, List[str]]:
    """Extract structured requirements from issue body"""
    if not text:
        return {"requirements": [], "acceptance": [], "files": [], "dependencies": []}
    
    result = {
        "requirements": [],
        "acceptance": [], 
        "files": [],
        "dependencies": []
    }
    
    # Extract acceptance criteria
    acc_patterns = [
        r"(?i)\*\*acceptance[^*]*\*\*:?\s*(.*?)(?=\n\*\*|\n#|\n---|\Z)",
        r"(?i)##?\s*acceptance[^#\n]*\n(.*?)(?=\n#|\n---|\Z)",
        r"(?i)acceptance\s*criteria[:\s]*(.*?)(?=\n\*\*|\n#|\n---|\Z)"
    ]
    
    for pattern in acc_patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            acc_text = match.group(1).strip()
            # Extract bullet points
            bullets = re.findall(r'[-*+]\s*(.+)', acc_text)
            result["acceptance"].extend(bullets)
            break
    
    # Extract file paths
    file_patterns = [
        r'`([^`]+\.[a-zA-Z]{1,4})`',  # Files in backticks
        r'(?:file|path):\s*([^\s\n]+\.[a-zA-Z]{1,4})',  # file: path.ext
    ]
    
    for pattern in file_patterns:
        matches = re.findall(pattern, text)
        result["files"].extend(matches)
    
    # Extract dependencies
    dep_patterns = [
        r"(?i)depends?\s+on[:\s]*(.+?)(?=\n|$)",
        r"(?i)requires?[:\s]*(.+?)(?=\n|$)",
        r"(?i)blocked\s+by[:\s]*(.+?)(?=\n|$)"
    ]
    
    for pattern in dep_patterns:
        matches = re.findall(pattern, text)
        result["dependencies"].extend(matches)
    
    # Clean up and deduplicate
    for key in result:
        result[key] = list(set(item.strip() for item in result[key] if item.strip()))
    
    return result

def format_issue_summary(issue_data: Dict) -> str:
    """Format issue data into a readable summary"""
    title = issue_data.get("title", "")
    body = issue_data.get("body", "")
    
    requirements = extract_requirements_from_issue(body)
    project_tag = resolve_project_tag(body)
    
    summary_parts = [f"**Title**: {title}"]
    
    if project_tag:
        summary_parts.append(f"**Project**: {project_tag}")
    
    if requirements["acceptance"]:
        acc_list = "\n".join(f"- {item}" for item in requirements["acceptance"][:5])
        summary_parts.append(f"**Acceptance Criteria**:\n{acc_list}")
    
    if requirements["files"]:
        files_list = ", ".join(f"`{f}`" for f in requirements["files"][:10])
        summary_parts.append(f"**Files**: {files_list}")
    
    if requirements["dependencies"]:
        deps_list = ", ".join(requirements["dependencies"][:3])
        summary_parts.append(f"**Dependencies**: {deps_list}")
    
    return "\n\n".join(summary_parts)