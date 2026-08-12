#!/usr/bin/env python
"""Re-exec a gate under the repo .venv interpreter — kills "gate interpreter roulette".

Pre-commit hooks here run with ``language: system``, i.e. whatever ``python`` happens to
be on PATH — which is NOT necessarily the project ``.venv``. So a gate can import a
different/older ``thomas`` (or miss a dep) and give different results in a worktree, a
fresh shell, or CI than in the main checkout. That inconsistency is the bug.

This shim is the hook entry: ``python scripts/_gate_python.py <gate.py> <args...>``. It
resolves the repo ``.venv`` python and ``os.execv``'s into it so the gate ALWAYS runs
under the project interpreter. If the venv python can't be found it FAILS CLOSED — it
never silently falls back to PATH python (that fallback is exactly what we're removing).

Worktree-aware: a linked worktree has no local ``.venv`` (it lives in the main checkout),
so we also resolve the main checkout via ``git rev-parse --git-common-dir`` and look there.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _candidates(root: Path) -> list[Path]:
    return [root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"]


def _find_venv_python() -> Path | None:
    here = Path(__file__).resolve().parent.parent  # scripts/.. == this checkout root
    cands = _candidates(here)
    # A linked worktree shares the main checkout's .venv (worktrees carry no own venv).
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=here,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            common = Path(proc.stdout.strip())
            if not common.is_absolute():
                common = (here / common).resolve()
            main_root = common.parent  # <main>/.git -> <main>
            cands += _candidates(main_root)
    # Locating the main worktree is best effort: on failure the candidate
    # loop below still tries every other interpreter it knows about.
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    for c in cands:
        if c.exists():
            return c
    return None


def main() -> int:
    target = sys.argv[1:]
    if not target:
        print("usage: _gate_python.py <script.py> [args...]", file=sys.stderr)
        return 2
    venv = _find_venv_python()
    if venv is None:
        print(
            "FAIL: repo .venv python not found — gates must run under the project venv; "
            "refusing to fall back to PATH python. Create .venv (and `pre-commit install` "
            "from inside it) so gate results are consistent across checkouts and CI.",
            file=sys.stderr,
        )
        return 1
    os.execv(str(venv), [str(venv), *target])
    return 0  # unreachable (execv replaces the process)


if __name__ == "__main__":
    raise SystemExit(main())
