#!/usr/bin/env python3
"""Enforce CHANGELOG.md updates when substantial code changes are staged.

Triggers when 3+ files under thomas/ are staged but CHANGELOG.md is not.
This catches real feature work while letting tiny fixes pass through.

See: GUARDRAILS.md Rule 6 - "Changelog Is Mandatory"
Audit reference: Adversarial Audit Finding 2 (2026-03-19)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# Load config from agent_safety.toml if available
try:
    from scripts.crew.brief.safety_config import config as _cfg

    DEFAULT_THRESHOLD = _cfg.changelog_threshold()
    CHANGELOG_PATH = _cfg.changelog_file()
    CODE_PREFIXES = tuple(d if d.endswith("/") else d + "/" for d in _cfg.source_dirs())
except ImportError:
    DEFAULT_THRESHOLD = 3
    CHANGELOG_PATH = "CHANGELOG.md"
    CODE_PREFIXES = ("src/", "scripts/")

CODE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css", ".html"}


def _changed_files(*, base: str | None = None, head: str | None = None) -> list[str]:
    diff_args = ["git", "diff", "--name-only"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    proc = subprocess.run(
        diff_args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _staged_files() -> list[str]:
    return _changed_files()


def _changelog_diff_content(base: str | None = None, head: str | None = None) -> str:
    """Get the meaningful content added to CHANGELOG.md in the staged diff."""
    diff_args = ["git", "diff"]
    if base and head:
        diff_args.extend([base, head])
    else:
        diff_args.append("--cached")
    diff_args.extend(["--", CHANGELOG_PATH])
    proc = subprocess.run(
        diff_args,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    # Extract only added lines (starting with +, excluding +++ header)
    added_lines = []
    for line in proc.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:].strip()
            # Ignore blank lines, pure whitespace, and trivial changes
            if content and len(content) > 3:
                added_lines.append(content)
    return "\n".join(added_lines)


def _is_code_file(path: str) -> bool:
    if not any(path.startswith(prefix) for prefix in CODE_PREFIXES):
        return False
    suffix = Path(path).suffix.lower()
    return suffix in CODE_EXTENSIONS


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Minimum staged code files to require CHANGELOG (default: {DEFAULT_THRESHOLD}).",
    )
    parser.add_argument("--base", default=None, help="Optional git base ref/SHA for diff-range mode.")
    parser.add_argument("--head", default=None, help="Optional git head ref/SHA for diff-range mode.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args(argv)
    if bool(args.base) != bool(args.head):
        parser.error("--base and --head must be provided together")

    staged = _changed_files(base=args.base, head=args.head) if args.base else _staged_files()
    code_files = [f for f in staged if _is_code_file(f)]
    changelog_staged = CHANGELOG_PATH in staged
    threshold = max(1, args.threshold)

    ok = True
    reason = ""

    if len(code_files) >= threshold and not changelog_staged:
        ok = False
        reason = f"You staged {len(code_files)} code file(s) (threshold: {threshold}) but CHANGELOG.md is not staged."
    elif len(code_files) >= threshold and changelog_staged:
        # Verify the CHANGELOG diff has real content, not just whitespace
        changelog_diff = (
            _changelog_diff_content(args.base, args.head) if args.base and args.head else _changelog_diff_content()
        )
        if not changelog_diff:
            ok = False
            reason = (
                "CHANGELOG.md is staged but contains no meaningful changes. "
                "Add a real changelog entry describing what you changed."
            )

    if args.json:
        print(
            json.dumps(
                {
                    "gate": "changelog_gate",
                    "ok": ok,
                    "code_files_staged": len(code_files),
                    "threshold": threshold,
                    "changelog_staged": changelog_staged,
                    "reason": reason,
                },
                sort_keys=True,
            )
        )
    else:
        if ok:
            print("Changelog gate: PASS")
            if code_files:
                print(f"  {len(code_files)} code file(s) staged", end="")
                if changelog_staged:
                    print(", CHANGELOG.md included.")
                else:
                    print(f" (under threshold of {threshold}).")
            else:
                print("  No code files under thomas/ staged.")
        else:
            print("SAFETY GATE FAILED: CHANGELOG.md Not Updated")
            print("=" * 70)
            print(f"You staged {len(code_files)} code file(s) under thomas/:")
            for f in code_files[:10]:
                print(f"  - {f}")
            if len(code_files) > 10:
                print(f"  ... and {len(code_files) - 10} more")
            print()
            print("WHAT YOU DID WRONG:")
            print("  GUARDRAILS.md Rule 6 requires a CHANGELOG.md entry for every")
            print("  logical unit of work. You changed code but didn't update CHANGELOG.md.")
            print()
            print("HOW TO FIX IT:")
            print("1. Add a changelog entry under ## [Unreleased] in CHANGELOG.md:")
            print("   ### Added / Changed / Fixed / Removed")
            print("   - <module>: <brief description of what changed and why>")
            print()
            print("2. Stage it:")
            print("   git add CHANGELOG.md")
            print()
            print("3. Retry your commit.")
            print("=" * 70)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
