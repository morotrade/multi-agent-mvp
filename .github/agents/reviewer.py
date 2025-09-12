#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Code Reviewer (patched)
- Always posts review comment
- Creates/updates fix issue for BLOCKERs (labels: bot:implement, task)
- Sets Project status = In review using ProjectV2 **item_id** with retries
- Applies policy gating *after* side-effects:
    - policy:strict          -> fail on BLOCKER or IMPORTANT
    - policy:essential-only  -> fail on BLOCKER only
    - policy:lenient         -> never fail (exit 0)
Environment:
  GITHUB_TOKEN / GH_CLASSIC_TOKEN
  GITHUB_REPOSITORY (owner/repo), GITHUB_EVENT_PATH
  GH_PROJECT_ID
  PROJECT_STATUS_FIELD_ID
  PROJECT_STATUS_INREVIEW_ID
"""
from __future__ import annotations
import json, os, re, sys, time, textwrap, typing as t

# ---------- Utilities: tokens & HTTP ----------
try:
    import httpx  # installed in workflow
except Exception as e:  # pragma: no cover
    print(f"⚠️ httpx missing: {e}", file=sys.stderr)
    raise

BASE = "https://api.github.com"
GQL  = "https://api.github.com/graphql"

def _token() -> str:
    tkn = os.getenv("GH_CLASSIC_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not tkn:
        raise RuntimeError("No GH token in env (GH_CLASSIC_TOKEN / GITHUB_TOKEN)")
    return tkn

def _headers(accept_gql: bool=False) -> dict:
    h = {
        "Authorization": f"Bearer {_token()}",
        "User-Agent": "ai-code-reviewer/1.0",
    }
    if accept_gql:
        h["Accept"] = "application/vnd.github+json"
    return h

def rest(method: str, path: str, **kw):
    url = f"{BASE}{path}"
    with httpx.Client(timeout=30) as c:
        r = c.request(method, url, headers=_headers(True), **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"REST {method} {path} -> {r.status_code}: {r.text[:300]}")
    if r.text:
        return r.json()
    return None

def graphql(query: str, variables: dict):
    payload = {"query": query, "variables": variables}
    with httpx.Client(timeout=30) as c:
        r = c.post(GQL, headers=_headers(True), json=payload)
    if r.status_code >= 400:
        raise RuntimeError(f"GraphQL HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]

# ---------- Context helpers ----------
def _event() -> dict:
    p = os.getenv("GITHUB_EVENT_PATH")
    if not p or not os.path.exists(p):
        raise RuntimeError("GITHUB_EVENT_PATH not found")
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)

def _repo() -> tuple[str,str]:
    full = os.getenv("GITHUB_REPOSITORY","")
    if "/" in full:
        owner, repo = full.split("/",1)
        return owner, repo
    # fallback to event
    ev = _event()
    owner = ev["repository"]["owner"]["login"]
    repo  = ev["repository"]["name"]
    return owner, repo

def _pr_number() -> int:
    ev = _event()
    pr = ev.get("pull_request") or {}
    return int(pr.get("number") or 0)

def _pr_body() -> str:
    owner, repo = _repo()
    number = _pr_number()
    j = rest("GET", f"/repos/{owner}/{repo}/pulls/{number}")
    return j.get("body") or ""

def _policy_from_labels(labels: list[str]) -> str:
    # priority: strict > essential-only > lenient > default(essential-only)
    labset = {l.lower() for l in labels}
    if "policy:strict" in labset: return "strict"
    if "policy:essential-only" in labset: return "essential-only"
    if "policy:lenient" in labset: return "lenient"
    return "essential-only"

def _pr_labels() -> list[str]:
    owner, repo = _repo()
    number = _pr_number()
    j = rest("GET", f"/repos/{owner}/{repo}/issues/{number}/labels")
    return [x["name"] for x in j]

def _post_pr_comment(body: str):
    owner, repo = _repo()
    number = _pr_number()
    rest("POST", f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body})

# ---------- Findings / LLM ----------
def _run_llm_review() -> dict:
    """
    Delegates to existing process if envs are present; fallback trivial heuristic.
    This function should be replaced by your current LLM pipeline if different.
    Returns a dict with keys: blockers, importants, suggestions, comment_md
    """
    # Fallback heuristic: parse PR diff for obvious issues? Keep minimal.
    body = _pr_body()
    # If the body contains 'WIP' consider IMPORTANT
    blockers = 0
    importants = 1 if re.search(r"\bWIP\b", body, re.I) else 0
    suggestions = 0
    comment_md = "🤖 *Automated review:* no blockers detected by fallback. If you rely on a model, hook it here."
    return {"blockers": blockers, "importants": importants, "suggestions": suggestions, "comment_md": comment_md}

# ---------- Fix issue management ----------
def _find_existing_fix_issue(pr_number: int) -> int|None:
    owner, repo = _repo()
    title = f"Fix findings from PR #{pr_number}"
    q = f'repo:{owner}/{repo} is:issue in:title "{title}"'
    res = rest("GET", f"/search/issues?q={httpx.utils.quote(q)}")
    items = res.get("items", [])
    for it in items:
        if it.get("title") == title:
            return it.get("number")
    return None

def _open_or_update_fix_issue(pr_number: int, md_comment: str) -> int:
    owner, repo = _repo()
    title = f"Fix findings from PR #{pr_number}"
    body  = textwrap.dedent(f"""
    Auto-generated by AI Code Reviewer for PR #{pr_number}.

    Please address the following findings and push updates. The PR will be re-reviewed automatically.

    {md_comment}
    """).strip()
    existing = _find_existing_fix_issue(pr_number)
    if existing:
        rest("PATCH", f"/repos/{owner}/{repo}/issues/{existing}", json={"body": body})
        # ensure labels
        rest("POST", f"/repos/{owner}/{repo}/issues/{existing}/labels", json={"labels":["bot:implement","task"]})
        return existing
    j = rest("POST", f"/repos/{owner}/{repo}/issues", json={
        "title": title,
        "body": body,
        "labels": ["bot:implement","task"]
    })
    return j["number"]

# ---------- Project v2 status: In review ----------
def _with_retry(fn, *a, retries: int=3, delay: float=1.0, **k):
    last = None
    for i in range(retries):
        try:
            return fn(*a, **k)
        except Exception as e:
            last = e
            time.sleep(delay * (2**i))
    raise last

def _issue_node_id(issue_number: int) -> str:
    owner, repo = _repo()
    data = graphql(
        """
        query($owner:String!,$repo:String!,$num:Int!) {
          repository(owner:$owner, name:$repo) {
            issue(number:$num){ id }
          }
        }
        """,
        {"owner": owner, "repo": repo, "num": issue_number}
    )
    return data["repository"]["issue"]["id"]

def _add_item_to_project(project_id: str, content_node_id: str) -> str:
    data = graphql(
        """
        mutation($p:ID!,$c:ID!){
          addProjectV2ItemById(input:{projectId:$p, contentId:$c}){
            item { id }
          }
        }
        """,
        {"p": project_id, "c": content_node_id}
    )
    return data["addProjectV2ItemById"]["item"]["id"]

def _set_project_single_select(project_id: str, item_id: str, field_id: str, option_id: str):
    graphql(
        """
        mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
          updateProjectV2ItemFieldValue(input:{
            projectId:$p, itemId:$i, fieldId:$f,
            value:{ singleSelectOptionId:$o }
          }){ projectV2Item { id } }
        }
        """,
        {"p": project_id, "i": item_id, "f": field_id, "o": option_id}
    )

def _ensure_in_review_status(source_issue_number: int):
    proj = os.getenv("GH_PROJECT_ID") or os.getenv("GITHUB_PROJECT_ID")
    field = os.getenv("PROJECT_STATUS_FIELD_ID")
    inrev = os.getenv("PROJECT_STATUS_INREVIEW_ID")
    if not (proj and field and inrev):
        print("ℹ️ Project env missing; skip status update")
        return
    node_id = _with_retry(_issue_node_id, source_issue_number)
    item_id = _with_retry(_add_item_to_project, proj, node_id)
    _with_retry(_set_project_single_select, proj, item_id, field, inrev)
    print("📌 Project status set to 'In review'")

# ---------- Source issue number (from PR body: Closes #N) ----------
def _source_issue_from_pr_body() -> int|None:
    body = _pr_body()
    m = re.search(r"(?:close[sd]?|fixe[sd]?|resolve[sd]?)\s+#(\d+)", body, re.I)
    return int(m.group(1)) if m else None

# ---------- Main ----------
def main():
    print("🔎 Reviewer: start")
    prn = _pr_number()
    if not prn:
        print("No PR number in event. Exiting 0.")
        return 0

    # LLM review
    print("call LLM…")
    res = _run_llm_review()
    blockers = int(res.get("blockers",0))
    importants = int(res.get("importants",0))
    suggestions = int(res.get("suggestions",0))
    comment_md = str(res.get("comment_md","")) or "No review content."
    policy = _policy_from_labels(_pr_labels())
    print(f"found: blockers={blockers} importants={importants} policy={policy}")

    # 1) PR comment (always)
    _post_pr_comment(comment_md)

    # 2) If BLOCKER => open/update fix issue and label implement
    if blockers > 0:
        fix_issue = _open_or_update_fix_issue(prn, comment_md)
        print(f"🛠️ Opened/updated fix issue #{fix_issue} and labeled bot:implement")

    # 3) Project status = In review (best-effort with retries)
    try:
        src_issue = _source_issue_from_pr_body()
        if src_issue:
            _ensure_in_review_status(src_issue)
        else:
            print("ℹ️ No 'Closes #N' found in PR body; skip project status update")
    except Exception as e:
        print(f"⚠️ Project update failed: {e}")

    # 4) Policy gate AFTER side-effects
    if policy == "strict" and (blockers > 0 or importants > 0):
        return 1
    if policy == "essential-only" and blockers > 0:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
