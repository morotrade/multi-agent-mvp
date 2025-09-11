#!/usr/bin/env python3
import os, json, re
import httpx
from utils import (
    get_github_headers, post_issue_comment, create_issue, add_labels,
    get_issue_node_id, add_item_to_project, set_project_single_select,
    call_llm_api, get_preferred_model
)

REPO = os.environ["GITHUB_REPOSITORY"]
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])

OWNER, REPO_NAME = REPO.split("/")

PROJECT_ID = os.environ.get("GITHUB_PROJECT_ID") or os.environ.get("GH_PROJECT_ID")
STATUS_FIELD_ID = os.environ.get("PROJECT_STATUS_FIELD_ID")
STATUS_BACKLOG_ID = os.environ.get("PROJECT_STATUS_BACKLOG_ID")
STATUS_INPROGRESS_ID = os.environ.get("PROJECT_STATUS_INPROGRESS_ID")

def get_issue() -> dict:
    url = f"https://api.github.com/repos/{REPO}/issues/{ISSUE_NUMBER}"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()

def load_prompt() -> str:
    path = ".github/prompts/analyzer.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """# Role: Senior Tech Project Planner (Analyzer)
You analyze the parent Issue and produce a modular plan split into sprints and tasks.
Return ONLY one fenced JSON with fields: policy, sprints[], tasks[]."""

def parse_llm_json(text: str) -> dict:
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if not m:
        # tenta raw json
        text = text.strip()
        try:
            return json.loads(text)
        except Exception as e:
            raise Exception(f"Analyzer: JSON non trovato/valido ({e}).")
    try:
        return json.loads(m.group(1))
    except Exception as e:
        raise Exception(f"Analyzer: JSON non valido ({e}).")

def add_to_project_if_available(issue_number: int, status_option_id: str = None):
    if not (PROJECT_ID and STATUS_FIELD_ID):
        return
    try:
        node_id = get_issue_node_id(OWNER, REPO_NAME, issue_number)
        item_id = add_item_to_project(PROJECT_ID, node_id)
        if status_option_id:
            set_project_single_select(PROJECT_ID, item_id, STATUS_FIELD_ID, status_option_id)
    except Exception as e:
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"⚠️ Project linkage error for #{issue_number}: `{e}`")

def main():
    issue = get_issue()
    title = issue["title"]
    body = issue.get("body") or ""
    post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"🧭 Analyzer avviato su #{ISSUE_NUMBER}\n\nRepo: {REPO}\nPolicy: default\nModel: {get_preferred_model('analyzer')}")

    # Prompt
    prompt = load_prompt()
    prompt += f"\n\n# PARENT ISSUE\nTitle: {title}\nBody:\n{body}\n\n"
    prompt += "Restituisci SOLO il JSON secondo lo schema indicato, senza testo extra."

    # LLM
    model = get_preferred_model("analyzer")
    raw = call_llm_api(prompt, model=model, max_tokens=4000)
    plan = parse_llm_json(raw)

    policy = (plan.get("policy") or "essential-only").strip()
    sprints = plan.get("sprints") or []
    tasks = plan.get("tasks") or []

    post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"📦 Piano generato (policy: {policy})\n\nSprints: {len(sprints)}\nTasks: {len(tasks)}")

    # Crea sprint issue (opzionale, prendiamo il primo)
    sprint_issue_num = None
    if sprints:
        s0 = sprints[0]
        s_title = f"[Sprint] {s0.get('name','Sprint 1')}"
        s_body = f"Goal: {s0.get('goal','')}\nDuration: {s0.get('duration','')}\n\nParent: #{ISSUE_NUMBER}"
        sprint = create_issue(OWNER, REPO_NAME, s_title, s_body, labels=["sprint"])
        sprint_issue_num = sprint["number"]
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"🗂️ Creato sprint: #{sprint_issue_num} — {s_title}")
        # project: set Backlog di default
        add_to_project_if_available(sprint_issue_num, STATUS_BACKLOG_ID)

    # Crea tasks
    created = []
    for i, t in enumerate(tasks, 1):
        t_title = t.get("title") or f"Task {i}"
        t_body = [
            f"Parent: #{ISSUE_NUMBER}",
        ]
        if sprint_issue_num:
            t_body.append(f"Sprint: #{sprint_issue_num}")
        if t.get("description"):
            t_body.append(f"\n{t['description']}\n")
        if t.get("paths"):
            t_body.append(f"Paths: {', '.join(t['paths'])}")
        if t.get("acceptance"):
            t_body.append("\n**Acceptance**:\n- " + "\n- ".join(t["acceptance"]))
        if t.get("depends_on"):
            t_body.append("\nDepends on: " + ", ".join(str(x) for x in t["depends_on"]))

        labels = list(set((t.get("labels") or []) + ["task"]))
        issue_task = create_issue(OWNER, REPO_NAME, t_title, "\n".join(t_body), labels=labels)
        task_num = issue_task["number"]
        created.append(task_num)

        # Aggiungi al Project e metti Backlog
        add_to_project_if_available(task_num, STATUS_BACKLOG_ID)

        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"🧩 Creato task: #{task_num} — {t_title}")

    # Auto-start del PRIMO task con bot:implement (pipeline automatizzata)
    if created:
        try:
            add_labels(OWNER, REPO_NAME, created[0], ["bot:implement"])
        except Exception as e:
            post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"⚠️ Impossibile etichettare il primo task #{created[0]} con bot:implement: `{e}`")

    post_issue_comment(
        OWNER, REPO_NAME, ISSUE_NUMBER,
        f"✅ Analyzer completato\n\nPolicy: {policy}\nSprint creati: {1 if sprint_issue_num else 0}\nTask creati: {len(created)}\n\n"
        f"Per avviare l’implementazione automatica di un task, aggiungi label `bot:implement` (il primo è già etichettato)."
    )

if __name__ == "__main__":
    main()
