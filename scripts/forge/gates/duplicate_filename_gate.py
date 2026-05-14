#!/usr/bin/env python3
"""Reject new files with duplication-signaling names.

Agents commonly create files like utils_v2.py, helper_new.py, or
service_updated.py instead of fixing the original. These names signal
duplicate work and violate GUARDRAILS.md Rule 4 ("No Duplicate Work").

Audit reference: Adversarial Audit Findings 10, 17, 18 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Load config from agent_safety.toml if available
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from agent_safety_config import config as _cfg

    _suffix_list = _cfg.forbidden_suffixes()
    _prefix_list = _cfg.forbidden_prefixes()
    SCAN_PREFIXES = tuple(d if d.endswith("/") else d + "/" for d in _cfg.all_code_dirs())
except ImportError:
    _suffix_list = ["_v2", "_new", "_fixed", "_copy", "_backup", "_old"]
    _prefix_list = ["new_", "copy_of_", "backup_", "old_"]
    SCAN_PREFIXES = ("src/", "scripts/", "tests/")

# Build regex patterns from config lists
_suffix_pattern = "|".join(re.escape(s) for s in _suffix_list)
FORBIDDEN_SUFFIXES = re.compile(
    rf"({_suffix_pattern})\.(py|js|mjs|ts|tsx|jsx|css|html)$",
    re.IGNORECASE,
)

_prefix_pattern = "|".join(re.escape(p) for p in _prefix_list)
FORBIDDEN_PREFIXES = re.compile(
    rf"^({_prefix_pattern})",
    re.IGNORECASE,
)

CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"}


def _staged_new_files() -> list[str]:
    """Get files that are newly added (not modified) in staging."""
    proc = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _is_scoped_code_file(path: str) -> bool:
    if not any(path.startswith(prefix) for prefix in SCAN_PREFIXES):
        return False
    return Path(path).suffix.lower() in CODE_EXTENSIONS


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)

    new_files = _staged_new_files()
    scoped_new = [path for path in new_files if _is_scoped_code_file(path)]
    violations: list[dict[str, str]] = []

    for filepath in scoped_new:
        name = Path(filepath).name
        if FORBIDDEN_SUFFIXES.search(name):
            violations.append(
                {
                    "path": filepath,
                    "reason": (
                        f"filename '{name}' uses a duplication-signaling suffix " "(-v2, _v2, -fixed, _new, etc.)"
                    ),
                }
            )
            continue
        if FORBIDDEN_PREFIXES.match(name):
            violations.append(
                {
                    "path": filepath,
                    "reason": (
                        f"filename '{name}' uses a duplication-signaling prefix "
                        "(new_, new-, copy_of_, copy-of-, etc.)"
                    ),
                }
            )

    ok = len(violations) == 0

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "duplicate_filename_gate",
                    "ok": ok,
                    "violations": violations,
                    "new_files_scanned": len(scoped_new),
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            if scoped_new:
                print(f"Duplicate filename gate: PASS ({len(scoped_new)} new file(s) checked)")
            else:
                print("Duplicate filename gate: PASS (no new files)")
        else:
            print("SAFETY GATE FAILED: Duplication-Signaling Filenames")
            print("=" * 70)
            print(f"Found {len(violations)} file(s) with names that signal duplicate work:")
            print()
            print("WHAT YOU DID WRONG:")
            for violation in violations:
                print(f"  - {violation['path']}")
                print(f"    {violation['reason']}")
            print()
            print("HOW TO FIX IT:")
            print("1. Search for existing implementations first:")
            print("   grep -r '<function_name>' thomas/ tests/ scripts/")
            print()
            print("2. If a similar file exists, fix or extend it.")
            print("   Do not create -v2, _v2, _new, or _fixed copies.")
            print()
            print("3. If this is genuinely new functionality, give it a")
            print("   descriptive name that reflects what it does, not that")
            print("   it replaces something.")
            print()
            print("See: GUARDRAILS.md Rule 4, PROJECT_MANAGEMENT_RULES.md Rule 4")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
