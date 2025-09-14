def constraints_block(project_root: str) -> str:
    return (
        "Constraints:\n"
        f"- Modify or create files ONLY under `{project_root}/`.\n"
        f"- The ONLY allowed exception is `{project_root}/README.md`.\n"
        "- Never touch the repository-root README.md.\n"
    )
    
def diff_format_block(project_root: str) -> str:
    return (
        "Output:\n"
        "- Return EXACTLY ONE fenced unified diff block and NOTHING ELSE.\n"
        "- The block MUST look like:\n"
        "```diff\n"
        f"--- a/<path/within/{project_root}/...>\n"
        f"+++ b/<path/within/{project_root}/...>\n"
        "@@ ...\n"
        "```\n"
        "- For **new files**, use `--- /dev/null` and `+++ b/<path>` with hunks starting at `@@ -0,0 +1,N @@`.\n"
        "- For **deleted files**, use `--- a/<path>` and `+++ /dev/null`.\n"
        "- No prose outside the code fence.\n"
    )
    

def files_list_block(paths: list[str]) -> str:
    items = "\n".join(f"- {p}" for p in paths[:50])
    return f"# Files in scope\n{items}\n"

def findings_block(text: str) -> str:
    """
    Include i findings del reviewer, rimuovendo in modo CHIRURGICO
    l'intera sezione 'Suggested Patches' (spesso contiene diff parziali
    e confonde l'LLM).
    """
    if not text:
        return ""

    import re
    lines = text.splitlines()
    out = []
    skip = False
    for i, line in enumerate(lines):
        # start: riga che contiene 'Suggested Patches' (case-insensitive)
        if not skip and re.search(r'(?i)\bSuggested Patches\b', line):
            skip = True
            continue

        if skip:
            # stop: incontriamo un "boundary" (intestazioni/sezioni successive)
            if (
                line.startswith("#")
                or line[:1] in ("🔄", "🏷", "📂", "📊", "🎯", "🔍", "🎯", "💡", "⚠")
                or re.search(r'(?i)^\s*(Auto-Review Loop|Merge info)\b', line)
            ):
                skip = False
                out.append(line)
            # altrimenti continuiamo a saltare
        else:
            out.append(line)

    cleaned = "\n".join(out).rstrip() + "\n"
    return f"# Reviewer findings / Notes\n{cleaned}"

def snapshots_block(snapshots: list[tuple[str, str]]) -> str:
    if not snapshots:
        return ""
    out = ["# Current file snapshots (read-only)"]
    for rel, content in snapshots:
        lang = "python" if rel.endswith(".py") else ""
        fence_lang = lang if lang else ""
        
        # mapping minimale estendibile
        ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
        lang_map = {
            "py": "python", "md": "markdown", "json": "json", "yml": "yaml", "yaml": "yaml",
            "js": "javascript", "ts": "typescript", "sh": "bash", "txt": ""
        }
        fence_lang = lang_map.get(ext, "")
        
        out.append(f"\n## {rel}\n```{fence_lang}\n{content}\n```\n")
    return "\n".join(out) + "\n"