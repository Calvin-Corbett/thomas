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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Maximum number of files that may be staged in a single commit.
# 50 is generous — most real feature commits touch 5-15 files.
# If you genuinely need to commit 50+ files (e.g. a migration), you
# must set THOMAS_BULK_COMMIT_GUARD_DISABLE=1 and document why.
DEFAULT_MAX_FILES = 50


def _staged_file_count(repo_root: Path) -> tuple[int, list[str]]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0, []
    files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return len(files), files


def _top_level_scope(path: str) -> str:
    parts = Path(path).parts
    if not parts:
        return "<root>"
    if len(parts) == 1:
        return parts[0]
    if parts[0] in {"thomas", "tests"} and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _suggest_split_batches(files: list[str], *, max_groups: int = 4) -> list[dict[str, object]]:
    grouped: dict[str, list[str]] = {}
    for path in files:
        grouped.setdefault(_top_level_scope(path), []).append(path)
    ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
    return [
        {
            "scope": scope,
            "count": len(scope_files),
            "sample_files": scope_files[:5],
        }
        for scope, scope_files in ordered[:max_groups]
    ]


def run(
    repo_root: Path,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    json_output: bool = False,
) -> int:
    if os.environ.get("THOMAS_BULK_COMMIT_GUARD_DISABLE") == "1":
        if not json_output:
            print("Bulk commit guard: SKIP (THOMAS_BULK_COMMIT_GUARD_DISABLE=1)")
        return 0

    count, files = _staged_file_count(repo_root)
    ok = count <= max_files
    suggested_batches = _suggest_split_batches(files) if not ok else []

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "staged_count": count,
                    "max_files": max_files,
                    "files": files,
                    "suggested_batches": suggested_batches,
                },
                indent=2,
            )
        )
    elif ok:
        print(f"Bulk commit guard: PASS " f"({count} staged file(s), limit {max_files})")
    else:
        print(f"Bulk commit guard: FAIL — {count} files staged " f"(limit is {max_files}).")
        print(
            "  Bulk dump commits are banned.  Break your work into "
            "smaller, focused commits.  If this is a genuine migration "
            "or refactor, set THOMAS_BULK_COMMIT_GUARD_DISABLE=1 "
            "and document the reason in your commit message."
        )
        sample = files[:15]
        for f in sample:
            print(f"  - {f}")
        if count > 15:
            print(f"  ... and {count - 15} more")
        if suggested_batches:
            print("  Suggested split batches:")
            for batch in suggested_batches:
                print(f"  - scope={batch['scope']} ({batch['count']} files)")
                for path in batch["sample_files"]:
                    print(f"      {path}")
        print("  Next step: commit one focused scope first, then move to the next batch.")

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
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(repo_root, max_files=args.max_files, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
