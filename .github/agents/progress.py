#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, json
import httpx
from urllib.parse import quote as urlquote
from utils import (
    get_github_headers, get_issue_node_id,
    add_item_to_project, set_project_single_select
)

REPO = os.environ["GITHUB_REPOSITORY"]  # "owner/repo"


def gh_get(url, timeout=30):
    with httpx.Client(timeout=timeout) as client:
        r = client.get(url, headers=get_github_headers())
        r.raise_for_status()
        return r


def get_closing_issue_number_from_pr(pr: dict):
    """Cerca 'Closes #<n>' nel body della PR (case-insensitive)."""
    m = re.search(r"(?i)\bcloses\s+#(\d+)\b", pr.get("body") or "")
    return int(m.group(1)) if m else None


def get_issue(owner: str, repo: str, number: int) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{number}"
    return gh_get(url).json()


def find_siblings(owner: str, repo: str, parent_number: int):
    """
    Trova issues APERTE che contengono 'Parent: #<parent>' nel body.
    Usa la Search API di GitHub (max 100 risultati).
    """
    q = f'repo:{owner}/{repo} is:issue is:open in:body "Parent: #{parent_number}"'
    url = f"https://api.github.com/search/issues?q={urlquote(q)}&per_page=100"
    return gh_get(url).json().get("items", [])


def get_event_pr_from_context(owner: str, repo: str) -> dict | None:
    """
    Prova a leggere la PR dall'evento Actions.
    L'evento 'pull_request' ha la PR in data['pull_request'].
    """
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pr = data.get("pull_request")
        if isinstance(pr, dict):
            return pr
    except Exception:
        pass
    return None


def get_pr_via_env(owner: str, repo: str) -> dict | None:
    """
    Fallback 1: se Actions fornisce PR_NUMBER nell'env.
    Fallback 2: estrai da GITHUB_REF (refs/pull/<n>/merge).
    """
    pr_num = os.environ.get("PR_NUMBER")
    if pr_num and str(pr_num).isdigit():
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{int(pr_num)}"
        return gh_get(url).json()

    ref = os.environ.get("GITHUB_REF", "")
    m = re.search(r"refs/pull/(\d+)/", ref)
    if m:
        pr_num = int(m.group(1))
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}"
        return gh_get(url).json()
    return None


def main():
    owner, repo = REPO.split("/", 1)

    # 1) Recupera PR dall'evento; 2) via env; altrimenti esci
    pr = get_event_pr_from_context(owner, repo) or get_pr_via_env(owner, repo)
    if not pr:
        print("❌ Progressor: impossibile ottenere i dettagli della PR dall'evento o dall'API.")
        return

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

    # Escludi l'issue appena chiusa e scegli il "prossimo" (numero più basso)
    candidates = sorted((it for it in siblings if it.get("number") != closing_issue), key=lambda x: x["number"])
    if not candidates:
        print("ℹ️ Nessun prossimo task da avviare.")
        return

    next_issue_num = candidates[0]["number"]
    print(f"▶️ Avvio prossimo task: #{next_issue_num}")

    # Aggiungi label bot:implement al prossimo task
    issue_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{next_issue_num}"
    rget = gh_get(issue_url); data = rget.json()
    labels = {l["name"] for l in data.get("labels", [])}
    labels.add("bot:implement")
    with httpx.Client(timeout=30) as client:
        client.patch(issue_url, headers=get_github_headers(), json={"labels": list(labels)}).raise_for_status()

    # Project linking (opzionale)
    project_id           = os.environ.get("GITHUB_PROJECT_ID") or os.environ.get("GH_PROJECT_ID")
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
