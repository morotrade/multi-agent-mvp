
#.github/agents/dev_core/snapshots.py`
from pathlib import Path

def collect_snapshots(project_root: str, paths: list[str], *, max_files=20, char_limit=8000) -> list[tuple[str, str]]:
    root = project_root.rstrip("/")
    out: list[tuple[str,str]] = []
    for rel in paths[:max_files]:
        rel = (rel or "").strip().lstrip("./")
        if not rel or not rel.startswith(root + "/"):
            continue
        p = Path(rel)
        if p.exists() and p.is_file():
            # skip binari / file enormi
            try:
                size = p.stat().st_size
                if size > (char_limit * 8):  # euristica veloce
                    continue
            except Exception:
                pass
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if len(txt) > char_limit:
                # tronca al fine riga più vicino <= char_limit
                cut = txt.rfind("\n", 0, char_limit)
                if cut == -1:
                    cut = char_limit
                txt = txt[:cut].rstrip("\n") + "\n# ... (truncated) ...\n"
            # evita collisioni con fence markdown nel prompt
            txt = txt.replace("```", "``\u200b`")
            out.append((rel, txt))
    return out
