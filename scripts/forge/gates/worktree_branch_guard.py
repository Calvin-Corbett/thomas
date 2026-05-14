#!/usr/bin/env python3
"""Block edits when branch is used from the wrong local worktree path."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
DISABLE_ENV = "THOMAS_WORKTREE_BRANCH_GUARD_DISABLE"

EXPECTED_BY_BRANCH = {
    "master": r"C:\Users\corbe\Thomas",
    "release/oss-launch": r"C:\Users\corbe\thomas-oss-launch",
    "publish-clean": r"C:\Users\corbe\Thomas_publish_clean",
}


def _normalize_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/").rstrip("/")
    return text.lower()


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _branch_name() -> str:
    cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git branch detection failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def run(_argv: Sequence[str] | None = None) -> int:
    # Honour the runtime protection toggle (requires Windows auth to disable).
    if (ROOT / "runtime" / ".runtime_protection_disabled").is_file():
        print("Worktree branch guard: PASS (runtime protection disabled by human)")
        return 0
    if _truthy(os.environ.get(DISABLE_ENV)):
        print(f"Worktree branch guard: SKIP ({DISABLE_ENV}=1)")
        return 0

    if _truthy(os.environ.get("CI")):
        print("Worktree branch guard: SKIP (CI environment)")
        return 0

    try:
        branch = _branch_name()
    except Exception as exc:
        print("Worktree branch guard: FAIL")
        print(f"- {exc}")
        return 1

    expected = EXPECTED_BY_BRANCH.get(branch)
    if not expected:
        print("Worktree branch guard: PASS")
        print(f"- branch '{branch}' is not mapped; no path restriction")
        return 0

    actual_norm = _normalize_path(ROOT)
    expected_norm = _normalize_path(expected)
    if actual_norm == expected_norm:
        print("Worktree branch guard: PASS")
        print(f"- branch '{branch}' is in expected worktree path")
        return 0

    print("Worktree branch guard: FAIL")
    print(f"- branch '{branch}' must run from: {expected}")
    print(f"- current worktree path is: {ROOT}")
    print(f"- override only when intentional: set {DISABLE_ENV}=1")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
