#.github/agents/dev_core/errors.py
def comment_with_llm_preview(gh, number: int, title: str, err: Exception, diffproc) -> None:
    msg = str(err) if err else "unknown error"
    sanitized = getattr(diffproc, "sanitize_error_for_comment", lambda s: s)(msg)
    preview = ""
    try:
        preview = diffproc.last_response_snippet()
    except Exception:
        pass

    body = f"❌ {title}\n\n```\n{sanitized}\n```"
    if preview:
        body += f"\n\n<details><summary>LLM raw output (truncated)</summary>\n\n```text\n{preview}\n```\n</details>"
    gh.post_comment(number, body)
