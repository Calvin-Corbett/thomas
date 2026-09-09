#!/usr/bin/env python3
"""Require test file changes alongside source code changes.

When an agent changes 3+ source files, at least one test file must
also be staged. This forces agents to write tests for their features,
which is the primary mechanism for catching logic bugs and regressions.

Exceptions:
- Docs-only changes (*.md, *.txt, *.rst)
- Config-only changes (*.toml, *.yaml, *.yml, *.json, *.cfg)
- CHANGELOG.md-only changes

Gap closed: 3 (no test requirement), supports 1 (logic) and 10 (runtime)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew.brief.safety_config import config as _cfg

    SOURCE_PREFIXES = tuple(d if d.endswith("/") else d + "/" for d in _cfg.source_dirs())
    TEST_PREFIXES = tuple(d if d.endswith("/") else d + "/" for d in _cfg.test_dirs())
    THRESHOLD = _cfg.changelog_threshold()  # reuse same threshold
except ImportError:
    SOURCE_PREFIXES = ("src/", "scripts/")
    TEST_PREFIXES = ("tests/",)
    THRESHOLD = 3

CODE_EXTENSIONS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx"}
DOC_EXTENSIONS = {".md", ".txt", ".rst"}
CONFIG_EXTENSIONS = {".toml", ".yaml", ".yml", ".json", ".cfg", ".ini"}


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


def _is_source_code(path: str) -> bool:
    if not any(path.startswith(p) for p in SOURCE_PREFIXES):
        return False
    return Path(path).suffix.lower() in CODE_EXTENSIONS


def _is_test_file(path: str) -> bool:
    if any(path.startswith(p) for p in TEST_PREFIXES):
        return Path(path).suffix.lower() in CODE_EXTENSIONS
    return False


def _is_doc_or_config(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return suffix in DOC_EXTENSIONS or suffix in CONFIG_EXTENSIONS


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument(
        "--threshold", type=int, default=THRESHOLD, help=f"Min source files to require test (default: {THRESHOLD})"
    )
    args = parser.parse_args(argv)

    staged = _staged_files()
    source_files = [f for f in staged if _is_source_code(f)]
    test_files = [f for f in staged if _is_test_file(f)]
    threshold = max(1, args.threshold)

    # If all changes are docs/config, skip the check
    non_doc_files = [f for f in staged if not _is_doc_or_config(f)]
    if not non_doc_files:
        if args.json:
            print(
                json.dumps(
                    {"gate": "test_coverage", "ok": True, "skipped": True, "reason": "docs/config only"}, sort_keys=True
                )
            )
        else:
            print("Test coverage gate: PASS (docs/config changes only)")
        return 0

    ok = True
    reason = ""

    if len(source_files) >= threshold and not test_files:
        ok = False
        reason = (
            f"You changed {len(source_files)} source file(s) but no test files. "
            f"Add or update tests in tests/ for your changes."
        )

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "test_coverage",
                    "ok": ok,
                    "source_files_staged": len(source_files),
                    "test_files_staged": len(test_files),
                    "threshold": threshold,
                    "reason": reason,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            if source_files and test_files:
                print(f"Test coverage gate: PASS ({len(source_files)} source + {len(test_files)} test files)")
            elif len(source_files) < threshold:
                print(f"Test coverage gate: PASS ({len(source_files)} source files, under threshold)")
            else:
                print("Test coverage gate: PASS")
        else:
            print("SAFETY GATE FAILED: No Test Files Staged")
            print("=" * 70)
            print(f"You changed {len(source_files)} source file(s) (threshold: {threshold}):")
            for f in source_files[:8]:
                print(f"  - {f}")
            if len(source_files) > 8:
                print(f"  ... and {len(source_files) - 8} more")
            print()
            print("But NO test files are staged.")
            print()
            print("HOW TO FIX IT:")
            print("1. Write tests for your changes in tests/")
            print("2. Run them: python -m pytest tests/your_test.py -v")
            print("3. Stage them: git add tests/your_test.py")
            print()
            print("Every feature needs tests. Tests catch logic bugs and")
            print("regressions that static checks cannot detect.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
