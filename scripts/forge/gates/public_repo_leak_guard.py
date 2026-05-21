#!/usr/bin/env python3
"""Public-repo leak guard.

Blocks pushes to the public main branch (or any commit that would land
on Calvin-Corbett/thomas) that contain internal-only patterns: competitor
names, internal-only doc filenames, agent-facing tooling at root, etc.

Triggered by:
- ``Thomas Publish Preflight`` pre-push hook
- ``GitHub Publish Safety`` CI workflow
- Optional pre-commit when ``THOMAS_PUBLIC_LEAK_GUARD=1``

This is the **2026-05-21 cleanup tripwire**: any future drift where a
competitor name or internal doc gets re-added (e.g. from a private
branch merge) will fail this gate before the change reaches public main.

Exit codes:
- 0: clean (or running on a non-public branch with no leak signals)
- 1: leak detected; pretty-print the offenders and refuse the push
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Forbidden substrings (case-insensitive). Add to this list when a new
# competitor or internal-only marker shows up. Each entry should be a
# substring that NEVER belongs on public main.
FORBIDDEN_SUBSTRINGS = (
    "openclaw",
    "open claw",
    "open-claw",
    "open_claw",
)

# Files that are ALLOWED to mention the forbidden substrings — typically
# the guard itself (which lists them as banned terms) and the changelog
# (historical record). Keep this list tiny.
ALLOWLIST_PATHS = frozenset(
    {
        "scripts/forge/gates/public_repo_leak_guard.py",
        "scripts/forge/publish/preflight.py",
        "CHANGELOG.md",
    }
)

# Forbidden file paths (exact relative paths under repo root). These
# files are by-policy internal-only; if they're tracked by git, the gate
# trips. Add new entries as the internal docs surface grows.
FORBIDDEN_PATHS = frozenset(
    {
        # Agent-facing internal docs that landed at root pre-2026-05-21
        # cleanup. If you need these back, move them into a private repo
        # or under `docs/internal/` (which is gitignored).
        "PROJECT_INDEX.md",
        "CLAUDE_CODE_GAP_ANALYSIS.md",
        "MODULE_REGISTRY.md",
        "PLAN-UI-UPGRADE.md",
        "AGENT_RULES_QUICK_REFERENCE.md",
        "AGENT_SAFETY_GATES.md",
        "WORKTREE_RULES.md",
        "REPO_CANONICAL_RULES.md",
        # Internal tooling at root
        "_healthcheck.py",
        "loc_counter.py",
        "check_zips.py",
        "module_analysis.csv",
        # Competitor artifacts
        "thomas_vs_openclaw_subcommands.json",
        "demo/baselines/openclaw.current.json",
        "docs/PRE_PUBLIC_CLEANUP.md",
        "docs/OPENCLAW_PARITY.md",
    }
)

# Forbidden path prefixes (any tracked file starting with these is blocked).
FORBIDDEN_PREFIXES = (
    "thomas/openclaw_compat/",
    "thomas/marketplace/openclaw_compat/",
    "library/entries/competitive-research/",
    "tests/competitors/",
    "scripts/competitors/",
    ".codex/skills/",  # codex sandbox artifacts
    "docs/internal/",  # explicit internal docs — should be gitignored
    "docs/OPENCLAW_",
    "docs/ops/COMPETITOR_",
)

# Patterns matching tmp/debugging files that shouldn't reach public main.
# Stay strict — `.tmp_*` is a debugging convention in this repo.
FORBIDDEN_REGEX = (
    re.compile(r"^\.tmp_"),
    re.compile(r"^thomas_vs_"),
)


def _tracked_files() -> list[str]:
    proc = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _changed_files(base: str, head: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _scan_paths(paths: Iterable[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (forbidden_path_hits, forbidden_substring_hits)."""
    path_hits: list[str] = []
    substring_hits: list[tuple[str, str]] = []
    for rel in paths:
        if not rel:
            continue
        if rel in FORBIDDEN_PATHS:
            path_hits.append(rel)
            continue
        if any(rel.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            path_hits.append(rel)
            continue
        if any(pattern.match(rel) for pattern in FORBIDDEN_REGEX):
            path_hits.append(rel)
            continue
        if rel in ALLOWLIST_PATHS:
            continue
        full = ROOT / rel
        if not full.is_file():
            continue
        try:
            raw = full.read_bytes()
        except OSError:
            continue
        if _is_binary(raw):
            continue
        try:
            text = raw.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, LookupError):
            continue
        lower = text.lower()
        for needle in FORBIDDEN_SUBSTRINGS:
            if needle in lower:
                substring_hits.append((rel, needle))
                break  # one hit per file is enough to flag it
    return path_hits, substring_hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only scan files changed between --base and --head (faster).",
    )
    parser.add_argument("--base", default="origin/main", help="Diff base (default: origin/main).")
    parser.add_argument("--head", default="HEAD", help="Diff head (default: HEAD).")
    parser.add_argument(
        "--allow-noncompetitive-internal",
        action="store_true",
        help="Skip the internal-docs check (still scans for competitor strings).",
    )
    args = parser.parse_args()

    if args.changed_only:
        try:
            files = _changed_files(args.base, args.head)
        except subprocess.CalledProcessError:
            # Fall back to full scan if the diff range is unreachable
            # (common during release branch cuts).
            files = _tracked_files()
    else:
        files = _tracked_files()

    path_hits, substring_hits = _scan_paths(files)

    if args.allow_noncompetitive_internal:
        # Strip path_hits that are internal-docs-only (those flagged by
        # FORBIDDEN_PATHS but not by competitor regex/prefixes).
        path_hits = [
            p
            for p in path_hits
            if not (
                p in FORBIDDEN_PATHS
                and not any(p.startswith(pref) for pref in FORBIDDEN_PREFIXES)
                and not any(pat.match(p) for pat in FORBIDDEN_REGEX)
            )
        ]

    if not path_hits and not substring_hits:
        print("Public repo leak guard: PASS (no internal artifacts detected).")
        return 0

    print("Public repo leak guard: FAIL")
    if path_hits:
        print("- Forbidden internal-only paths still tracked:")
        for hit in sorted(set(path_hits))[:30]:
            print(f"  - {hit}")
        if len(set(path_hits)) > 30:
            print(f"  ... and {len(set(path_hits)) - 30} more")
    if substring_hits:
        print("- Competitor/internal substring matches:")
        for rel, needle in sorted(set(substring_hits))[:30]:
            print(f"  - {rel}: contains '{needle}'")
        if len(set(substring_hits)) > 30:
            print(f"  ... and {len(set(substring_hits)) - 30} more")
    print()
    print("Run `python scripts/forge/gates/public_repo_leak_guard.py` to re-check.")
    print("If you need to add a legitimate exception, update FORBIDDEN_PATHS in")
    print("the gate script and add a justification comment.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
