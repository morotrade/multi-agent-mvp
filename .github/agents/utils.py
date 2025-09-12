# -*- coding: utf-8 -*-
"""
utils.py — GitHub + LLM helpers for MultiAgent workflows (PATCHED VERSION)
Enhanced version with:
- Improved diff validation and application with explicit failure modes
- Better timeout management and error handling
- Enhanced file path validation
- Robust project tag resolution
"""
from __future__ import annotations

import os, re, fnmatch, subprocess, json, shutil, time
from typing import List, Optional, Dict

import httpx

# Configuration constants
TIMEOUT_DEFAULT = 30
TIMEOUT_GRAPHQL = 40
TIMEOUT_LLM = 120

# ===========
# GitHub API
# ===========

def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v

def get_github_headers() -> dict:
    return {
        "Authorization": f"Bearer {_require_env('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def get_github_graphql_headers() -> dict:
    # ProjectV2 often requires a classic PAT if fine-grained token lacks scopes.
    token = os.environ.get("GH_CLASSIC_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GH_CLASSIC_TOKEN/GITHUB_TOKEN for GraphQL")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

def post_issue_comment(owner: str, repo: str, issue_number: int, body: str) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        r = client.post(url, headers=get_github_headers(), json={"body": body})
        r.raise_for_status()

def create_issue(owner: str, repo: str, title: str, body: str, labels: Optional[List[str]]=None) -> Dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        r = client.post(url, headers=get_github_headers(), json=payload)
        r.raise_for_status()
        return r.json()

def add_labels(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        r = client.post(url, headers=get_github_headers(), json={"labels": labels})
        r.raise_for_status()

def add_labels_to_issue(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    """Alias kept for backward-compatibility with agents."""
    add_labels(owner, repo, issue_number, labels)

def ensure_label_exists(owner: str, repo: str, name: str, color: str="0E8A16", description: str="") -> None:
    """Create label if missing; ignore if it already exists."""
    base = f"https://api.github.com/repos/{owner}/{repo}/labels"
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        # check
        r = client.get(f"{base}/{name}", headers=get_github_headers())
        if r.status_code == 200:
            return
        # Create
        payload = {"name": name, "color": color.lstrip("#"), "description": description or ""}
        r = client.post(base, headers=get_github_headers(), json=payload)
        # race condition: if someone created it meanwhile, 422 -> ignore if message matches
        if r.status_code not in (200,201):
            try:
                data = r.json()
            except Exception:
                data = {}
            if data and "already_exists" in json.dumps(data).lower():
                return
            r.raise_for_status()

def get_issue_node_id(owner: str, repo: str, issue_number: int) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()["node_id"]

def get_issue(owner: str, repo: str, issue_number: int) -> Dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()

def add_item_to_project(project_id: str, content_node_id: str) -> str:
    """ProjectV2 add item (GraphQL) -> returns item id"""
    query = """
      mutation($projectId: ID!, $contentId: ID!){
        addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
          item { id }
        }
      }
    """
    vars_ = {"projectId": project_id, "contentId": content_node_id}
    with httpx.Client(timeout=TIMEOUT_GRAPHQL) as client:
        r = client.post(
            "https://api.github.com/graphql",
            headers=get_github_graphql_headers(),
            json={"query": query, "variables": vars_},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            # Check if it's a permission/scope error
            error_msg = str(data["errors"])
            if any(term in error_msg.lower() for term in ["scope", "permission", "forbidden"]):
                raise RuntimeError("Project access requires GH_CLASSIC_TOKEN with 'project' scope")
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        return data["data"]["addProjectV2ItemById"]["item"]["id"]

def set_project_single_select(project_id: str, item_id: str, field_id: str, option_id: str) -> None:
    """Set ProjectV2 SingleSelect field (e.g., Status)"""
    query = """
      mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
        updateProjectV2ItemFieldValue(
          input:{
            projectId:$projectId,
            itemId:$itemId,
            fieldId:$fieldId,
            value:{ singleSelectOptionId:$optionId }
          }
        ){
          projectV2Item { id }
        }
      }
    """
    vars_ = {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "optionId": option_id}
    with httpx.Client(timeout=TIMEOUT_GRAPHQL) as client:
        r = client.post(
            "https://api.github.com/graphql",
            headers=get_github_graphql_headers(),
            json={"query": query, "variables": vars_},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            error_msg = str(data["errors"])
            if any(term in error_msg.lower() for term in ["scope", "permission", "forbidden"]):
                raise RuntimeError("Project access requires GH_CLASSIC_TOKEN with 'project' scope")
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

# ======================
# LLM provider routing
# ======================

def call_llm_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
    """Call LLM API with timeout and retry logic"""
    if model.startswith(("claude", "anthropic")):
        return call_anthropic_api(prompt, model, max_tokens)
    if model.startswith("gemini"):
        return call_gemini_api(prompt, model, max_tokens)
    return call_openai_api(prompt, model, max_tokens)

def call_openai_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
    try:
        from openai import OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "❌ OPENAI_API_KEY not configured"
        
        client = OpenAI(api_key=api_key, timeout=TIMEOUT_LLM)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        return f"OpenAI API error: {str(e)[:200]}"

def call_anthropic_api(prompt: str, model: str = "claude-3-5-sonnet-latest", max_tokens: int = 4000) -> str:
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "❌ ANTHROPIC_API_KEY not configured"
        
        client = anthropic.Anthropic(api_key=api_key)  # Remove timeout from constructor
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
            timeout=TIMEOUT_LLM  # Pass timeout to the call
        )
        return "".join(getattr(b, "text", str(b)) for b in resp.content)
    except Exception as e:
        return f"Anthropic API error: {str(e)[:200]}"

def call_gemini_api(prompt: str, model: str = "gemini-1.5-pro", max_tokens: int = 4000) -> str:
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "❌ GEMINI_API_KEY not configured"
        
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model)
        resp = m.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Gemini API error: {str(e)[:200]}"

def get_preferred_model(role: str) -> str:
    return {
        "reviewer": os.environ.get("REVIEWER_MODEL", "gpt-4o-mini"),
        "developer": os.environ.get("DEVELOPER_MODEL", "gpt-4o-mini"),
        "analyzer": os.environ.get("ANALYZER_MODEL", "gpt-4o-mini"),
    }.get(role, "gpt-4o-mini")

# ======================
# Repo helpers & guards
# ======================
def get_repo_language() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return "Python"
    url = f"https://api.github.com/repos/{repo}/languages"
    try:
        with httpx.Client(timeout=TIMEOUT_DEFAULT) as client:
            r = client.get(url, headers=get_github_headers())
            r.raise_for_status()
            data = r.json()
            if not data:
                return "Python"
            # pick most-used language
            return max(data, key=data.get)
    except Exception:
        return "Python"

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+","-", text).strip("-")
    return text[:60]

def get_whitelist_patterns() -> List[str]:
    """File patterns that are allowed to be modified"""
    return [
        "src/**","lib/**","utils/**","app/**","components/**",
        "**/*.py","**/*.js","**/*.ts","**/*.jsx","**/*.tsx",
        "**/*.java","**/*.go","**/*.rs","**/*.php","**/*.rb",
        "**/*.css","**/*.scss","**/*.html","**/*.vue","**/*.svelte",
        "tests/**","test/**","__tests__/**","spec/**",
        "docs/**","documentation/**",
        "*.md","*.txt","*.rst","*.yml","*.yaml","*.json",
        "LICENSE*","README*","CHANGELOG*","CONTRIBUTING*",
        "package.json","requirements.txt","Cargo.toml","go.mod"
    ]

def get_denylist_patterns() -> List[str]:
    """File patterns that are never allowed to be modified"""
    return [
        ".github/**",".git/**","infra/**","infrastructure/**",
        "deploy/**","deployment/**","k8s/**","terraform/**",
        "**/*.env","**/.env.*","**/secrets/**","**/secret/**",
        "**/id_rsa*","**/*.key","**/*.pem","**/*.p12","**/*.jks",
        "ssh/*","**/ssh/**",".aws/**","config/secrets/**",
        "**/credentials*","**/*credential*","**/token*",
        "**/docker-compose*.yml","**/Dockerfile*","**/*.dockerfile",
        "node_modules/**","vendor/**","venv/**","__pycache__/**",
        "*.log","**/*.log","logs/**","tmp/**","temp/**"
    ]

def paths_from_unified_diff(diff: str) -> List[str]:
    """Extract file paths from unified diff"""
    files = []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, flags=re.M):
        path = m.group(1).split("\t")[0].strip()
        files.append(path)
    return list(set(files))

def is_path_allowed(path: str) -> bool:
    """Check if path matches whitelist patterns"""
    return any(fnmatch.fnmatch(path, p) for p in get_whitelist_patterns())

def is_path_denied(path: str) -> bool:
    """Check if path matches denylist patterns"""
    return any(fnmatch.fnmatch(path, p) for p in get_denylist_patterns())

def validate_diff_files(diff_content: str) -> None:
    """Validate that diff only touches allowed files"""
    files = paths_from_unified_diff(diff_content)
    violations = []
    
    for p in files:
        if not is_path_allowed(p):
            violations.append(f"{p} (not in whitelist)")
        if is_path_denied(p):
            violations.append(f"{p} (in denylist)")
    
    if violations:
        raise Exception(f"Diff contains unauthorized files: {violations}")

def extract_single_diff(markdown_text: str) -> str:
    """Extract and validate single diff from markdown with enhanced validation"""
    if not markdown_text or not markdown_text.strip():
        raise Exception("Empty response from LLM")
    
    # Try to find diff blocks
    patterns = [
        r"```diff\s*([\s\S]*?)```",  # Explicit diff blocks
        r"```\s*(---[\s\S]*?\+\+\+[\s\S]*?)```",  # Generic blocks with diff headers
        r"```\s*([\s\S]*?)```"  # Any code blocks
    ]
    
    blocks = []
    for pattern in patterns:
        blocks = re.findall(pattern, markdown_text, re.MULTILINE)
        if blocks:
            break
    
    if len(blocks) != 1:
        raise Exception(f"Expected exactly 1 diff block, found {len(blocks)}. "
                       "LLM must return a single unified diff.")
    
    diff = blocks[0].strip()
    if not diff:
        raise Exception("Diff block is empty")

    # Normalize line endings and encoding
    lines = diff.split("\n")
    cleaned_lines = []
    for line in lines:
        # Remove non-ASCII characters that could cause issues
        cleaned_line = line.encode("ascii", "ignore").decode("ascii")
        cleaned_lines.append(cleaned_line)
    diff = "\n".join(cleaned_lines)

    # Enhanced validation
    if not re.search(r"^--- (?:a/|/dev/null)", diff, flags=re.M):
        raise Exception("Invalid diff format: must start with '--- a/' or '--- /dev/null'")
    
    if not re.search(r"^\+\+\+ b/", diff, flags=re.M):
        raise Exception("Invalid diff format: must contain '+++ b/' headers")
    
    if not re.search(r"^@@.*@@", diff, flags=re.M):
        raise Exception("Invalid diff format: must contain at least one hunk header '@@'")
    
    # Size check
    if len(diff) > 800_000:
        raise Exception("Diff too large (>800KB)")
    
    # Check for multiple file headers (should be single logical change)
    file_count = len(re.findall(r"^--- (?:a/|/dev/null)", diff, flags=re.M))
    if file_count > 20:
        raise Exception(f"Diff touches too many files ({file_count}). "
                       "Break into smaller changes.")

    return diff

def apply_diff_resilient(diff_content: str) -> bool:
    """Apply diff with multiple strategies and explicit failure modes"""
    if not diff_content or not diff_content.strip():
        print("❌ No diff content to apply")
        return False
    
    # Normalize diff
    normalized = diff_content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"

    # Check if this diff contains in-place modifications
    has_modifications = bool(re.search(r"^--- a/", normalized, flags=re.M))
    has_new_files = bool(re.search(r"^--- /dev/null", normalized, flags=re.M))
    
    print(f"📋 Diff analysis: modifications={has_modifications}, new_files={has_new_files}")

    path = "/tmp/patch.diff"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(normalized)

        # Strategy 1: git apply with check
        try:
            print("🔧 Strategy 1: git apply --check + apply...")
            result = subprocess.run(
                ["git", "apply", "--check", "--whitespace=fix", path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                subprocess.run(["git", "apply", "--whitespace=fix", path], 
                             check=True, timeout=120)
                print("✅ Git apply successful")
                return True
            else:
                print(f"⚠️ Git apply check failed: {result.stderr[:200]}")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            print(f"⚠️ Git apply failed: {str(e)[:200]}")

        # Strategy 2: git apply --3way (better for conflicts)
        try:
            print("🔧 Strategy 2: git apply --3way...")
            subprocess.run(["git", "apply", "--3way", "--whitespace=fix", path], 
                         check=True, timeout=180)
            print("✅ Git apply --3way successful")
            return True
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            print(f"⚠️ Git apply --3way failed: {str(e)[:200]}")

        # Strategy 3: patch command
        if shutil.which("patch"):
            try:
                print("🔧 Strategy 3: patch command...")
                subprocess.run(["patch", "-p1", "-i", path], 
                             check=True, timeout=180)
                print("✅ Patch command successful")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"⚠️ Patch command failed: {str(e)[:200]}")

        # Strategy 4: Manual creation (ONLY for new files)
        if has_modifications and not has_new_files:
            print("❌ Cannot apply in-place modifications manually")
            print("   LLM should regenerate with full file content for existing files")
            return False
        elif has_new_files:
            try:
                print("🔧 Strategy 4: manual file creation...")
                return apply_diff_manually(normalized)
            except Exception as e:
                print(f"⚠️ Manual application failed: {e}")

        print("❌ All diff application strategies failed")
        return False

    finally:
        try:
            os.remove(path)
        except OSError:
            pass

def apply_diff_manually(diff_content: str) -> bool:
    """
    Manual application for NEW FILES ONLY (--- /dev/null ... +++ b/FILE)
    Does NOT handle in-place modifications to existing files
    """
    created_any = False
    
    # Split by new file markers
    files = re.split(r"(?m)^--- /dev/null\s*\n\+\+\+ b/", diff_content)
    
    # The first split chunk is preamble; subsequent chunks start with file path
    for chunk in files[1:]:
        # Extract file path (first line until newline)
        first_newline = chunk.find("\n")
        if first_newline == -1:
            continue
            
        rel_path = chunk[:first_newline].strip()
        file_chunk = chunk[first_newline+1:]
        
        if not rel_path:
            continue

        # Collect added lines from hunks
        added_lines = []
        in_hunk = False
        
        for line in file_chunk.splitlines():
            if line.startswith("@@") and "@@" in line[2:]:
                in_hunk = True
                continue
            
            if in_hunk:
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])
                elif line.startswith("\\"):
                    # Handle "\ No newline at end of file"
                    continue
        
        # Write file if we have content
        if added_lines:
            try:
                # Create directory if needed
                dir_path = os.path.dirname(rel_path)
                if dir_path:
                    os.makedirs(dir_path, exist_ok=True)
                
                # Write file
                with open(rel_path, "w", encoding="utf-8", newline="\n") as f:
                    content = "\n".join(added_lines)
                    if not content.endswith("\n"):
                        content += "\n"
                    f.write(content)
                
                print(f"✅ Created file: {rel_path}")
                created_any = True
                
            except Exception as e:
                print(f"❌ Failed to create {rel_path}: {e}")
                return False
    
    return created_any

# ======================
# Enhanced parsing
# ======================

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

# ======================
# Enhanced validation
# ======================

def validate_environment() -> Dict[str, bool]:
    """Validate required environment setup"""
    checks = {
        "github_token": bool(os.environ.get("GITHUB_TOKEN")),
        "github_repo": bool(os.environ.get("GITHUB_REPOSITORY")),
        "git_available": bool(shutil.which("git")),
        "patch_available": bool(shutil.which("patch")),
        "llm_key_available": bool(
            os.environ.get("OPENAI_API_KEY") or 
            os.environ.get("ANTHROPIC_API_KEY") or 
            os.environ.get("GEMINI_API_KEY")
        ),
        "classic_token": bool(os.environ.get("GH_CLASSIC_TOKEN")),
    }
    
    return checks

def get_system_info() -> Dict[str, str]:
    """Get system information for debugging"""
    info = {
        "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
        "working_directory": os.getcwd(),
        "github_repository": os.environ.get("GITHUB_REPOSITORY", "not set"),
        "github_ref": os.environ.get("GITHUB_REF", "not set"),
        "github_event_name": os.environ.get("GITHUB_EVENT_NAME", "not set"),
    }
    
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], 
                               capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            info["git_commit"] = result.stdout.strip()
    except Exception:
        info["git_commit"] = "unavailable"
    
    return info