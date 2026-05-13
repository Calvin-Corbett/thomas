#!/usr/bin/env python3
"""Detect significant code removal in staged files.

Flags files that shrank by more than 30% (configurable) compared to
their HEAD version. This catches agents silently gutting files during
"cleanup" or "refactoring."

The gate does NOT block the commit outright — it requires the
verification record to include a shrinkage justification explaining
what was removed and why. If no verification record exists, the commit
is blocked.

Gap closed: 2 (silent code deletion inside files)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERIFICATION_RECORD = ROOT / ".git" / "agent_verification.json"

SHRINKAGE_THRESHOLD = 0.30  # 30%
CODE_EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".css", ".html"}


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


def _head_line_count(filepath: str) -> int | None:
    """Get line count of a file in HEAD. Returns None if file is new."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{filepath}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return len(proc.stdout.splitlines())


def _staged_line_count(filepath: str) -> int:
    """Get line count of a file in the staging area."""
    proc = subprocess.run(
        ["git", "show", f":{filepath}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        full = ROOT / filepath
        if full.exists():
            return len(full.read_text(encoding="utf-8").splitlines())
        return 0
    return len(proc.stdout.splitlines())


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
    parser.add_argument(
        "--threshold",
        type=float,
        default=SHRINKAGE_THRESHOLD,
        help=f"Shrinkage threshold (default: {SHRINKAGE_THRESHOLD})",
    )
    args = parser.parse_args(argv)

    staged = _staged_files()
    code_files = [f for f in staged if Path(f).suffix.lower() in CODE_EXTENSIONS]
    threshold = args.threshold

    shrunk_files: list[dict] = []

    for filepath in code_files:
        head_lines = _head_line_count(filepath)
        if head_lines is None or head_lines == 0:
            continue  # New file or empty file, no shrinkage

        current_lines = _staged_line_count(filepath)
        removed = head_lines - current_lines
        if removed <= 0:
            continue  # File grew or stayed same

        shrinkage_pct = removed / head_lines
        if shrinkage_pct > threshold:
            shrunk_files.append(
                {
                    "file": filepath,
                    "head_lines": head_lines,
                    "current_lines": current_lines,
                    "removed": removed,
                    "shrinkage_pct": round(shrinkage_pct * 100),
                }
            )

    if not shrunk_files:
        if args.json:
            print(json.dumps({"gate": "shrinkage", "ok": True, "files_checked": len(code_files)}, sort_keys=True))
        else:
            print(f"Shrinkage gate: PASS ({len(code_files)} files checked)")
        return 0

    # Files shrunk — check for justification in verification record
    record = _load_verification_record()
    justification = ""
    if record:
        justification = str(record.get("shrinkage", {}).get("deletions_justified", "")).strip()

    has_justification = len(justification) >= 10
    ok = has_justification

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "shrinkage",
                    "ok": ok,
                    "shrunk_files": shrunk_files,
                    "has_justification": has_justification,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print(f"Shrinkage gate: PASS ({len(shrunk_files)} file(s) shrunk, justification provided)")
        else:
            print("SAFETY GATE FAILED: Significant Code Removal Detected")
            print("=" * 70)
            print(f"Found {len(shrunk_files)} file(s) that lost >{int(threshold*100)}% of content:")
            print()
            for sf in shrunk_files:
                print(
                    f"  - {sf['file']}: {sf['head_lines']} -> {sf['current_lines']} lines ({sf['shrinkage_pct']}% removed)"
                )
            print()
            print("HOW TO FIX IT:")
            print("1. If this deletion was intentional, create a verification record:")
            print("   python scripts/create_verification_record.py \\")
            print('     --test-command "python -m pytest tests/ -v" \\')
            print('     --task "your task" \\')
            print('     --shrinkage-reason "Explain what was removed and why"')
            print()
            print("2. If this was accidental, undo the changes:")
            for sf in shrunk_files[:3]:
                print(f"   git checkout HEAD -- {sf['file']}")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
