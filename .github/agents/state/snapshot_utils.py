# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable
import subprocess

from .snapshot_store import SnapshotStore

LogFn = Optional[Callable[[str], None]]  # es: lambda msg: ledger.append_decision(msg, actor="Analyzer")

def normalize_paths_under_root(paths: List[str], project_root: str) -> List[str]:
    """Prefix relative paths with project_root (idempotente)."""
    out: List[str] = []
    root = project_root.rstrip("/")
    seen = set()
    for p in paths or []:
        q = str(p).strip().lstrip("./")
        if not q:
            continue
        if not q.startswith(root + "/"):
            q = f"{root}/{q}"
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out

def split_existing_missing(repo_root: Path, commit: str, paths: List[str]) -> Tuple[List[str], List[str]]:
    """Divide i path tra quelli presenti in <commit> e quelli assenti (nuovi/da creare)."""
    existing, missing = [], []
    if not paths:
        return existing, missing
    for fp in paths:
        try:
            r = subprocess.run(
                ["git", "ls-tree", commit, "--", fp],
                text=True, capture_output=True, check=True, cwd=repo_root
            )
            (existing if r.stdout.strip() else missing).append(fp)
        except subprocess.CalledProcessError:
            missing.append(fp)
    return existing, missing

def safe_snapshot_existing_files(
    snap: SnapshotStore,
    paths: List[str],
    commit: str,
    *,
    on_log: LogFn = None
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Crea snapshot SOLO dei file esistenti a <commit>.
    Ritorna: (metadati_snapshot_indexati_per_path, missing_paths)
    """
    existing, missing = split_existing_missing(snap.repo_root, commit, paths)
    metas: Dict[str, Dict] = {}
    if existing:
        metas = snap.ensure_many(existing, commit=commit)
        if on_log:
            on_log(f"snapshotted {len(existing)}/{len(paths)} files @{commit[:8]}")
    if missing and on_log:
        on_log(f"{len(missing)} files to be created (no snapshot) @{commit[:8]}")
    return metas, missing
