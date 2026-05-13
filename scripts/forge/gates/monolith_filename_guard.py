#!/usr/bin/env python3
"""Reject legacy monolith split filename patterns.

Catches ALL split patterns across ALL languages:
  - `.partNN.ext`  (dot-separated, e.g. app.part3.js)
  - `_partNN.ext`  (underscore-separated, e.g. app_part3.py)
  - `part-NNN.ext` (dash-separated, e.g. part-001.js)
  - Files inside directories named `*_parts/` or `*-parts/`

This check is intentionally strict and filename-only: if any staged or tracked
repository file matches the pattern, the gate fails unless that file is outside
scanned directories.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_PART_FILE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # .partNN.ext — e.g. app.part3.js
    re.compile(r"\.part\d+\.[^.]+$", re.IGNORECASE),
    # _partNN.ext — e.g. app_part3.py
    re.compile(r"_part\d+\.\w+$", re.IGNORECASE),
    # part-NNN.ext — e.g. part-001.js, part-032b.js
    re.compile(r"^part-\d+[a-z]?\.\w+$", re.IGNORECASE),
)

# Directories that are themselves a split pattern (e.g. app_parts/, css_parts/)
FORBIDDEN_SPLIT_DIR_PATTERNS: tuple[re.Pattern[str], ...] = (re.compile(r"[_-]parts?$", re.IGNORECASE),)

SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".next",
    ".nuxt",
    "build",
    "coverage",
    "dist",
    "runtime",
    "Inbox",
    "output",
    "pack",
    "patches",
    ".inbox_extract_20260210_234207",
    ".feature_backups",
}


def _runtime_protection_disabled() -> bool:
    """Check if a human has temporarily disabled runtime protection."""
    flag = ROOT / "runtime" / ".runtime_protection_disabled"
    return flag.is_file()


def _is_skipped_path(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _git_changed_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        rel = line.strip()
        if rel:
            out.append(rel)
    return out


def _is_forbidden_part_file(path: Path) -> bool:
    # Check the filename itself
    if any(pattern.search(path.name) for pattern in FORBIDDEN_PART_FILE_PATTERNS):
        return True
    # Check if the file lives in a forbidden split directory
    for parent in path.parents:
        if any(pattern.search(parent.name) for pattern in FORBIDDEN_SPLIT_DIR_PATTERNS):
            # Allow GUARDRAILS.md files inside these dirs (they document debt)
            return path.name.upper() not in ("GUARDRAILS.MD", "README.MD")
    return False


def _run_all_file_scan(repo_root: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for root, dirs, files in os.walk(repo_root, topdown=True):
        dirs[:] = [item for item in dirs if item not in SKIP_DIR_NAMES]
        for name in files:
            if not isinstance(name, str):
                continue
            path = Path(root) / name
            if _is_skipped_path(path):
                continue
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if not _is_forbidden_part_file(path):
                continue
            out.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "reason": "legacy split filename pattern",
                }
            )
    return out


def _run_staged_scan(repo_root: Path) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for rel in _git_changed_files(repo_root):
        path = repo_root / rel
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        if _is_skipped_path(path):
            continue
        if not _is_forbidden_part_file(path):
            continue
        out.append(
            {
                "path": rel.replace("\\", "/"),
                "reason": "legacy split filename pattern",
            }
        )
    return out


def _scan(repo_root: Path, *, staged_only: bool) -> list[dict[str, str]]:
    if staged_only:
        return _run_staged_scan(repo_root)
    return _run_all_file_scan(repo_root)


def run(argv: Iterable[str] | None = None) -> int:
    if _runtime_protection_disabled():
        print("Monolith filename guard: PASS (runtime protection disabled by human)")
        return 0

    parser = argparse.ArgumentParser(
        description=("Fail when `.partNN.ext` filenames are present " "in repository sources.")
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root (default: inferred from script location).",
    )
    parser.add_argument(
        "--staged-only",
        action="store_true",
        help="Limit scan to staged files only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    repo_root = Path(args.repo_root).resolve() if args.repo_root else ROOT
    violations = _scan(repo_root, staged_only=bool(args.staged_only))
    ok = len(violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "staged_only": bool(args.staged_only),
                    "repo_root": str(repo_root),
                    "violations": violations,
                },
                sort_keys=True,
            )
        )
    elif ok:
        print("Monolith filename guard: PASS " "(no legacy `.partNN.ext` filenames)")
    else:
        print(f"Monolith filename guard: FAIL " f"({len(violations)} violation(s))")
        for row in violations:
            print(f"- {row['path']}: {row['reason']}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
