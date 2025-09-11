#!/usr/bin/env python3
import os, re, httpx, sys
from utils import get_github_headers, get_issue_node_id, add_item_to_project, set_project_single_select

REPO = os.environ["GITHUB_REPOSITORY"]

def get_closing_issue_number_from_pr(pr):
    # Cerca "Closes #<n>" nel body
    m = re.search(r"(?i)\bcloses\s+#(\d+)\b", pr.get("body") or "")
    return int(m.group(1)) if m else None

def get_issue(owner, repo, number):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    r = httpx.get(url, headers=get_github_headers(), timeout=30)
    r.raise_for_status()
    return r.json()

def find_siblings(owner, repo, parent_number):
    # Trova issues che contengono "Parent: #<parent>"
    q = f'repo:{owner}/{repo} is:issue is:open in:body "Parent: #{parent_number}"'
    url = f"https://api.github.com/search/issues?q={httpx.utils.quote(q)}&per_page=100"
    r = httpx.get(url, headers=get_github_headers(), timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])

def main():
    owner, repo = REPO.split("/")
    pr = dict(os.environ.get("GITHUB_EVENT_PATH") and __import__("json").load(open(os.environ["GITHUB_EVENT_PATH"], "r")))
    # In Actions, meglio rifetch PR con id dall'evento
    if not pr:
        # fallback: usa API events context? per semplicità rifacciamo GET con numero PR dal env GITHUB_REF?
        print("ℹ️ Progressor: leggo PR dall’API usando GITHUB_REF.")
        ref = os.environ.get("GITHUB_REF", "")
        m = re.search(r"refs/pull/(\d+)/merge", ref)
        if not m:
            print("❌ Non trovo numero PR")
            return
        pr_num = int(m.group(1))
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
        resp = httpx.get(url, headers=get_github_headers(), timeout=30)
        resp.raise_for_status()
        pr = resp.json()

    closing_issue = get_closing_issue_number_from_pr(pr)
    if not closing_issue:
        print("ℹ️ Nessun 'Closes #<n>' nella PR, niente progress.")
        return

    issue = get_issue(owner, repo, closing_issue)
    m = re.search(r"(?im)^Parent:\s*#(\d+)\b", issue.get("body") or "")
    if not m:
        print("ℹ️ Nessun Parent nel body, niente progress.")
        return

    parent = int(m.group(1))
    siblings = find_siblings(owner, repo, parent)
    if not siblings:
        print(f"ℹ️ Nessun task fratello aperto per Parent #{parent}.")
        return

    # Scegli il “prossimo”: quello con numero più basso, o ordinamento semplice
    candidates = sorted((it for it in siblings if it["number"] != closing_issue), key=lambda x: x["number"])
    if not candidates:
        print("ℹ️ Nessun prossimo task da avviare.")
        return

    next_issue_num = candidates[0]["number"]
    print(f"▶️ Avvio prossimo task: #{next_issue_num}")

    # Aggiungi label bot:implement
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{next_issue_num}"
    rget = httpx.get(url, headers=get_github_headers(), timeout=30); rget.raise_for_status()
    labels = set([l["name"] for l in rget.json().get("labels", [])])
    labels.add("bot:implement")
    httpx.patch(url, headers=get_github_headers(), json={"labels": list(labels)}, timeout=30).raise_for_status()

    # Sposta a In progress sul Project (se configurato)
    project_id           = os.environ.get("GITHUB_PROJECT_ID")
    status_field_id      = os.environ.get("PROJECT_STATUS_FIELD_ID")
    status_inprogress_id = os.environ.get("PROJECT_STATUS_INPROGRESS_ID")
    if project_id and status_field_id and status_inprogress_id:
        try:
            node_id = get_issue_node_id(owner, repo, next_issue_num)
            item_id = add_item_to_project(project_id, node_id)  # idempotente
            set_project_single_select(project_id, item_id, status_field_id, status_inprogress_id)
            print(f"📌 Task #{next_issue_num} → In progress nel Project")
        except Exception as e:
            print(f"⚠️ Project update fallito: {e}")

if __name__ == "__main__":
    main()
