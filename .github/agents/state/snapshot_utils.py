# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable
import subprocess

from .snapshot_store import SnapshotStore
from .thread_ledger import ThreadLedger

LogFn = Optional[Callable[[str], None]]


def normalize_paths_under_root(paths: List[str], project_root: str) -> List[str]:
    """Prefix dei path con project_root (idempotente) e pulizia './'."""
    out: List[str] = []
    root = project_root.rstrip("/") if project_root else ""
    seen = set()

    for p in paths or []:
        q = str(p).strip().lstrip("./")
        if not q:
            continue
        # Prefissa solo se abbiamo un root e q non è già sotto root
        if root and not q.startswith(root + "/") and q != root:
            q = f"{root}/{q}"
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def split_existing_missing(repo_root: Path, commit: str, paths: List[str]) -> Tuple[List[str], List[str]]:
    """
    Divide i path tra quelli presenti in <commit> e quelli assenti (nuovi/da creare).
    Se il commit è invalido o la repo è corrotta, solleva l'errore.
    """
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
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").lower()
            # Errori git "gravi" → interrompi
            if "unknown revision" in stderr or "not a valid object name" in stderr:
                raise
            # Altrimenti trattiamo come "file non presente a quel commit"
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
    Ritorna: (metadati_snapshot_per_path, missing_paths)
    """
    existing, missing = split_existing_missing(snap.repo_root, commit, paths)
    metas: Dict[str, Dict] = {}

    if existing:
        try:
            metas = snap.ensure_many(existing, commit=commit)
            if on_log:
                on_log(f"snapshotted {len(existing)}/{len(paths)} files @{commit[:8]}")
        except Exception as e:
            if on_log:
                on_log(f"snapshot failed: {e}")

    if missing and on_log:
        on_log(f"{len(missing)} files to be created (no snapshot) @{commit[:8]}")

    return metas, missing


def update_snapshots_after_commit(
    snap: SnapshotStore,
    ledger: ThreadLedger,
    commit: str,
    changed_files: List[str],
    context: str,
    actor: str
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Aggiorna gli snapshot nel ledger dopo un commit (gestendo anche file nuovi).
    Ritorna: (metas, missing) dove:
      - metas  = dict { path: {sha, lines, content_path} } per i file snapshottati
      - missing = lista di path non presenti al commit (nuovi/da creare)
    """
    if not changed_files:
        ledger.append_decision(f"{context}: no changed files to snapshot", actor=actor)
        return {}, []

    # Normalizza sempre (ripulisce './' e, se c'è, prefissa project_root)
    project_root = ledger.read().get("project_root", "")
    normalized_files = normalize_paths_under_root(changed_files, project_root)

    try:
        metas, missing = safe_snapshot_existing_files(
            snap, normalized_files, commit,
            on_log=lambda m: ledger.append_decision(f"{context}: {m}", actor=actor)
        )
    except Exception as e:
        ledger.append_decision(f"{context}: snapshot pre-check failed - {e}", actor=actor)
        return {}, []

    # Aggiorna snapshot nel ledger
    if metas:
        try:
            cur = ledger.read().get("snapshots", {})
            cur.update({
                p: {
                    "sha": m["sha"],
                    "lines": m["lines"],
                    "content_path": m["content_path"]
                }
                for p, m in metas.items()
            })
            ledger.update(snapshots=cur)
            ledger.append_decision(
                f"{context}: updated {len(metas)} snapshots @{commit[:8]}",
                actor=actor
            )
        except Exception as e:
            ledger.append_decision(f"{context}: snapshot ledger update failed - {e}", actor=actor)
    else:
        ledger.append_decision(f"{context}: no snapshots updated @{commit[:8]}", actor=actor)

    # Registra i file da creare
    if missing:
        try:
            to_create = set(ledger.read().get("files_to_create", []))
            to_create.update(missing)
            ledger.update(files_to_create=sorted(to_create))
            ledger.append_decision(f"{context}: {len(missing)} files marked for creation", actor=actor)
        except Exception as e:
            ledger.append_decision(f"{context}: files_to_create update failed - {e}", actor=actor)

    return metas, missing

def detect_changed_files(
    repo_root: Path,
    commit_from: str,
    commit_to: str,
    *,
    diff_text: Optional[str] = None,
) -> List[str]:
    """
    Rileva la lista di file cambiati tra due commit.
    - Se presente, usa anche 'diff_text' (regex su header 'diff --git a/... b/...').
    - Fallback/merge con 'git diff --name-only commit_from commit_to'.
    Ritorna una lista deduplicata e pulita.
    """
    paths: List[str] = []
    # 1) dal diff fornito (se disponibile)
    if diff_text and isinstance(diff_text, str):
        import re as _re
        paths.extend([
            m.group(2).strip()
            for m in _re.finditer(r"^diff --git a/(.+?) b/(.+)$", diff_text, _re.M)
        ])
    # 2) da git (autorità)
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", commit_from, commit_to],
            text=True, capture_output=True, check=True, cwd=repo_root
        ).stdout.splitlines()
        paths.extend([p.strip() for p in out if p.strip()])
    except Exception:
        pass
    # dedup + ordine di comparsa
    seen, deduped = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p); deduped.append(p)
    return deduped


def post_commit_snapshot_update(
    repo_root: Path,
    ledger: ThreadLedger,
    commit: str,
    changed_files: List[str],
    *,
    context: str,
    actor: str,
) -> Tuple[Dict[str, Dict], List[str]]:
    """
    Helper ad alto livello:
    - istanzia SnapshotStore(repo_root)
    - invoca update_snapshots_after_commit con i file passati
    """
    snap = SnapshotStore(repo_root)
    return update_snapshots_after_commit(
        snap=snap,
        ledger=ledger,
        commit=commit,
        changed_files=changed_files,
        context=context,
        actor=actor,
    )
