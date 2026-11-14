"""The harness runs the monolith guard for a run that has no shell.

An edit-only run (a Build pass on Thomas's own checkout, for one) cannot run
``python scripts/forge/gates/monolith_guard.py`` itself, and the rules of the
road still require the guard after code edits. The loop calls this instead and
hands the result to the check as a receipt, so the requirement is met by a
real guard run, not waived, and a failing guard still fails the run with its
findings.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

GUARD_RELATIVE = Path("scripts") / "forge" / "gates" / "monolith_guard.py"
# Never execute a guard found in the workspace: a worker can write that path.
# Use Thomas's own guard to judge the workspace instead.
THOMAS_GUARD = Path(__file__).resolve().parents[2] / GUARD_RELATIVE
# The guard script and the waiver file it reads. A run that changes either is
# judging itself, so the done-check fails it.
_GUARD_OWN_FILES = (GUARD_RELATIVE.as_posix(), "docs/monolith_guard_baseline.json")
DETAIL_LIMIT = 1200


def guard_path(repo_root: Path) -> Path:
    return Path(repo_root) / GUARD_RELATIVE


def _repo_relative(root: Path, raw: str) -> str:
    """A path as the guard prints it: repo-relative, forward slashes, case-folded."""
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return ""
    path = Path(text)
    if path.is_absolute():
        try:
            text = path.resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            return ""
    return text.lstrip("./").casefold()


def changed_paths(repo_root: Path) -> set[str] | None:
    """Files git sees as changed or new under ``repo_root``, or None outside git.

    Tool events name the file a write went to, but a multi-file patch does not, so
    the done-check also judges everything git reports as changed."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "-uall", "-z"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    paths: set[str] = set()
    entries = proc.stdout.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            index += 1  # a rename or copy is followed by its old path
        if "D" not in status:
            paths.add(path)
    return paths


def run_monolith_guard(
    repo_root: Path,
    *,
    timeout: float = 180.0,
    only_paths: list[str] | set[str] | None = None,
    script: Path | None = None,
) -> dict[str, Any]:
    """Run Thomas's own guard pointed at the workspace and return ``{"ok", "detail", "by"}``.

    With ``only_paths`` the run is judged on those files alone, the rule the commit
    gate already applies: a task answers for the files it changed, not for old
    oversized files it never touched. Violations elsewhere are listed as not counted.
    """
    root = Path(repo_root)
    script = THOMAS_GUARD if script is None else Path(script)
    if not script.is_file():
        return {"ok": False, "detail": f"monolith guard not found at {script}", "by": "harness"}
    command = [sys.executable, str(script), "--repo-root", str(root)]
    if only_paths is not None:
        command.append("--json")
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"monolith guard timed out after {int(timeout)}s", "by": "harness"}
    except OSError as exc:
        return {"ok": False, "detail": f"monolith guard could not start: {exc}", "by": "harness"}
    output = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part and part.strip())
    if only_paths is None:
        detail = output[-DETAIL_LIMIT:] if output else f"exit code {proc.returncode}"
        return {"ok": proc.returncode == 0, "detail": detail, "by": "harness"}
    return _judge_changed_files(root, proc, output, only_paths)


def _judge_changed_files(
    root: Path, proc: subprocess.CompletedProcess[str], output: str, only_paths: list[str] | set[str]
) -> dict[str, Any]:
    try:
        report = json.loads(proc.stdout or "")
        violations = [v for v in report.get("violations") or [] if isinstance(v, dict)]
    except (ValueError, AttributeError):
        # Unreadable output fails closed, with what the guard printed.
        detail = output[-DETAIL_LIMIT:] if output else f"exit code {proc.returncode}"
        return {"ok": False, "detail": f"monolith guard output could not be read: {detail}", "by": "harness"}
    wanted = {_repo_relative(root, p) for p in only_paths} - {""}
    # A task may not change the guard that judges it. Found live 2026-09-19: pushed by
    # the whole-repo check, a Build agent rewrote the waiver file to excuse every
    # violation and pushed expiry dates to 2027, while saying it was blocked.
    tampered = sorted(p for p in _GUARD_OWN_FILES if p.casefold() in wanted)
    if tampered:
        detail = (
            "Monolith guard FAILED: this task changed the guard's own files ("
            + ", ".join(tampered)
            + "). A task may not waive its own limits; only you can change those files."
        )
        return {"ok": False, "detail": detail, "by": "harness"}
    counted = [v for v in violations if _repo_relative(root, str(v.get("path") or "")) in wanted]
    ignored = [v for v in violations if v not in counted]

    def _line(v: dict[str, Any]) -> str:
        return f"- {v.get('path')}: {v.get('lines')} lines ({v.get('reason')})"

    if counted:
        lines = ["Monolith guard FAILED on files this task changed:", *(_line(v) for v in counted)]
    else:
        lines = [f"Monolith guard: PASS for the {len(wanted)} file(s) this task changed."]
    if ignored:
        lines.append(f"{len(ignored)} older violation(s) in files this task did not change were not counted.")
    detail = "\n".join(lines)
    return {"ok": not counted, "detail": detail[-DETAIL_LIMIT:], "by": "harness"}


__all__ = ["run_monolith_guard", "changed_paths", "guard_path", "GUARD_RELATIVE"]
