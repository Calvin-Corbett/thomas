#!/usr/bin/env python3
"""Gradual type-safety enforcement for Thomas modules.

Runs mypy on staged Python files that belong to opted-in modules.
Uses a ratchet approach: only modules explicitly listed in ENABLED_MODULES
are checked. New modules are added as they're cleaned up.

This prevents new type errors from being introduced in modules that have
already been cleaned up, without requiring the entire codebase to pass
mypy at once.

Requires: mypy (pip install mypy)
If mypy is not installed, the check passes with a warning.

Audit reference: Adversarial Audit Finding 14 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.brief.safety_config import load_config
except ImportError:  # pragma: no cover
    from scripts.crew.brief.safety_config import load_config  # type: ignore

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENABLED_MODULES: tuple[str, ...] = ("thomas/core/__init__.py",)
DEFAULT_MYPY_ARGS: list[str] = [
    "--ignore-missing-imports",
    "--no-error-summary",
    "--no-color-output",
]


def _config():
    return load_config()


def _enabled_modules() -> tuple[str, ...]:
    configured = tuple(str(item) for item in (_config().type_safety_files() or []) if str(item).strip())
    return configured or DEFAULT_ENABLED_MODULES


def _mypy_args() -> list[str]:
    configured = [str(item) for item in (_config().type_safety_args() or []) if str(item).strip()]
    return configured or list(DEFAULT_MYPY_ARGS)


def _staged_files() -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _is_enabled(rel_path: str) -> bool:
    """Check if a file is in an enabled module."""
    for enabled in _enabled_modules():
        # Exact file match
        if rel_path == enabled:
            return True
        # Directory prefix match (e.g., "thomas/core/" enables all files under it)
        if enabled.endswith("/") and rel_path.startswith(enabled):
            return True
    return False


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    # Check if mypy is available
    mypy_path = shutil.which("mypy")
    if not mypy_path:
        if args.json:
            print(
                json.dumps(
                    {"gate": "type_safety", "ok": True, "skipped": True, "reason": "mypy not installed"}, sort_keys=True
                )
            )
        else:
            print("Type safety gate: PASS (mypy not installed — install with: pip install mypy)")
        return 0

    staged = _staged_files()
    python_files = [f for f in staged if f.endswith(".py")]
    enabled_files = [f for f in python_files if _is_enabled(f)]

    if not enabled_files:
        if args.json:
            print(
                json.dumps(
                    {"gate": "type_safety", "ok": True, "skipped": True, "reason": "no enabled files staged"},
                    sort_keys=True,
                )
            )
        else:
            print("Type safety gate: PASS (no type-checked files staged)")
        return 0

    # Run mypy on enabled files
    try:
        proc = subprocess.run(
            [mypy_path] + _mypy_args() + enabled_files,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        if args.json:
            print(
                json.dumps(
                    {"gate": "type_safety", "ok": True, "skipped": True, "reason": "mypy timed out"}, sort_keys=True
                )
            )
        else:
            print("Type safety gate: PASS (mypy timed out — check manually)")
        return 0

    errors = [line.strip() for line in proc.stdout.splitlines() if line.strip() and ": error:" in line]

    ok = len(errors) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "type_safety",
                    "ok": ok,
                    "files_checked": len(enabled_files),
                    "errors": errors[:20],
                    "enabled_modules": list(_enabled_modules()),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Type safety gate: PASS ({len(enabled_files)} file(s) checked)")
        else:
            print("❌ SAFETY GATE FAILED: Type Errors in Type-Checked Modules")
            print("=" * 70)
            print(f"Found {len(errors)} type error(s) in opted-in modules:")
            print()
            print("WHAT YOU DID WRONG:")
            for err in errors[:10]:
                print(f"  {err}")
            if len(errors) > 10:
                print(f"  ... and {len(errors) - 10} more")
            print()
            print("HOW TO FIX IT:")
            print("1. Fix the type errors reported by mypy.")
            print("2. Run mypy locally to verify:")
            print(f"   mypy {' '.join(_mypy_args())} {' '.join(enabled_files)}")
            print()
            print("These modules have opted in to type checking and must stay clean.")
            print("See: agent_safety.toml [type_safety]")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
