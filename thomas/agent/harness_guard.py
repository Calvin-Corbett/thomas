"""The harness runs the monolith guard for a run that has no shell.

An edit-only run (a Build pass on Thomas's own checkout, for one) cannot run
``python scripts/forge/gates/monolith_guard.py`` itself, and the rules of the
road still require the guard after code edits. The loop calls this instead and
hands the result to the check as a receipt, so the requirement is met by a
real guard run, not waived, and a failing guard still fails the run with its
findings.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

GUARD_RELATIVE = Path("scripts") / "forge" / "gates" / "monolith_guard.py"
DETAIL_LIMIT = 1200


def guard_path(repo_root: Path) -> Path:
    return Path(repo_root) / GUARD_RELATIVE


def run_monolith_guard(repo_root: Path, *, timeout: float = 180.0) -> dict[str, Any]:
    """Run the guard in ``repo_root`` and return ``{"ok", "detail", "by"}``."""
    root = Path(repo_root)
    script = guard_path(root)
    if not script.is_file():
        return {"ok": False, "detail": f"monolith guard not found at {script}", "by": "harness"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
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
    detail = output[-DETAIL_LIMIT:] if output else f"exit code {proc.returncode}"
    return {"ok": proc.returncode == 0, "detail": detail, "by": "harness"}


__all__ = ["run_monolith_guard", "guard_path", "GUARD_RELATIVE"]
