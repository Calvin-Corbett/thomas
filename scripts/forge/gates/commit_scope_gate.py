#!/usr/bin/env python3
"""Limit commit scope to prevent enormous unfocused commits.

Rules:
- >20 code files: requires scope_justification in verification record
- >50 code files: hard block (split the commit)

Exceptions for bulk operations detected via git diff:
- Bulk renames (R status)
- Version bumps (only pyproject.toml, __init__.py, CHANGELOG.md changed)

Gap closed: 7 (enormous commits hide bad changes in volume)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
VERIFICATION_RECORD = ROOT / ".git" / "agent_verification.json"

WARN_THRESHOLD = 20
HARD_LIMIT = 50
CODE_EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".html"}

# These files don't count toward the code file count
VERSION_BUMP_FILES = {"pyproject.toml", "CHANGELOG.md", "thomas/__init__.py"}


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


def _staged_renames() -> int:
    """Count files that are renames (not new code)."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-status"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0
    return sum(1 for line in proc.stdout.splitlines() if line.strip() and line.strip()[0] == "R")


def _load_verification_record() -> dict | None:
    if not VERIFICATION_RECORD.exists():
        return None
    try:
        return json.loads(VERIFICATION_RECORD.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--warn", type=int, default=WARN_THRESHOLD)
    parser.add_argument("--hard-limit", type=int, default=HARD_LIMIT)
    args = parser.parse_args(argv)

    staged = _staged_files()
    code_files = [f for f in staged if Path(f).suffix.lower() in CODE_EXTENSIONS and f not in VERSION_BUMP_FILES]

    rename_count = _staged_renames()
    effective_count = max(0, len(code_files) - rename_count)

    ok = True
    reason = ""

    if effective_count > args.hard_limit:
        ok = False
        reason = (
            f"Commit touches {effective_count} code files (hard limit: {args.hard_limit}). "
            "Split into smaller, focused commits."
        )
    elif effective_count > args.warn:
        record = _load_verification_record()
        justification = ""
        if record:
            justification = str(record.get("scope_justification", "")).strip()
        if len(justification) < 10:
            ok = False
            reason = (
                f"Commit touches {effective_count} code files (>{args.warn}). "
                "Add scope_justification to the verification record."
            )

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "commit_scope",
                    "ok": ok,
                    "code_files": len(code_files),
                    "effective_count": effective_count,
                    "renames_excluded": rename_count,
                    "warn_threshold": args.warn,
                    "hard_limit": args.hard_limit,
                    "reason": reason,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Commit scope gate: PASS ({effective_count} code files)")
        else:
            print("SAFETY GATE FAILED: Commit Too Large")
            print("=" * 70)
            print(reason)
            print()
            if effective_count > args.hard_limit:
                print("HOW TO FIX IT:")
                print("  Split this into smaller, focused commits.")
                print("  Each commit should change one logical thing.")
            else:
                print("HOW TO FIX IT:")
                print("  Create a verification record with scope justification:")
                print("  python scripts/create_verification_record.py \\")
                print('    --test-command "python -m pytest tests/ -v" \\')
                print('    --task "your task" \\')
                print('    --scope-reason "Explain why this many files changed"')
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
