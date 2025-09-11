import os, re, fnmatch, subprocess, json
from typing import List, Optional, Dict

import httpx

# ===========
# GitHub API
# ===========

def get_github_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def get_github_graphql_headers() -> dict:
    # per ProjectV2 con PAT classic se necessario
    token = os.environ.get("GH_CLASSIC_TOKEN") or os.environ.get("GITHUB_TOKEN")
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

def get_issue_node_id(owner: str, repo: str, issue_number: int) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()["node_id"]

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
        return data["data"]["addProjectV2ItemById"]["item"]["id"]

def set_project_single_select(project_id: str, item_id: str, field_id: str, option_id: str) -> None:
    """Set ProjectV2 SingleSelect field (e.g. Status)"""
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

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+","-", text).strip("-")
    return text[:60]

def get_whitelist_patterns() -> List[str]:
    return [
        "src/**","lib/**",
        "**/*.py","**/*.js","**/*.ts","**/*.java","**/*.go","**/*.rs",
        "tests/**","docs/**",
        "*.md","*.txt","LICENSE*"
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
    blocks = re.findall(r"```diff\s+([\s\S]*?)```", markdown_text)
    if len(blocks) != 1:
        raise Exception(f"Atteso 1 blocco diff, trovati {len(blocks)}")
    diff = blocks[0].strip()
    if not re.search(r"^--- a/", diff, flags=re.M) or not re.search(r"^\+\+\+ b/", diff, flags=re.M):
        raise Exception("Il diff non sembra essere in formato unified diff valido")
    if len(diff) > 800000:
        raise Exception("Diff troppo grande (>800KB)")
    return diff

def apply_diff_resilient(diff_content: str) -> bool:
    normalized = diff_content.replace("\r\n","\n").replace("\r","\n")
    path = "/tmp/patch.diff"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(normalized)
    try:
        chk = subprocess.run(["git","apply","--check","--whitespace=fix",path], capture_output=True, text=True)
        if chk.returncode == 0:
            subprocess.run(["git","apply","--whitespace=fix",path], check=True)
            return True
        print("Fallback a git apply --3way…")
        subprocess.run(["git","apply","--3way","--whitespace=fix",path], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Errore nell'applicazione del diff: {e}")
        return False
    finally:
        try: os.remove(path)
        except: pass

def get_repo_language() -> str:
    try:
        if os.path.exists("package.json"): return "JavaScript"
        if os.path.exists("go.mod"): return "Go"
        if os.path.exists("Cargo.toml"): return "Rust"
        if os.path.exists("requirements.txt") or os.path.exists("pyproject.toml"): return "Python"
        if os.path.exists("pom.xml"): return "Java"
        result = subprocess.run(["git","ls-files"], capture_output=True, text=True)
        exts = {}
        for f in result.stdout.splitlines():
            if "." in f:
                ext = f.rsplit(".",1)[-1].lower()
                exts[ext] = exts.get(ext,0)+1
        if exts:
            main = max(exts.items(), key=lambda x: x[1])[0]
            return {"py":"Python","js":"JavaScript","ts":"TypeScript","java":"Java","go":"Go","rs":"Rust"}.get(main,"Python")
        return "Python"
    except:
        return "Python"
    
def _read_project_tag_from_file() -> str | None:
    """
    Cerca il tag di progetto in:
      - issue_tagProgetto.md (riga 'ProjectTag: <valore>' o prima riga non vuota)
      - .project-tag (prima riga non vuota)
    """
    candidates = ["issue_tagProgetto.md", ".project-tag"]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read()
                m = re.search(r"(?im)^\s*ProjectTag\s*:\s*([^\s]+)\s*$", content)
                if m:
                    return m.group(1).strip()
                # fallback: prima riga non vuota
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        return line
            except:
                pass
    return None

def resolve_project_tag(issue_body: str | None = "") -> str:
    """
    Priorità:
    1) env PROJECT_TAG
    2) file issue_tagProgetto.md / .project-tag
    3) body issue riga 'ProjectTag: <valore>'
    4) fallback 'proj:default'
    """
    # 1) ENV
    env_tag = os.environ.get("PROJECT_TAG")
    if env_tag:
        return env_tag.strip()

    # 2) file
    file_tag = _read_project_tag_from_file()
    if file_tag:
        return file_tag.strip()

    # 3) issue body
    if issue_body:
        m = re.search(r"(?im)^\s*ProjectTag\s*:\s*([^\s]+)\s*$", issue_body)
        if m:
            return m.group(1).strip()

    # 4) fallback
    return "proj:default"

def ensure_label_exists(owner: str, repo: str, label: str, color: str = "BFDADC", description: str = "Project scoped tag") -> None:
    """
    Crea il label se non esiste (idempotente).
    """
    base = f"https://api.github.com/repos/{owner}/{repo}"
    headers = get_github_headers()
    with httpx.Client(timeout=30) as client:
        # GET label
        r = client.get(f"{base}/labels/{label}", headers=headers)
        if r.status_code == 200:
            return
        # CREATE
        data = {"name": label, "color": color, "description": description}
        r = client.post(f"{base}/labels", headers=headers, json=data)
        # Se esiste già o creato con successo, ok; altrimenti logga
        if r.status_code not in (200, 201, 422):
            print(f"⚠️ Impossibile creare label {label}: {r.status_code} {r.text}")

def add_labels_to_issue(owner: str, repo: str, issue_number: int, labels: list[str]) -> None:
    """
    Aggiunge label a Issue/PR (PR sono issue lato API) — idempotente.
    """
    base = f"https://api.github.com/repos/{owner}/{repo}"
    headers = get_github_headers()
    data = {"labels": labels}
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{base}/issues/{issue_number}/labels", headers=headers, json=data)
        if r.status_code not in (200, 201):
            print(f"⚠️ add_labels_to_issue: {r.status_code} {r.text}")
