"""Measure one commit's own test selection on one fixed real change, in an exported copy of that commit.

The code measured is the code that would run: each commit is exported with ``git archive`` and its own
``thomas.server.proof.selection.select`` runs in a child Python (``-I``, the copy first on its path). On 2026-10-27,
on a busy machine, b52ac43e took 28.5 s for 35 files, e51b2c7f was still running at 300 s, and b6fdcf85 took 39.9 s
for 49 files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

# Run from pythonw by a scheduled task: without this each child opened a console window over the desktop.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# The change from b6fdcf85: the check machinery and a module beside it, a change real hand-ins make.
CHANGE = ("thomas/server/precard/check.py", "thomas/server/hand_in_hold.py")
# A backstop only: the alarm that matters compares against the good commit measured the same way.
BACKSTOP_S = 600.0
SNIPPET = """
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from thomas.server.proof import selection
started = time.perf_counter()
chosen = selection.select(Path.cwd(), json.loads(sys.argv[1]))
seconds = time.perf_counter() - started
print(json.dumps({"seconds": seconds, "files": len(chosen.files), "left_out": len(getattr(chosen, "left_out", ()))}))
"""


@dataclass(frozen=True)
class Measurement:
    """One commit's selection: seconds and files, or why it gave none (``error`` is "" when it ran)."""

    commit: str
    seconds: float | None
    files: int = 0
    left_out: int = 0
    error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "seconds": self.seconds,
            "files": self.files,
            "left_out": self.left_out,
            "error": self.error,
        }


def default_python(repo: Path) -> str:
    """The repo's own interpreter, which has what the selection's package imports; else this one."""
    venv = Path(repo) / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.is_file() else sys.executable


def export(repo: Path, commit: str, root: Path) -> Path:
    """*commit*'s tracked files in ``root/<sha12>``, exported once and reused. Raises on a commit git cannot read."""
    tree = Path(root) / commit[:12]
    if commit and tree.is_dir():
        return tree
    archive = subprocess.run(
        ["git", "-C", str(repo), "archive", "--format=tar", commit],
        capture_output=True,
        check=False,
        creationflags=NO_WINDOW,
    )
    if archive.returncode or not commit:
        why = archive.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no commit named"]
        raise ValueError(why[0])
    staging = Path(root) / f".tmp-{commit[:12]}-{time.time_ns()}"
    staging.mkdir(parents=True)
    tar = Path(f"{staging}.tar")
    try:
        tar.write_bytes(archive.stdout)
        with tarfile.open(tar) as handle:
            handle.extractall(staging, filter="data")
        staging.rename(tree)  # whole or not at all: a half-written copy is never reused
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        tar.unlink(missing_ok=True)
    return tree


def measure(
    repo: Path,
    commit: str,
    root: Path,
    *,
    change: Sequence[str] = CHANGE,
    timeout_s: float = BACKSTOP_S,
    python: str | None = None,
) -> Measurement:
    """Run *commit*'s own selection for *change* in its exported copy; never raises."""
    try:
        tree = export(repo, commit, root)
    except (OSError, ValueError, tarfile.TarError) as exc:
        return Measurement(commit, None, error=f"it could not be exported: {exc}")
    try:
        done = subprocess.run(
            [python or default_python(repo), "-I", "-c", SNIPPET, json.dumps(list(change))],
            cwd=tree,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return Measurement(commit, None, error=f"it did not finish: over {timeout_s:g} s")
    lines = [line for line in (done.stdout or "").splitlines() if line.strip()]
    if done.returncode or not lines:
        last = [line for line in (done.stderr or "").splitlines() if line.strip()][-1:] or [f"exit {done.returncode}"]
        return Measurement(commit, None, error=f"it failed: {last[0][:300]}")
    try:
        found = json.loads(lines[-1])
        return Measurement(commit, float(found["seconds"]), int(found["files"]), int(found["left_out"]))
    except (ValueError, KeyError, TypeError) as exc:
        return Measurement(commit, None, error=f"it answered something unreadable: {exc}")


def prune(root: Path, keep: Iterable[str]) -> None:
    """Remove every exported copy under *root* except those of the commits in *keep*."""
    kept = {str(commit)[:12] for commit in keep}
    if not Path(root).is_dir():
        return
    for path in Path(root).iterdir():
        if path.is_dir() and path.name not in kept:
            shutil.rmtree(path, ignore_errors=True)


__all__ = ["BACKSTOP_S", "CHANGE", "Measurement", "default_python", "export", "measure", "prune"]
