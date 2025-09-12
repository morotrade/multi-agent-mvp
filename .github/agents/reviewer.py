#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Code Reviewer — PR-centric loop (PATCHED VERSION)
- Real LLM integration with robust parsing and fallbacks
- Sticky comment with anchors and stable sections
- Policy gating after side-effects
- Improved error handling and timeout management
"""
from __future__ import annotations
import json, os, re, sys, time, typing as t
import httpx
from utils import call_llm_api, get_preferred_model

BASE = "https://api.github.com"
GQL  = "https://api.github.com/graphql"
STICKY_TAG_TPL = "<!-- AI-REVIEWER:PR-{n} -->"
TIMEOUT_DEFAULT = 60

def _token()->str:
    tkn = os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not tkn:
        raise RuntimeError("Missing token (GH_CLASSIC_TOKEN/GITHUB_TOKEN)")
    return tkn

def _headers(accept=True)->dict:
    h = {"Authorization": f"Bearer {_token()}", "User-Agent":"ai-reviewer/loop"}
    if accept: h["Accept"] = "application/vnd.github+json"
    return h

def _rest(method:str, path:str, **kw):
    timeout = kw.pop('timeout', TIMEOUT_DEFAULT)
    url = f"{BASE}{path}"
    with httpx.Client(timeout=timeout) as c:
        r = c.request(method, url, headers=_headers(), **kw)
    if r.status_code>=400:
        raise RuntimeError(f"REST {method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else None

def _gql(query:str, variables:dict, timeout=TIMEOUT_DEFAULT):
    with httpx.Client(timeout=timeout) as c:
        r = c.post(GQL, headers=_headers(), json={"query":query, "variables":variables})
    if r.status_code>=400:
        raise RuntimeError(f"GraphQL HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]

def _event()->dict:
    p = os.getenv("GITHUB_EVENT_PATH")
    if p and os.path.exists(p):
        return json.load(open(p, "r", encoding="utf-8"))
    return {}

def _repo()->tuple[str,str]:
    full = os.getenv("GITHUB_REPOSITORY","")
    if "/" in full: 
        o, r = full.split("/",1); return o, r
    ev = _event()
    return ev["repository"]["owner"]["login"], ev["repository"]["name"]

def _pr_number()->int:
    if os.getenv("PR_NUMBER"):
        return int(os.getenv("PR_NUMBER"))
    ev = _event()
    pr = ev.get("pull_request") or {}
    return int(pr.get("number") or 0)

def _pr()->dict:
    owner, repo = _repo()
    num = _pr_number()
    return _rest("GET", f"/repos/{owner}/{repo}/pulls/{num}")

def _pr_files()->list[dict]:
    """Get PR files with diff content"""
    owner, repo = _repo()
    num = _pr_number()
    return _rest("GET", f"/repos/{owner}/{repo}/pulls/{num}/files")

def _pr_issue_comments()->list[dict]:
    owner, repo = _repo()
    num = _pr_number()
    return _rest("GET", f"/repos/{owner}/{repo}/issues/{num}/comments")

def _post_comment(body:str)->dict:
    owner, repo = _repo()
    num = _pr_number()
    return _rest("POST", f"/repos/{owner}/{repo}/issues/{num}/comments", json={"body":body})

def _patch_comment(comment_id:int, body:str)->dict:
    owner, repo = _repo()
    return _rest("PATCH", f"/repos/{owner}/{repo}/issues/comments/{comment_id}", json={"body":body})

def _add_labels(labels:list[str]):
    owner, repo = _repo()
    num = _pr_number()
    _rest("POST", f"/repos/{owner}/{repo}/issues/{num}/labels", json={"labels":labels})

def _remove_label(label:str):
    owner, repo = _repo()
    num = _pr_number()
    try:
        _rest("DELETE", f"/repos/{owner}/{repo}/issues/{num}/labels/{label}")
    except Exception:
        pass

def _get_pr_labels()->set[str]:
    """Get current PR labels"""
    owner, repo = _repo()
    num = _pr_number()
    try:
        labels_data = _rest("GET", f"/repos/{owner}/{repo}/issues/{num}/labels")
        return {l["name"].lower() for l in labels_data}
    except Exception:
        return set()

def _policy_from_labels()->str:
    labels = _get_pr_labels()
    if "policy:strict" in labels: return "strict"
    if "policy:lenient" in labels: return "lenient"
    return "essential-only"

def _create_review_prompt(pr_data: dict, files_data: list[dict]) -> str:
    """Create standardized prompt for LLM review"""
    title = pr_data.get("title", "")
    body = pr_data.get("body", "")
    
    # Collect diff content
    diff_sections = []
    for file_data in files_data:
        filename = file_data.get("filename", "")
        patch = file_data.get("patch", "")
        if patch:
            diff_sections.append(f"=== {filename} ===\n{patch}")
    
    diff_content = "\n\n".join(diff_sections) if diff_sections else "No changes detected"
    
    prompt = f"""# AI Code Reviewer Task

You are reviewing a Pull Request. Analyze the code changes and provide feedback in JSON format.

## PR Details
Title: {title}
Description: {body}

## Code Changes
{diff_content[:50000]}  # Truncate if too long

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
  "summary": "Brief overall assessment"
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
"""
    return prompt

def _parse_llm_response(raw_response: str) -> dict:
    """Parse LLM response with robust fallbacks"""
    try:
        # Try to extract JSON block
        json_match = re.search(r'```json\s*(.*?)\s*```', raw_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try raw JSON
            json_str = raw_response.strip()
        
        data = json.loads(json_str)
        
        # Validate and normalize
        result = {
            "blockers": int(data.get("blockers", 0)),
            "importants": int(data.get("importants", 0)),
            "suggestions": int(data.get("suggestions", 0)),
            "findings": data.get("findings", []),
            "summary": str(data.get("summary", "No summary provided"))
        }
        
        return result
        
    except Exception as e:
        print(f"⚠️ JSON parsing failed: {e}")
        # Fallback: extract counts heuristically
        blockers = len(re.findall(r'BLOCKER', raw_response, re.I))
        importants = len(re.findall(r'IMPORTANT', raw_response, re.I))
        suggestions = len(re.findall(r'SUGGESTION', raw_response, re.I))
        
        return {
            "blockers": blockers,
            "importants": importants, 
            "suggestions": suggestions,
            "findings": [{"level": "IMPORTANT", "file": "", "line": None, 
                         "message": "LLM response parsing failed", 
                         "suggestion": "Check LLM configuration"}],
            "summary": f"Parsing error occurred. Raw response available for manual review."
        }

def _format_findings_markdown(findings: list[dict]) -> str:
    """Format findings as markdown"""
    if not findings:
        return "_No specific issues found._"
    
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
    
    markdown_parts = []
    for level in ["BLOCKER", "IMPORTANT", "SUGGESTION"]:
        if sections[level]:
            emoji = {"BLOCKER": "🚫", "IMPORTANT": "⚠️", "SUGGESTION": "💡"}[level]
            markdown_parts.append(f"\n#### {emoji} {level}\n" + "\n".join(f"- {item}" for item in sections[level]))
    
    return "\n".join(markdown_parts)

def _sticky_comment_body(result: dict, timestamp: str = None) -> str:
    """Create sticky comment body with anchors"""
    prn = _pr_number()
    tag = STICKY_TAG_TPL.format(n=prn)
    timestamp = timestamp or time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    
    blockers = result["blockers"]
    importants = result["importants"] 
    suggestions = result["suggestions"]
    findings_md = _format_findings_markdown(result["findings"])
    summary = result["summary"]
    
    header = f"""### 🤖 AI Code Review
{tag}
<!-- reviewer:sticky:start -->

**Last Updated**: {timestamp}

#### 📊 Summary
{summary}

#### 🎯 Issue Counts
- **🚫 BLOCKER**: {blockers}
- **⚠️ IMPORTANT**: {importants}  
- **💡 SUGGESTION**: {suggestions}
"""
    
    findings_section = f"""
#### 📝 Detailed Findings
{findings_md}
"""
    
    footer = """
---
> 🔄 **Auto-Review Loop**: This comment updates automatically when you push changes to this branch.  
> 🏷️ **Labels**: `need-fix` = blockers to resolve, `ready-to-merge` = all clear!

<!-- reviewer:sticky:end -->"""
    
    body = header + findings_section + footer
    if len(body) > 65000:
        body = body[:64500] + "\n\n... (truncated by reviewer)\n" + footer
    return body

def _upsert_sticky_comment(body:str):
    """Update existing sticky comment or create new one"""
    prn = _pr_number()
    tag = STICKY_TAG_TPL.format(n=prn)
    existing = None
    
    for c in _pr_issue_comments():
        if tag in c.get("body",""):
            existing = c
            break
    
    if existing:
        _patch_comment(existing["id"], body)
        print("📝 Updated sticky comment")
    else:
        _post_comment(body)
        print("📝 Created sticky comment")

def _issue_node_id(issue_number: int) -> str:
    owner, repo = _repo()
    data = _gql("""
    query($owner:String!,$repo:String!,$num:Int!){
      repository(owner:$owner,name:$repo){
        issue(number:$num){ id }
      }
    }""", {"owner":owner,"repo":repo,"num":issue_number})
    return data["repository"]["issue"]["id"]

def _add_item_to_project(project_id: str, content_node_id: str) -> str:
    data = _gql("""
    mutation($p:ID!,$c:ID!){
      addProjectV2ItemById(input:{projectId:$p,contentId:$c}){ item{id} }
    }""", {"p":project_id,"c":content_node_id})
    return data["addProjectV2ItemById"]["item"]["id"]

def _set_project_single_select(project_id: str, item_id: str, field_id: str, option_id: str):
    _gql("""
    mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
      updateProjectV2ItemFieldValue(input:{
        projectId:$p,itemId:$i,fieldId:$f,
        value:{singleSelectOptionId:$o}
      }){ projectV2Item{id} }
    }""", {"p":project_id,"i":item_id,"f":field_id,"o":option_id}, timeout=40)

def _ensure_in_review_status(source_issue_number:int):
    """Set Project status to 'In review' with safe error handling"""
    proj = os.getenv("GH_PROJECT_ID") or os.getenv("GITHUB_PROJECT_ID")
    field = os.getenv("PROJECT_STATUS_FIELD_ID") 
    inrev = os.getenv("PROJECT_STATUS_INREVIEW_ID")
    
    if not (proj and field and inrev):
        print("ℹ️ Project integration disabled (missing env vars)")
        return
        
    try:
        node_id = _issue_node_id(source_issue_number)
        item_id = _add_item_to_project(proj, node_id)
        _set_project_single_select(proj, item_id, field, inrev)
        print("📌 Project status set to 'In review'")
    except Exception as e:
        print(f"⚠️ Project update failed (non-blocking): {e}")

def _source_issue_from_pr_body()->int|None:
    """Extract issue number from PR body 'Closes #N' patterns"""
    body = _pr().get("body") or ""
    m = re.search(r"(?:close[sd]?|fixe[sd]?|resolve[sd]?)\s+#(\d+)", body, re.I)
    return int(m.group(1)) if m else None

def _run_llm_review() -> dict:
    """Run LLM review with retry logic"""
    try:
        pr_data = _pr()
        files_data = _pr_files()
        
        prompt = _create_review_prompt(pr_data, files_data)
        model = get_preferred_model("reviewer")
        
        print(f"🤖 Running LLM review with model: {model}")
        
        # Call LLM with timeout and retry
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                raw_response = call_llm_api(prompt, model=model, max_tokens=4000)
                result = _parse_llm_response(raw_response)
                
                print(f"✅ LLM review completed: {result['blockers']} blockers, {result['importants']} important, {result['suggestions']} suggestions")
                return result
                
            except Exception as e:
                if attempt < max_retries:
                    print(f"⚠️ LLM attempt {attempt + 1} failed: {e}, retrying...")
                    time.sleep(2)
                else:
                    raise
        
    except Exception as e:
        print(f"❌ LLM review failed: {e}")
        # Fallback result
        return {
            "blockers": 0,
            "importants": 1, 
            "suggestions": 0,
            "findings": [{
                "level": "IMPORTANT",
                "file": "",
                "line": None,
                "message": f"AI review failed: {str(e)[:100]}",
                "suggestion": "Manual review recommended"
            }],
            "summary": "Automated review unavailable - manual review required"
        }

def main():
    print("🔎 Reviewer: start (patched version)")
    prn = _pr_number()
    if not prn:
        print("No PR number; exit 0")
        return 0

    # Run LLM analysis
    result = _run_llm_review()
    
    blockers = result["blockers"]
    importants = result["importants"]
    suggestions = result["suggestions"]

    # Side effects BEFORE policy gating
    
    # 1. Always update sticky comment
    sticky_body = _sticky_comment_body(result)
    _upsert_sticky_comment(sticky_body)

    # 2. Project status update (best-effort)
    try:
        src = _source_issue_from_pr_body()
        if src:
            _ensure_in_review_status(src)
    except Exception as e:
        print(f"⚠️ Project update failed: {e}")

    # 3. Apply labels based on policy
    policy = _policy_from_labels()
    must_fix = (blockers > 0) or (policy == "strict" and importants > 0)
    
    if must_fix:
        _add_labels(["need-fix"])
        _remove_label("ready-to-merge")
        print(f"🏷️ need-fix applied (policy={policy}, blockers={blockers}, importants={importants})")
    else:
        _remove_label("need-fix")
        _add_labels(["ready-to-merge"]) 
        print(f"🏷️ ready-to-merge applied (policy={policy})")

    # 4. Policy gating for exit code
    if policy == "lenient":
        print("🟢 Policy: lenient - always pass")
        return 0
    elif policy == "essential-only":
        exit_code = 1 if blockers > 0 else 0
        print(f"🟡 Policy: essential-only - exit {exit_code} (blockers={blockers})")
        return exit_code
    elif policy == "strict":
        exit_code = 1 if (blockers > 0 or importants > 0) else 0
        print(f"🔴 Policy: strict - exit {exit_code} (blockers={blockers}, importants={importants})")
        return exit_code
    
    return 0

if __name__ == "__main__":
    sys.exit(main())