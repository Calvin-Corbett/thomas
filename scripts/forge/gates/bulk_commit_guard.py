#!/usr/bin/env python3
"""Bulk commit guard for Thomas.

Prevents "snapshot" or "dump" commits that touch an unreasonable number of
files in a single commit.  These bulk dumps are the #1 vector for
smuggling monolith files past guards — when 1000+ files change at once,
review is impossible and bad things slip through.

How it works:
  1. Count the number of staged files.
  2. If the count exceeds MAX_FILES, FAIL.

Override:
  Set THOMAS_BULK_COMMIT_GUARD_DISABLE=1 to skip (audited by the
  pre-commit skip policy gate).

Exit codes:
  0 — staged file count is within budget
  1 — too many files staged
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# Maximum number of files that may be staged in a single commit.
# 50 is generous — most real feature commits touch 5-15 files.
# If you genuinely need to commit 50+ files (e.g. a migration), you
# must set THOMAS_BULK_COMMIT_GUARD_DISABLE=1 and document why.
DEFAULT_MAX_FILES = 50
APPROVAL_TRAILERS = ("thomas-bulk-change-approved:", "thomas-bulk-approved:", "thomas-breakglass:")
COMMIT_MESSAGE_ENV = "THOMAS_COMMIT_MESSAGE"


def _changed_files(repo_root: Path, *, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return files


def _staged_file_count(repo_root: Path) -> tuple[int, list[str]]:
    files = _changed_files(repo_root)
    return len(files), files


def _commit_messages(repo_root: Path, base: str, head: str) -> list[str]:
    if base == head:
        return []
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%B%n---END---", f"{base}..{head}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [chunk.strip() for chunk in str(proc.stdout or "").split("---END---") if chunk.strip()]


def _bulk_approval(messages: list[str]) -> tuple[bool, str, str]:
    for msg in messages:
        for line in msg.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            for trailer in APPROVAL_TRAILERS:
                if not lowered.startswith(trailer):
                    continue
                reason = stripped.split(":", 1)[1].strip()
                if reason:
                    return True, trailer.rstrip(":"), reason
    return False, "", ""


def run(
    repo_root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    json_output: bool = False,
    base: str | None = None,
    head: str | None = None,
) -> int:
    if os.environ.get("THOMAS_BULK_COMMIT_GUARD_DISABLE") == "1":
        if not json_output:
            print("Bulk commit guard: SKIP (THOMAS_BULK_COMMIT_GUARD_DISABLE=1)")
        return 0

    files = _changed_files(repo_root, base=base, head=head) if base and head else _staged_file_count(repo_root)[1]
    count = len(files)
    approved = False
    approval_trailer = ""
    approval_reason = ""
    if count > max_files and base and head:
        approved, approval_trailer, approval_reason = _bulk_approval(_commit_messages(repo_root, base, head))
    elif count > max_files:
        message = str(os.getenv(COMMIT_MESSAGE_ENV, "") or "")
        if message:
            approved, approval_trailer, approval_reason = _bulk_approval([message])
    ok = count <= max_files or approved

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "staged_count": count,
                    "max_files": max_files,
                    "approved_bulk_change": approved,
                    "approval_trailer": approval_trailer,
                    "approval_reason": approval_reason,
                },
                indent=2,
            )
        )
    elif ok:
        if approved:
            print(
                "Bulk commit guard: PASS "
                f"({count} files, limit {max_files}; approved via {approval_trailer}: {approval_reason[:120]})"
            )
        else:
            print(f"Bulk commit guard: PASS ({count} staged file(s), limit {max_files})")
    else:
        print(f"Bulk commit guard: FAIL — {count} files staged (limit is {max_files}).")
        print(
            "  Bulk dump commits are banned.  Break your work into "
            "smaller, focused commits.  If this is a genuine migration "
            "or refactor, use a non-empty Thomas-Bulk-Change-Approved "
            "commit trailer with the review/approval reason."
        )
        sample = files[:15]
        for f in sample:
            print(f"  - {f}")
        if count > 15:
            print(f"  ... and {count - 15} more")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Block commits that stage too many files at once.")
    parser.add_argument(
        "--max-files",
        type=int,
        default=DEFAULT_MAX_FILES,
        help=f"Maximum staged files per commit (default: {DEFAULT_MAX_FILES}).",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred).",
    )
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    args = parser.parse_args()
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(repo_root, max_files=args.max_files, json_output=args.json, base=args.base, head=args.head)


if __name__ == "__main__":
    raise SystemExit(main())
