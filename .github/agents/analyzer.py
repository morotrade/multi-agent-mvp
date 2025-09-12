#!/usr/bin/env python3
import os, json, re
import httpx
from utils import (
    get_github_headers, post_issue_comment, create_issue, add_labels,
    get_issue_node_id, add_item_to_project, set_project_single_select,
    call_llm_api, get_preferred_model, resolve_project_tag, ensure_label_exists, add_labels_to_issue
)

# ---------- Env & Globals ----------
REPO = os.environ["GITHUB_REPOSITORY"]                # "owner/repo"
ISSUE_NUMBER = int(os.environ["ISSUE_NUMBER"])        # parent issue id

OWNER, REPO_NAME = REPO.split("/")

# Optional Project config (graceful fallback to 'off')
PROJECT_ID = (
    os.getenv("GITHUB_PROJECT_ID")
    or os.getenv("GH_PROJECT_ID")
    or None
)
STATUS_FIELD_ID = os.getenv("PROJECT_STATUS_FIELD_ID") or None
BACKLOG_ID = os.getenv("PROJECT_STATUS_BACKLOG_ID") or None

# ---------- Helpers ----------
def _get_issue():
    """Fetch the parent issue (title/body) from GitHub."""
    url = f"https://api.github.com/repos/{REPO}/issues/{ISSUE_NUMBER}"
    with httpx.Client(timeout=30) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r.json()

def _safe_get_issue_body():
    try:
        return (_get_issue().get("body") or "")
    except Exception:
        return ""

def load_prompt() -> str:
    path = ".github/prompts/analyzer.md"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        # Fallback compact prompt (token-friendly)
        return (
            "# Role: Senior Tech Project Planner (Analyzer)\n"
            "You analyze the parent Issue and produce a modular plan split into sprints and tasks.\n"
            "Return ONLY one fenced JSON with fields: policy, sprints[], tasks[]."
        )

def parse_llm_json(text: str) -> dict:
    """Extract a single fenced JSON block or try raw JSON; do light validation."""
    m = re.search(r"```json\s*([\s\S]+?)\s*```", text)
    if not m:
        text = text.strip()
        try:
            obj = json.loads(text)
        except Exception as e:
            raise Exception(f"Analyzer: JSON non trovato/valido ({e}).")
    else:
        try:
            obj = json.loads(m.group(1))
        except Exception as e:
            raise Exception(f"Analyzer: JSON non valido ({e}).")

    if not isinstance(obj, dict):
        raise Exception("Analyzer: JSON root deve essere un oggetto.")

    # minimal schema defaults
    obj.setdefault("policy", "essential-only")
    obj.setdefault("sprints", [])
    obj.setdefault("tasks", [])
    if not isinstance(obj["sprints"], list) or not isinstance(obj["tasks"], list):
        raise Exception("Analyzer: 'sprints' e 'tasks' devono essere liste.")
    return obj

def add_to_project_if_available(issue_number: int, status_option_id: str | None):
    """Link issue to the configured Project and optionally set Status to Backlog."""
    if not PROJECT_ID:
        return  # project integration disabled
    try:
        node_id = get_issue_node_id(OWNER, REPO_NAME, issue_number)
        item_id = add_item_to_project(PROJECT_ID, node_id)
        if STATUS_FIELD_ID and status_option_id:
            set_project_single_select(PROJECT_ID, item_id, STATUS_FIELD_ID, status_option_id)
    except Exception as e:
        post_issue_comment(
            OWNER, REPO_NAME, ISSUE_NUMBER,
            f"⚠️ Project linking fallito per #{issue_number}: `{e}`"
        )

# ---------- Main ----------
def main():
    # Ensure PROJECT_TAG is computed only after we have the issue body
    issue = _get_issue()
    title = issue.get("title") or ""
    body = issue.get("body") or ""

    # Resolve a project tag from body (optional) and apply as label on the parent
    try:
        project_tag = resolve_project_tag(body) or None
        if project_tag:
            ensure_label_exists(OWNER, REPO_NAME, project_tag, color="0E8A16", description="Project tag")
            add_labels_to_issue(OWNER, REPO_NAME, ISSUE_NUMBER, [project_tag])
            print(f"🏷️ Project tag applicato all'issue madre: {project_tag}")
    except Exception as e:
        print(f"⚠️ Project tag: {e}")

    # Announce start
    post_issue_comment(
        OWNER, REPO_NAME, ISSUE_NUMBER,
        f"🧭 Analyzer avviato su #{ISSUE_NUMBER}\n\n"
        f"Repo: {REPO}\n"
        f"Project linking: {'on' if PROJECT_ID else 'off'}\n"
        f"Model: {get_preferred_model('analyzer')}"
    )

    # Compose prompt and call LLM
    base_prompt = load_prompt()
    user_context = (
        f"[PARENT ISSUE]\n"
        f"Title: {title}\n"
        f"Body:\n"
        f"{body}\n"
    )
    prompt = f"{base_prompt}\n\n{user_context}"

    model = get_preferred_model("analyzer")
    raw = call_llm_api(prompt, model=model, max_tokens=4000)
    plan = parse_llm_json(raw)

    policy = plan.get("policy", "essential-only")
    sprints = plan.get("sprints", [])
    tasks = plan.get("tasks", [])

    # Create first sprint (optional)
    sprint_issue_num = None
    if sprints:
        s0 = sprints[0] or {}
        s_title = f"[Sprint] {s0.get('name','Sprint 1')}"
        s_body = (
            f"**Goal**: {s0.get('goal','')}\n"
            f"**Duration**: {s0.get('duration','')}\n\n"
            f"Parent: #{ISSUE_NUMBER}"
        )
        sprint = create_issue(OWNER, REPO_NAME, s_title, s_body, labels=["sprint"])
        sprint_issue_num = sprint["number"]
        post_issue_comment(OWNER, REPO_NAME, ISSUE_NUMBER, f"🗂️ Creato sprint: #{sprint_issue_num} — {s_title}")
        add_to_project_if_available(sprint_issue_num, BACKLOG_ID)

    # Create tasks
    created = []
    for i, t in enumerate(tasks, 1):
        t_title = t.get("title") or f"Task {i}"
        desc_lines = []
        if t.get("description"):
            desc_lines.append(t["description"])
        if t.get("acceptance"):
            desc_lines.append("\n**Acceptance**:\n" + "\n".join(f"- {x}" for x in t["acceptance"]))
        if t.get("paths"):
            desc_lines.append("\n**Paths**:\n" + "\n".join(f"- `{p}`" for p in t["paths"]))
        if t.get("depends_on"):
            desc_lines.append("\n**Depends on**:\n" + "\n".join(f"- {d}" for d in t["depends_on"]))

        t_body = (("\n".join(desc_lines)).strip() or f"Auto-generated task from #{ISSUE_NUMBER}")
        t_labels = list(set((t.get("labels") or []) + ["task"]))

        ti = create_issue(OWNER, REPO_NAME, t_title, t_body, labels=t_labels)
        ti_num = ti["number"]
        created.append(ti_num)
        add_to_project_if_available(ti_num, BACKLOG_ID)

    # Auto-start the FIRST task with bot:implement (dev pipeline)
    if created:
        try:
            add_labels(OWNER, REPO_NAME, created[0], ["bot:implement"])
        except Exception as e:
            post_issue_comment(
                OWNER, REPO_NAME, ISSUE_NUMBER,
                f"⚠️ Impossibile etichettare il primo task #{created[0]} con `bot:implement`: `{e}`"
            )

    post_issue_comment(
        OWNER, REPO_NAME, ISSUE_NUMBER,
        (
            "✅ Analyzer completato\n\n"
            f"Policy: {policy}\n"
            f"Sprint creati: {1 if sprint_issue_num else 0}\n"
            f"Task creati: {len(created)}\n\n"
            "Per avviare l'implementazione automatica di un task, aggiungi label `bot:implement` "
            "(il primo è già etichettato)."
        )
    )

if __name__ == "__main__":
    main()
