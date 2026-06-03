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
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# The sensitive blocklist — competitor names and self-comparison artifact
# paths — is NOT hardcoded in this public source. It lives in a local,
# gitignored file (`leak_blocklist.local.json`) that is merged on top of the
# generic defaults below at import time. So the public gate code reveals no
# competitor name, while protection stays full on any machine that has the
# file. To extend protection, edit the LOCAL file, not this source.

# Generic public defaults — safe to ship; they name no competitor.
_DEFAULT_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = ()

# Files allowed to mention blocklisted substrings (e.g. the changelog's
# historical record). The local blocklist file is gitignored, so it is
# never part of the tracked tree the gate scans.
ALLOWLIST_PATHS = frozenset(
    {
        "scripts/forge/gates/public_repo_leak_guard.py",
        "scripts/forge/publish/preflight.py",
        "CHANGELOG.md",
    }
)

# Generic internal-only docs/tooling that must not ship at root. Competitor-
# named paths are supplied by the local blocklist file.
_DEFAULT_FORBIDDEN_PATHS: frozenset[str] = frozenset(
    {
        # Agent-facing internal docs. If you need these back, move them
        # under `docs/internal/` (which is gitignored).
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
        "docs/PRE_PUBLIC_CLEANUP.md",
    }
)

# Generic forbidden prefixes (no competitor naming).
_DEFAULT_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    ".codex/skills/",  # codex sandbox artifacts
    "docs/internal/",  # explicit internal docs — should be gitignored
)

# Generic tmp/debugging filename patterns.
_DEFAULT_FORBIDDEN_REGEX: tuple[re.Pattern[str], ...] = (re.compile(r"^\.tmp_"),)

# Local, gitignored blocklist (competitor names + comparison artifact paths).
LOCAL_BLOCKLIST_PATH = ROOT / "scripts" / "forge" / "gates" / "leak_blocklist.local.json"


def _load_local_blocklist() -> tuple[tuple[str, ...], frozenset[str], tuple[str, ...], tuple[re.Pattern[str], ...]]:
    """Merge the local (gitignored) sensitive blocklist if present.

    Absent file (e.g. a fresh public clone) -> empty extras, so the gate
    still runs and enforces the generic defaults; it simply has no
    competitor-specific terms to check.

    The path is FIXED (not env-overridable). An earlier draft honored
    ``THOMAS_LEAK_BLOCKLIST_FILE``, but a worker-settable path is a fail-open
    hole: point it at a nonexistent file and every competitor-name rule is
    silently dropped while the gate still passes. The blocklist now always
    loads from the one gitignored location -- mirroring the
    THOMAS_PRAXIS_MARKER_KEY_FILE decision (see commit_breakglass_guard).
    """
    path = LOCAL_BLOCKLIST_PATH
    if not path.is_file():
        return (), frozenset(), (), ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (), frozenset(), (), ()
    subs = tuple(str(s).lower() for s in data.get("forbidden_substrings", []) if str(s).strip())
    paths = frozenset(str(s) for s in data.get("forbidden_paths", []) if str(s).strip())
    prefixes = tuple(str(s) for s in data.get("forbidden_prefixes", []) if str(s).strip())
    regexes: list[re.Pattern[str]] = []
    for pat in data.get("forbidden_regex", []):
        try:
            regexes.append(re.compile(str(pat)))
        except re.error:
            continue
    return subs, paths, prefixes, tuple(regexes)


_local_subs, _local_paths, _local_prefixes, _local_regex = _load_local_blocklist()

FORBIDDEN_SUBSTRINGS = _DEFAULT_FORBIDDEN_SUBSTRINGS + _local_subs
FORBIDDEN_PATHS = frozenset(_DEFAULT_FORBIDDEN_PATHS | _local_paths)
FORBIDDEN_PREFIXES = _DEFAULT_FORBIDDEN_PREFIXES + _local_prefixes
FORBIDDEN_REGEX = _DEFAULT_FORBIDDEN_REGEX + _local_regex


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
