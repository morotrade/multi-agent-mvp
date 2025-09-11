#!/usr/bin/env python3
import os, json, re
import httpx
from utils import get_github_headers, call_llm_api, get_preferred_model

REPO = os.environ.get("REPO") or os.environ["GITHUB_REPOSITORY"]
OWNER, NAME = REPO.split("/")
ISSUE_NUMBER = os.environ["ISSUE_NUMBER"]
ISSUE_TITLE  = os.environ.get("ISSUE_TITLE", "")
ISSUE_BODY   = os.environ.get("ISSUE_BODY", "")

GITHUB_PROJECT_ID = os.environ.get("GITHUB_PROJECT_ID")  # Projects v2 (opzionale)
PROJECT_STATUS_FIELD_ID = os.environ.get("PROJECT_STATUS_FIELD_ID")  # opzionale
PROJECT_STATUS_BACKLOG_OPTION_ID = os.environ.get("PROJECT_STATUS_BACKLOG_OPTION_ID")  # opzionale

def log(msg: str):
    print(msg, flush=True)

def load_prompt() -> str:
    path = ".github/prompts/analyzer.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "# Analyzer\nProduce a JSON plan as specified."

def post_issue_comment(issue_number: str, body: str):
    url = f"https://api.github.com/repos/{REPO}/issues/{issue_number}/comments"
    r = httpx.post(url, headers=get_github_headers(), json={"body": body}, timeout=30)
    r.raise_for_status()
    return r.json()

def create_issue(title: str, body: str, labels=None):
    url = f"https://api.github.com/repos/{REPO}/issues"
    data = {"title": title, "body": body}
    if labels:
        data["labels"] = labels
    r = httpx.post(url, headers=get_github_headers(), json=data, timeout=30)
    r.raise_for_status()
    return r.json()

def add_issue_to_project(issue_node_id: str):
    if not GITHUB_PROJECT_ID:
        return None
    url = "https://api.github.com/graphql"
    query = """
      mutation($project:ID!, $issue:ID!) {
        addProjectV2ItemById(input: {projectId: $project, contentId: $issue}) {
          item { id }
        }
      }
    """
    variables = {"project": GITHUB_PROJECT_ID, "issue": issue_node_id}
    r = httpx.post(url, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Content-Type": "application/json"
    }, json={"query": query, "variables": variables}, timeout=30)
    r.raise_for_status()
    return r.json()

def set_project_status(item_id: str, status_field_id: str, option_id: str):
    # Setta la colonna (Status) su "Backlog" se hai gli ID
    url = "https://api.github.com/graphql"
    query = """
      mutation($project:ID!, $item:ID!, $field:ID!, $option: String!) {
        updateProjectV2ItemFieldValue(input:{
          projectId: $project,
          itemId: $item,
          fieldId: $field,
          value: { singleSelectOptionId: $option }
        }) { clientMutationId }
      }
    """
    variables = {
        "project": GITHUB_PROJECT_ID,
        "item": item_id,
        "field": status_field_id,
        "option": option_id
    }
    r = httpx.post(url, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Content-Type": "application/json"
    }, json={"query": query, "variables": variables}, timeout=30)
    r.raise_for_status()
    return r.json()

def ensure_backlog(project_add_resp):
    try:
        if PROJECT_STATUS_FIELD_ID and PROJECT_STATUS_BACKLOG_OPTION_ID and project_add_resp:
            item_id = project_add_resp["data"]["addProjectV2ItemById"]["item"]["id"]
            set_project_status(item_id, PROJECT_STATUS_FIELD_ID, PROJECT_STATUS_BACKLOG_OPTION_ID)
    except Exception as e:
        log(f"⚠️ Impossibile impostare Status=Backlog: {e}")

def main():
    log(f"🧭 Analyzer started on issue #{ISSUE_NUMBER} — {ISSUE_TITLE}")
    post_issue_comment(ISSUE_NUMBER, f"🧭 **Analyzer avviato** su #{ISSUE_NUMBER}\n\n- Repo: `{REPO}`\n- Policy: default\n- Model: `{get_preferred_model('analyzer')}`")

    # 1) Costruisci prompt
    prompt = f"{load_prompt()}\n\n---\n# Parent Issue\nTitle: {ISSUE_TITLE}\n\nBody:\n{ISSUE_BODY}\n\nReturn ONLY one fenced JSON block as specified."
    model = get_preferred_model("analyzer")
    plan_txt = call_llm_api(prompt, model=model, max_tokens=4000)

    # 2) Estrai il JSON dal fenced block
    m = re.search(r"```json\s+([\s\S]+?)\s```", plan_txt)
    if not m:
        # tenta plain json
        m2 = re.search(r"\{[\s\S]+\}\s*$", plan_txt.strip())
        if not m2:
            post_issue_comment(ISSUE_NUMBER, f"❌ Analyzer: nessun JSON valido trovato.\n\nOutput grezzo:\n```\n{plan_txt[:2000]}\n```")
            raise SystemExit(1)
        json_str = m2.group(0)
    else:
        json_str = m.group(1)

    try:
        plan = json.loads(json_str)
    except Exception as e:
        post_issue_comment(ISSUE_NUMBER, f"❌ Analyzer: JSON non valido.\n\nErrore: `{e}`\n\nEstratto:\n```\n{json_str[:2000]}\n```")
        raise

    policy = plan.get("policy", "essential-only")
    sprints = plan.get("sprints", [])
    tasks   = plan.get("tasks", [])

    post_issue_comment(ISSUE_NUMBER, f"📦 **Piano generato** (policy: `{policy}`)\n\n- Sprints: {len(sprints)}\n- Tasks: {len(tasks)}")

    # 3) Crea issue Sprint (se presenti)
    sprint_map = {}  # name -> issue number
    for sp in sprints:
        stitle = f"[Sprint] {sp.get('name','Sprint')}"
        sbody = f"**Goal:** {sp.get('goal','')}\n**Duration:** {sp.get('duration','')}\n\nParent: #{ISSUE_NUMBER}"
        sprint_issue = create_issue(stitle, sbody, labels=["sprint"])
        sprint_map[sp.get("name","Sprint")] = sprint_issue["number"]
        post_issue_comment(ISSUE_NUMBER, f"🗂️ Creato sprint: #{sprint_issue['number']} — {stitle}")

        # add to project backlog
        if GITHUB_PROJECT_ID and sprint_issue.get("node_id"):
            resp = add_issue_to_project(sprint_issue["node_id"])
            ensure_backlog(resp)

    # 4) Crea issue Task
    for t in tasks:
        ttitle = t["title"]
        desc   = t.get("description","")
        labels = t.get("labels", []) + ["task"]
        sev    = t.get("severity","important")
        est    = t.get("estimate","M")
        sprint_name = t.get("sprint")
        paths  = t.get("paths", [])
        depends_on = t.get("depends_on", [])
        acceptance = t.get("acceptance", [])
        tpolicy = t.get("policy", policy)

        links = []
        if sprint_name and sprint_name in sprint_map:
            links.append(f"**Sprint:** #{sprint_map[sprint_name]}")
        if depends_on:
            links.append("**Depends on:** " + ", ".join(depends_on))

        body = f"""**What & why**
{desc}

**Policy:** `{tpolicy}`
**Severity:** `{sev}` — **Estimate:** `{est}`

**Paths (indicative):**
{os.linesep.join(paths)}

ruby
Copia codice

**Acceptance:**
- {os.linesep.join(acceptance)}

**Parent:** #{ISSUE_NUMBER}
{os.linesep.join(links)}
"""
        task_issue = create_issue(ttitle, body, labels=labels)
        post_issue_comment(ISSUE_NUMBER, f"🧩 Creato task: #{task_issue['number']} — {ttitle}")

        # add to project backlog
        if GITHUB_PROJECT_ID and task_issue.get("node_id"):
            resp = add_issue_to_project(task_issue["node_id"])
            ensure_backlog(resp)

    # 5) Commento riassuntivo + hint su Dev
    post_issue_comment(ISSUE_NUMBER,
        "✅ **Analyzer completato**\n\n"
        f"- Policy: `{policy}`\n"
        f"- Sprint creati: {len(sprints)}\n"
        f"- Task creati: {len(tasks)}\n\n"
        "Per avviare l’implementazione automatica di un task, aggiungi label `bot:implement` alla relativa Issue.\n"
        "Il Reviewer partirà automaticamente sulle PR tramite `AI Code Reviewer`."
    )

if __name__ == "__main__":
    main()