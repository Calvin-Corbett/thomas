#!/usr/bin/env python3
"""Per-file growth guard for Thomas.

Prevents any single file from growing by more than MAX_GROWTH_LINES in a
single commit.  This is the key defense against agents that dump thousands
of lines into a file in one shot.

How it works:
  1. For every staged file, compute the line count in the working tree.
  2. Compute the line count at HEAD (or 0 if the file is new).
  3. If the growth exceeds the threshold, FAIL — unless the file extension
     is not in the monitored set.

Override:
  Set THOMAS_COMMIT_GROWTH_GUARD_DISABLE=1 to skip (audited by the
  pre-commit skip policy gate).

Exit codes:
  0 — all staged files within growth budget
  1 — one or more files exceed the per-commit growth cap
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Configurable limits ──────────────────────────────────────────────────
# Maximum net lines a single file may grow in one commit.
DEFAULT_MAX_GROWTH = 300

# File extensions to monitor.  Only these are checked.
MONITORED_EXTENSIONS: set[str] = {
    "py",
    "js",
    "mjs",
    "cjs",
    "jsx",
    "ts",
    "tsx",
    "css",
    "html",
}

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "coverage",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    ".feature_backups",
}


def _runtime_protection_disabled() -> bool:
    """Check if a human has temporarily disabled runtime protection."""
    flag = ROOT / "runtime" / ".runtime_protection_disabled"
    return flag.is_file()


def _is_skipped(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in SKIP_DIR_NAMES for p in parts)


def _staged_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _working_tree_lines(repo_root: Path, rel: str) -> int:
    path = repo_root / rel
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _head_lines(repo_root: Path, rel: str) -> int:
    """Line count of the file at HEAD.  Returns 0 for new files."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return 0  # new file
    text = proc.stdout
    if not text:
        return 0
    return len(text.splitlines())


def run(
    repo_root: Path,
    *,
    max_growth: int = DEFAULT_MAX_GROWTH,
    json_output: bool = False,
) -> int:
    if _runtime_protection_disabled():
        if not json_output:
            print("Commit growth guard: PASS (runtime protection disabled by human)")
        return 0

    if os.environ.get("THOMAS_COMMIT_GROWTH_GUARD_DISABLE") == "1":
        if not json_output:
            print("Commit growth guard: SKIP " "(THOMAS_COMMIT_GROWTH_GUARD_DISABLE=1)")
        return 0

    staged = _staged_files(repo_root)
    violations: list[dict] = []

    for rel in staged:
        if _is_skipped(rel):
            continue
        ext = Path(rel).suffix.lstrip(".").lower()
        if ext not in MONITORED_EXTENSIONS:
            continue

        current = _working_tree_lines(repo_root, rel)
        prior = _head_lines(repo_root, rel)
        growth = current - prior

        if growth > max_growth:
            violations.append(
                {
                    "path": rel,
                    "prior_lines": prior,
                    "current_lines": current,
                    "growth": growth,
                    "max_growth": max_growth,
                    "is_new_file": prior == 0,
                }
            )

    ok = len(violations) == 0

    if json_output:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "max_growth": max_growth,
                    "staged_count": len(staged),
                    "violations": violations,
                },
                indent=2,
            )
        )
    elif ok:
        print(f"Commit growth guard: PASS " f"(no file grew by more than {max_growth} lines)")
    else:
        print(
            f"Commit growth guard: FAIL — {len(violations)} file(s) "
            f"grew by more than {max_growth} lines in this commit."
        )
        print(
            f"  The per-commit growth cap is {max_growth} lines.  "
            f"Split your changes across multiple files or "
            f"multiple commits with meaningful intermediate states."
        )
        for v in violations:
            tag = " (NEW FILE)" if v["is_new_file"] else ""
            print(f"  - {v['path']}: {v['prior_lines']} -> " f"{v['current_lines']} (+{v['growth']} lines){tag}")

    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=("Block commits where any single file " "grows by too many lines."))
    parser.add_argument(
        "--max-growth",
        type=int,
        default=DEFAULT_MAX_GROWTH,
        help=f"Max net line growth per file (default: {DEFAULT_MAX_GROWTH}).",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred).",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    return run(repo_root, max_growth=args.max_growth, json_output=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
