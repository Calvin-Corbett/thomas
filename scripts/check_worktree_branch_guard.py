#!/usr/bin/env python3
"""Block edits when branch is used from the wrong local worktree path."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DISABLE_ENV = "THOMAS_WORKTREE_BRANCH_GUARD_DISABLE"

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


def _worktree_paths_by_branch() -> dict[str, str]:
    cmd = ["git", "worktree", "list", "--porcelain"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree detection failed: {proc.stderr.strip()}")

    paths: dict[str, str] = {}
    current_path = ""
    for raw in proc.stdout.splitlines():
        line = str(raw or "").strip()
        if line.startswith("worktree "):
            current_path = line.split(" ", 1)[1].strip()
            continue
        if line.startswith("branch refs/heads/") and current_path:
            branch = line.removeprefix("branch refs/heads/").strip()
            if branch:
                paths[branch] = current_path
    return paths


def run(_argv: Sequence[str] | None = None) -> int:
    # Honour the runtime protection toggle (requires Windows auth to disable).
    try:
        try:
            from scripts.runtime_protection_toggle import runtime_protection_is_disabled
        except (ImportError, ModuleNotFoundError):
            from runtime_protection_toggle import runtime_protection_is_disabled  # type: ignore
    except ImportError:
        runtime_protection_is_disabled = None  # type: ignore[assignment]
    if callable(runtime_protection_is_disabled) and runtime_protection_is_disabled(ROOT):
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

    try:
        expected = _worktree_paths_by_branch().get(branch)
    except Exception as exc:
        print("Worktree branch guard: FAIL")
        print(f"- {exc}")
        return 1
    if not expected:
        print("Worktree branch guard: PASS")
        print(f"- branch '{branch}' is not mapped by git worktree list; no path restriction")
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
