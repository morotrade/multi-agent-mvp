# SPDX-License-Identifier: MIT
from __future__ import annotations
import json, os, time
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, Optional

LEDGER_ROOT = Path(os.getenv("LEDGER_ROOT", "logs/threads"))
LEDGER_ROOT.mkdir(parents=True, exist_ok=True)

@contextmanager
def _lock(path: Path, timeout: float = 10.0):
    """File lock minimale cross-process."""
    lock = path.with_suffix(".lock")
    start = time.time()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - start > timeout:
                raise TimeoutError(f"Lock timeout: {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try: os.remove(lock)
        except FileNotFoundError: pass

_DEFAULT_DOC: Dict[str, Any] = {
    "thread_id": None,
    "repo": None,
    "status": "triage",
    "project_root": None,
    "project_structure": [],
    "base_sha": None,
    "branch": None,
    "scope": {"must_edit": [], "must_not_edit": []},
    "reviewer": {"sticky_findings": "", "suggested_patch": None},
    "dev_fix": {
        "model": None,
        "params": {},
        "last_prompt_hash": None,
        "last_generated_patch": None,
        "preflight": {"ok": None, "stderr": ""},
        "applied_commit": None
    },
    "ci": {"pytest": None, "flake8": None, "mypy": None},
    "snapshots": {},     # metadati snapshot (non i contenuti pesanti)
    "decisions": [],
    "policy": {"allow_comment_patches": False, "acl": {"apply_patch": []}},
    "telemetry": {"tokens": {"prompt": 0, "completion": 0}, "latency_ms": 0, "cost_estimate": 0.0}
}

class ThreadLedger:
    """
    Ledger di stato per un thread (PR/Issue/Task).
    Persistenza JSON + lock file. Facile migrazione a SQLite se in futuro serve.
    """
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.path = LEDGER_ROOT / f"{thread_id}.json"

    def _ensure(self) -> None:
        if not self.path.exists():
            doc = dict(_DEFAULT_DOC)
            doc["thread_id"] = self.thread_id
            self.write(doc)

    def read(self) -> Dict[str, Any]:
        self._ensure()
        with _lock(self.path):
            return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lock(self.path):
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def update(self, **patch) -> None:
        data = self.read()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
        self.write(data)

    def set_scope(self, must_edit: list[str], must_not_edit: Optional[list[str]] = None) -> None:
        self.update(scope={"must_edit": must_edit, "must_not_edit": must_not_edit or []})

    def record_telemetry(self, prompt_tokens:int, completion_tokens:int, latency_ms:int, cost_estimate:float=0.0) -> None:
        self.update(telemetry={
            "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
            "latency_ms": latency_ms, "cost_estimate": cost_estimate
        })

    def set_project(self, project_root: str, paths: list[str]) -> None:
        self.update(project_root=project_root, project_structure=paths)

    def set_status(self, new_status: str) -> None:
        self.update(status=new_status)

    def append_decision(self, note: str, actor: str) -> None:
        data = self.read()
        data["decisions"].append({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "actor": actor,
            "note": note
        })
        self.write(data)
