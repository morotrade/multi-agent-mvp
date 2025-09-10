import os, re, fnmatch, subprocess
from typing import List

import httpx

def get_github_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def call_llm_api(prompt: str, model: str = "gpt-4o-mini", max_tokens: int = 4000) -> str:
    # Router semplice per provider
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
            messages=[{"role":"user","content":prompt}],
            temperature=0.1,
            max_tokens=max_tokens
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
            messages=[{"role":"user","content":prompt}]
        )
        # Claude SDK restituisce una lista di content blocks
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
        "project_manager": os.environ.get("PM_MODEL", "gpt-4o-mini"),
    }.get(role, "gpt-4o-mini")

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+","-", text).strip("-")
    return text[:40]

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
    import fnmatch
    return any(fnmatch.fnmatch(path, p) for p in get_whitelist_patterns())

def is_path_denied(path: str) -> bool:
    import fnmatch
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
