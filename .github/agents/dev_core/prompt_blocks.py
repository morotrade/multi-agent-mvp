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
        "- No prose outside the code fence.\n"
    )
    

def files_list_block(paths: list[str]) -> str:
    items = "\n".join(f"- {p}" for p in paths[:50])
    return f"# Files in scope\n{items}\n"

def findings_block(text: str) -> str:
    return f"# Reviewer findings / Notes\n{text}\n"

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