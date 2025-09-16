# SPDX-License-Identifier: MIT
from __future__ import annotations
from pathlib import Path
import subprocess, json, os
from typing import Dict, Optional

SNAP_ROOT = Path(os.getenv("SNAPSHOT_ROOT", "snapshots"))
SNAP_ROOT.mkdir(parents=True, exist_ok=True)
INDEX_PATH = SNAP_ROOT / "index.json"

def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True,
                          capture_output=True, check=True)
    return proc.stdout

class SnapshotStore:
    """
    Mantiene snapshot dei file del repo indicizzati per path+sha,
    salvando i contenuti su disco (sharded per sha) e un index leggero.
    """
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root)
        self.index = self._load_index()

    def _load_index(self) -> Dict:
        if INDEX_PATH.exists():
            try:
                return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"index_sha": None, "files": {}}

    def _save_index(self) -> None:
        INDEX_PATH.write_text(json.dumps(self.index, indent=2), encoding="utf-8")

    def update_index(self, commit: Optional[str] = None) -> Dict:
        head = (_git(["rev-parse", commit or "HEAD"], self.repo_root).strip())
        # Se l'index punta già a questo HEAD, non rigenerare tutto: aggiorna on-demand a file
        self.index["index_sha"] = head
        self._save_index()
        return self.index

    def ensure_file_snapshot(self, path: str, commit: Optional[str] = None) -> Dict:
        """Assicura che lo snapshot di `path` a `commit` esista su disco e in index."""
        head = (_git(["rev-parse", commit or "HEAD"], self.repo_root).strip())
        # ricava sha blob del file a head
        # git ls-tree -r <HEAD> <path> → ottieni sha; se path non in tree, alza
        try:
            line = _git(["ls-tree", "-r", head, "--", path], self.repo_root).strip()
        except subprocess.CalledProcessError as e:
            raise FileNotFoundError(f"Path not found in repo: {path}") from e
        if not line:
            raise FileNotFoundError(f"Path not found in commit {head}: {path}")

        # formato: "<mode> blob <sha>\t<path>" (senza --long, niente size)
        parts, _ = line.split("\t", 1)
        _, _, sha = parts.split(" ", 2)

        # se già in index con lo stesso sha → ok
        meta = self.index["files"].get(path)
        if meta and meta.get("sha") == sha:
            return meta

        content = _git(["show", f"{head}:{path}"], self.repo_root)
        shard = sha[:2]
        outdir = SNAP_ROOT / shard
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{sha}.{Path(path).name.replace('/', '_')}"
        if not out.exists():
            out.write_text(content, encoding="utf-8")

        meta = {
            "sha": sha,
            "lines": content.count("\n") + 1 if content else 0,
            "content_path": str(out)
        }
        self.index["files"][path] = meta
        self._save_index()
        return meta

    def get_content(self, path: str) -> str:
        meta = self.index["files"].get(path)
        if not meta:
            raise KeyError(f"Snapshot not indexed for: {path}")
        return Path(meta["content_path"]).read_text(encoding="utf-8")

    def get_meta(self, path: str) -> Dict:
        meta = self.index["files"].get(path)
        if not meta:
            raise KeyError(f"Snapshot not indexed for: {path}")
        return meta
            
    # New: snapshot multipli in batch
    def ensure_many(self, paths: list[str], commit: Optional[str] = None) -> dict[str, Dict]:
        out = {}
        for p in paths:
            out[p] = self.ensure_file_snapshot(p, commit=commit)
        return out

    # New: scansione struttura progetto
    def scan_tree(self, project_root: str, depth: Optional[int] = None) -> list[str]:
        base = (self.repo_root / project_root).resolve()
        if not base.exists():
            return []
        files = []
        max_depth = depth if depth is not None else 99
        root_parts = Path(project_root).as_posix().rstrip("/").split("/")
                
        for p in base.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self.repo_root).as_posix()
                rel_parts = rel.split("/")
                
                # profondità relativa al project_root (quanti segment oltre root)
                try:
                    # allinea l'inizio: se il path non inizia con root, salta
                    if rel_parts[:len(root_parts)] != root_parts:
                        continue
                    extra = len(rel_parts) - len(root_parts) - 1  # -1 perché il file stesso non conta come "dir"
                    if extra <= max_depth:
                        files.append(rel)
                except Exception:
                    continue
        return sorted(files)