# -*- coding: utf-8 -*-
"""
utils.py — GitHub + LLM helpers for MultiAgent workflows
Hardened version: adds missing functions, completes patch apply fallback,
and improves error handling / token routing for Projects v2 GraphQL.
"""
from __future__ import annotations

import os, re, fnmatch, subprocess, json, shutil, time
from typing import List, Optional, Dict

import httpx

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
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=get_github_headers(), json={"body": body})
        r.raise_for_status()

def create_issue(owner: str, repo: str, title: str, body: str, labels: Optional[List[str]]=None) -> Dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=get_github_headers(), json=payload)
        r.raise_for_status()
        return r.json()

def add_labels(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
    with httpx.Client(timeout=30) as client:
        r = client.post(url, headers=get_github_headers(), json={"labels": labels})
        r.raise_for_status()

def add_labels_to_issue(owner: str, repo: str, issue_number: int, labels: List[str]) -> None:
    """Alias kept for backward-compatibility with agents."""
    add_labels(owner, repo, issue_number, labels)

def ensure_label_exists(owner: str, repo: str, name: str, color: str="0E8A16", description: str="") -> None:
    """Create label if missing; ignore if it already exists."""
    base = f"https://api.github.com/repos/{owner}/{repo}/labels"
    with httpx.Client(timeout=30) as client:
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
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()["node_id"]

def get_issue(owner: str, repo: str, issue_number: int) -> Dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    with httpx.Client(timeout=30) as client:
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
    with httpx.Client(timeout=40) as client:
        r = client.post(
            "https://api.github.com/graphql",
            headers=get_github_graphql_headers(),
            json={"query": query, "variables": vars_},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
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
    with httpx.Client(timeout=40) as client:
        r = client.post(
            "https://api.github.com/graphql",
            headers=get_github_graphql_headers(),
            json={"query": query, "variables": vars_},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

# ======================
# LLM provider routing
# ======================

def call_llm_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
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
            return "❌ OPENAI_API_KEY non configurata"
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"Errore OpenAI API: {e}"

def call_anthropic_api(prompt: str, model: str = "claude-3-5-sonnet-latest", max_tokens: int = 4000) -> str:
    try:
        import anthropic
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return "❌ ANTHROPIC_API_KEY non configurata"
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.1,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(getattr(b, "text", str(b)) for b in resp.content)
    except Exception as e:
        return f"Errore Anthropic API: {e}"

def call_gemini_api(prompt: str, model: str = "gemini-1.5-pro", max_tokens: int = 4000) -> str:
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return "❌ GEMINI_API_KEY non configurata"
        genai.configure(api_key=api_key)
        m = genai.GenerativeModel(model)
        resp = m.generate_content(prompt)
        return resp.text
    except Exception as e:
        return f"Errore Gemini API: {e}"

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
        with httpx.Client(timeout=20) as client:
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
    return [
        "src/**","lib/**","utils/**",
        "**/*.py","**/*.js","**/*.ts","**/*.java","**/*.go","**/*.rs",
        "tests/**","docs/**",
        "*.md","*.txt","LICENSE*","README*"
    ]

def get_denylist_patterns() -> List[str]:
    return [
        ".github/**",".git/**","infra/**",
        "**/*.env","**/.env.*","**/id_rsa*","**/*.key","**/*.pem",
        "ssh/*",".aws/**","config/secrets/**","**/credentials*",
        "**/docker-compose*.yml","**/Dockerfile*"
    ]

def paths_from_unified_diff(diff: str) -> List[str]:
    files = []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, flags=re.M):
        path = m.group(1).split("\t")[0].strip()
        files.append(path)
    return list(set(files))

def is_path_allowed(path: str) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in get_whitelist_patterns())

def is_path_denied(path: str) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in get_denylist_patterns())

def validate_diff_files(diff_content: str) -> None:
    files = paths_from_unified_diff(diff_content)
    violations = []
    for p in files:
        if not is_path_allowed(p):
            violations.append(f"{p} (non in whitelist)")
        if is_path_denied(p):
            violations.append(f"{p} (in denylist)")
    if violations:
        raise Exception(f"Diff contiene file non autorizzati: {violations}")

def extract_single_diff(markdown_text: str) -> str:
    """Estrae e pulisce un singolo diff da testo markdown con validazione migliorata"""
    # Prova a trovare blocchi diff specifici
    blocks = re.findall(r"```diff\s*([\s\S]*?)```", markdown_text, re.MULTILINE)
    if len(blocks) != 1:
        # fallback: blocco generico
        blocks = re.findall(r"```\s*([\s\S]*?)```", markdown_text, re.MULTILINE)
        if len(blocks) != 1:
            raise Exception(f"Atteso 1 blocco diff, trovati {len(blocks)}")
    diff = blocks[0].strip()

    # Normalizza/clean
    lines = diff.split("\n")
    cleaned_lines = []
    for line in lines:
        cleaned_lines.append(line.encode("ascii", "ignore").decode("ascii"))
    diff = "\n".join(cleaned_lines)

    # Validate unified diff
    if not re.search(r"^--- (?:a/|/dev/null)", diff, flags=re.M):
        raise Exception("Il diff deve iniziare con '--- a/' o '--- /dev/null'")
    if not re.search(r"^\+\+\+ b/", diff, flags=re.M):
        raise Exception("Il diff deve contenere '+++ b/'")
    if not re.search(r"^@@.*@@", diff, flags=re.M):
        raise Exception("Il diff deve contenere almeno un hunk header '@@'")
    if len(diff) > 800_000:
        raise Exception("Diff troppo grande (>800KB)")

    return diff

def apply_diff_resilient(diff_content: str) -> bool:
    """Applica un diff con multiple strategie di fallback"""
    normalized = diff_content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"

    path = "/tmp/patch.diff"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(normalized)

        # Strategy 1: git apply --check then apply
        try:
            print("🔧 Tentativo git apply standard...")
            result = subprocess.run(
                ["git", "apply", "--check", "--whitespace=fix", path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                subprocess.run(["git", "apply", "--whitespace=fix", path], check=True, timeout=120)
                print("✅ Git apply standard riuscito")
                return True
            else:
                print(f"⚠️ Git apply check fallito: {result.stderr}")
        except subprocess.TimeoutExpired:
            print("⚠️ Git apply timeout")
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Git apply error: {e}")

        # Strategy 2: git apply --3way
        try:
            print("🔧 Tentativo git apply --3way...")
            subprocess.run(["git", "apply", "--3way", "--whitespace=fix", path], check=True, timeout=180)
            print("✅ Git apply --3way riuscito")
            return True
        except subprocess.TimeoutExpired:
            print("⚠️ Git apply --3way timeout")
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Git apply --3way error: {e}")

        # Strategy 3: patch command
        try:
            print("🔧 Tentativo patch command...")
            subprocess.run(["patch", "-p1", "-i", path], check=True, timeout=180)
            print("✅ Patch command riuscito")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"⚠️ Patch command error: {e}")

        # Strategy 4: Manual creation for brand-new files
        try:
            print("🔧 Tentativo applicazione manuale...")
            return apply_diff_manually(normalized)
        except Exception as e:
            print(f"⚠️ Applicazione manuale fallita: {e}")

        return False
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

def apply_diff_manually(diff_content: str) -> bool:
    """
    Best-effort manual application:
    - Only supports brand-new files (--- /dev/null ... +++ b/FILE)
    - Writes added lines (+) as file content; ignores context/minus lines
    """
    created_any = False
    files = re.split(r"(?m)^--- /dev/null\s*\n\+\+\+ b/", diff_content)
    # The first split chunk is preamble; subsequent chunks start with file path
    for chunk in files[1:]:
        # Extract file path (first line until newline)
        first_newline = chunk.find("\n")
        if first_newline == -1:
            continue
        rel_path = chunk[:first_newline].strip()
        file_chunk = chunk[first_newline+1:]

        # Collect added lines from hunks
        added_lines = []
        for line in file_chunk.splitlines():
            if line.startswith("+") and not line.startswith("+++ "):
                added_lines.append(line[1:])
        # Write file
        if added_lines:
            os.makedirs(os.path.dirname(rel_path) or ".", exist_ok=True)
            with open(rel_path, "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(added_lines) + "\n")
            created_any = True
    return created_any

# ======================
# Lightweight parsing
# ======================

def resolve_project_tag(text: str) -> Optional[str]:
    """
    Heuristic: look for an explicit project tag in issue body.
    Supported forms (case-insensitive):
      - Project: my-project
      - project-tag: alpha
      - #project(alpha) or [project:alpha]
      - Tag: alpha  (as a weak fallback, but must be short slug)
    Returns a slugified string or None.
    """
    if not text:
        return None
    patterns = [
        r"(?i)^\s*project\s*:\s*([A-Za-z0-9._\- ]{1,40})\s*$",
        r"(?i)^\s*project-tag\s*:\s*([A-Za-z0-9._\- ]{1,40})\s*$",
        r"(?i)#project\(([A-Za-z0-9._\- ]{1,40})\)",
        r"(?i)\[project:([A-Za-z0-9._\- ]{1,40})\]",
        r"(?i)^\s*tag\s*:\s*([A-Za-z0-9._\- ]{1,30})\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.M)
        if m:
            raw = m.group(1).strip()
            return slugify(raw)
    return None
