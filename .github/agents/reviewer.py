#!/usr/bin/env python3
import os, re, httpx
from utils import get_github_headers, call_llm_api, get_preferred_model, set_project_single_select, add_item_to_project, get_issue_node_id

REPO = os.environ["GITHUB_REPOSITORY"]
PR_NUMBER = os.environ["PR_NUMBER"]

def gh_get(url, accept=None, timeout=60):
    headers = get_github_headers()
    if accept:
        headers["Accept"] = accept
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        return r

def gh_post(url, json=None, timeout=60):
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, headers=get_github_headers(), json=json)
        r.raise_for_status()
        return r

def get_pr_info():
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"
    return gh_get(url).json()

def get_pr_diff_text():
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"
    return gh_get(url, accept="application/vnd.github.v3.diff").text

def post_comment(body: str):
    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    gh_post(url, json={"body": body})

def create_issue(title: str, body: str, labels):
    url = f"https://api.github.com/repos/{REPO}/issues"
    gh_post(url, json={"title": title, "body": body, "labels": labels})

def load_prompt(name: str) -> str:
    path = f".github/prompts/{name}.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"# Prompt {name}\nAnalizza il codice seguendo le best practices."

def detect_policy(pr_json) -> str:
    labels = [l["name"].lower() for l in pr_json.get("labels", [])]
    if "policy:strict".lower() in labels:
        return "strict"
    if "policy:lenient".lower() in labels:
        return "lenient"
    return "essential-only"

def extract_findings(analysis_text: str):
    """Estrarre liste di bullet tra le intestazioni BLOCKER / IMPORTANT / SUGGESTION."""
    def bullets_between(start_kw, end_kw=None):
        patt = r"(?:^|\n)\s*"+start_kw+r".*?\n(?P<body>[\s\S]*?)" + (r"(?:\n\s*"+end_kw+r"\b|$)" if end_kw else r"$")
        m = re.search(patt, analysis_text, flags=re.I)
        if not m:
            return []
        lines = [ln.strip() for ln in m.group("body").splitlines()]
        return [re.sub(r"^[-*\u2022]\s*", "", ln).strip() for ln in lines if ln.strip().startswith(("-", "*", "•"))]

    blockers = bullets_between(r"(?:\*\*)?BLOCKER:?")
    importants = bullets_between(r"(?:\*\*)?IMPORTANT:?", r"(?:\*\*)?SUGGESTION:?")
    # Heuristics: se dice esplicitamente none/nessuno, azzera
    if re.search(r"BLOCKER[^:\n]*:\s*(?:none|nessuno|n/a)", analysis_text, re.I):
        blockers = []
    if re.search(r"IMPORTANT[^:\n]*:\s*(?:none|nessuno|n/a)", analysis_text, re.I):
        importants = []
    return blockers, importants

def should_fail(policy: str, blockers: list, importants: list) -> bool:
    if policy == "lenient":
        return False
    if policy == "essential-only":
        return len(blockers) > 0
    if policy == "strict":
        return (len(blockers) > 0) or (len(importants) > 0)
    return False

def main():
    try:
        print("🔎 Reviewer: start")
        pr = get_pr_info()
    
        # Se usi solo env/branch:
        branch = os.environ.get("GITHUB_HEAD_REF") or ""
        pr_url = pr["html_url"]
        policy = detect_policy(pr)
        m = re.search(r"issue-(\d+)-", branch)
        issue_num = int(m.group(1)) if m else None

        project_id = os.environ.get("GITHUB_PROJECT_ID")
        status_field_id = os.environ.get("PROJECT_STATUS_FIELD_ID")
        status_inreview = os.environ.get("PROJECT_STATUS_INREVIEW_ID")

        if issue_num and project_id and status_field_id and status_inreview:
            try:
                owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
                issue_node_id = get_issue_node_id(owner, repo, issue_num)
                item_id = add_item_to_project(project_id, issue_node_id)  # safe: idempotente
                set_project_single_select(project_id, item_id, status_field_id, status_inreview)
                print(f"📌 Issue #{issue_num} impostata su 'In review'")
            except Exception as e:
                print(f"⚠️ Project linkage (review) error: {e}")

        # Log iniziale visibile in PR
        post_comment(f"🧭 **AI Reviewer avviato** su PR #{PR_NUMBER}\n\n- Branch: `{branch}`\n- Policy: `{policy}`\n- PR: {pr_url}")

        diff_text = get_pr_diff_text()
        if not diff_text or len(diff_text.strip()) < 50:
            post_comment("ℹ️ Nessun diff significativo da analizzare.")
            print("no-diff")
            return

        prompt = load_prompt("reviewer") + f"\n\n## DIFF DA ANALIZZARE:\n\n```diff\n{diff_text}\n```\n\n## ANALISI:"
        model = get_preferred_model("reviewer")
        print("call LLM…")
        analysis = call_llm_api(prompt, model=model)

        # Posta l’analisi completa
        post_comment(f"## 🤖 AI Code Review\n\n{analysis}\n\n---\n*Revisione automatica*")

        # Estrai BLOCKER/IMPORTANT
        blockers, importants = extract_findings(analysis)
        print(f"found: blockers={len(blockers)} importants={len(importants)} policy={policy}")

        # Se serve, apri Issue di fix per il Dev
        need_fix_issue = should_fail(policy, blockers, importants)
        if need_fix_issue:
            checklist = ""
            if blockers:
                checklist += "### BLOCKER\n" + "\n".join(f"- [ ] {b}" for b in blockers) + "\n"
            if policy == "strict" and importants:
                checklist += "### IMPORTANT\n" + "\n".join(f"- [ ] {i}" for i in importants) + "\n"

            body = (
                f"Fix per **PR #{PR_NUMBER}** ({pr_url})\n\n"
                f"**branch:** `{branch}`\n\n"
                f"{checklist}\n"
                f"---\n"
                f"_Issue aperta automaticamente dal Reviewer. Etichetta: `bot:implement`_"
            )
            create_issue(
                title=f"Fix findings from PR #{PR_NUMBER}",
                body=body,
                labels=["bot:implement"]
            )
            post_comment("📌 Creata Issue di fix con `bot:implement`. Il Dev Agent prenderà in carico le patch.")

        # Fallisci o passa il job secondo policy
        if need_fix_issue:
            print("fail by policy")
            raise SystemExit(1)
        else:
            print("pass by policy")

    except Exception as e:
        print(f"error: {e}")
        try:
            post_comment(f"❌ **Errore Reviewer**\n\n{e}")
        except:
            pass
        raise

if __name__ == "__main__":
    main()
