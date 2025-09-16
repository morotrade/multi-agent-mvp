# SPDX-License-Identifier: MIT
from __future__ import annotations
import os, json, uuid, datetime, subprocess
from pathlib import Path
from typing import Tuple

ARTIFACTS_ROOT = Path(os.getenv("ARTIFACTS_ROOT", "logs/agent_runs"))
ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)

def _now_id() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{uuid.uuid4().hex[:8]}"

def preflight_git_apply_check(patch_text: str, repo_root: Path) -> Tuple[bool, str, str]:
    """Esegue git apply --check - sul repo. Ritorna (ok, stdout, stderr)."""
    proc = subprocess.run(
        ["git", "apply", "--check", "-"],
        input=patch_text.encode("utf-8"),
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc.returncode == 0, proc.stdout.decode("utf-8", "ignore"), proc.stderr.decode("utf-8", "ignore")

class DiffRecorder:
    """
    Registra artefatti di una run (prompt/diff/preflight) per diagnosi e audit.
    """
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or _now_id()
        self.dir = ARTIFACTS_ROOT / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def save_metadata(self, **meta) -> None:
        (self.dir / "metadata.json").write_text(json.dumps({
            "run_id": self.run_id,
            "ts_iso": datetime.datetime.now().isoformat(timespec="seconds"),
            **meta
        }, indent=2), encoding="utf-8")

    def save_text(self, name: str, text: str) -> None:
        (self.dir / name).write_text(text, encoding="utf-8")

    def record_model_raw(self, text: str) -> None:
        self.save_text("model_raw.txt", text)

    def record_payload(self, diff_text: str) -> None:
        self.save_text("payload_to_git.patch", diff_text)

    def record_preflight(self, stdout: str, stderr: str) -> None:
        self.save_text("preflight_stdout.txt", stdout)
        self.save_text("preflight_stderr.txt", stderr)


    def record_prompt(self, text: str) -> None:
        self.save_text("prompt.txt", text)

    @staticmethod
    def preflight_git_apply_threeway(patch_text: str, repo_root: Path) -> Tuple[bool, str, str]:
        """Tentativo con --3way (fallback)."""
        proc = subprocess.run(
            ["git", "apply", "--3way", "--check", "-"],
            input=patch_text.encode("utf-8"),
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return proc.returncode == 0, proc.stdout.decode("utf-8", "ignore"), proc.stderr.decode("utf-8", "ignore")