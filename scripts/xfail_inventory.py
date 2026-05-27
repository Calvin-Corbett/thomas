#!/usr/bin/env python3
"""Human-facing inventory + report tool for pytest.mark.xfail markers.

The AST scanner lives in scripts/xfail_scanner.py — this module wraps
it with enrichment (git blame, classification, arc-id) and report
generation.

Usage:
    python scripts/xfail_inventory.py                # human summary
    python scripts/xfail_inventory.py --json         # machine-readable
    python scripts/xfail_inventory.py --by-arc       # group by arc-id
    python scripts/xfail_inventory.py --count-only   # just `N xfails`

Classification heuristics are in CLASSIFIERS below. Arc-id extractors
are in ARC_ID_PATTERNS. The senior review's recommended cleanup order
uses these classifications to prioritize.

Part of the xfail-debt arc (P0-1 from the 2026-05-27 senior review).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.xfail_scanner import XfailEntry, find_xfail_markers  # noqa: E402

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Reason text -> classification heuristics. Order matters; first match wins.
# Word-boundary anchors (\b) prevent false positives like "STUB_TRACKING"
# matching the "stub" keyword.
CLASSIFIERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("flake", re.compile(r"\bflake|RNG|nondeterministic|timing|race\b", re.IGNORECASE)),
    (
        "domain-stub",
        re.compile(r"\b(skeleton|stub|placeholder|NotImplementedError|pending implementation)\b", re.IGNORECASE),
    ),
    ("step-up", re.compile(r"step-up|mixed-\d+|surfaced by step", re.IGNORECASE)),
    ("tracked", re.compile(r"docs/|tracking|tracked\s+(separately|per|in)|TRACKING\.md|Pattern\s+\d+", re.IGNORECASE)),
    ("platform-specific", re.compile(r"skipif|platform|Windows-only|Linux-only|macOS-only", re.IGNORECASE)),
)


def _classify(reason: str) -> str:
    for label, pat in CLASSIFIERS:
        if pat.search(reason):
            return label
    return "other"


# ---------------------------------------------------------------------------
# Arc-id extraction from commit subjects
# ---------------------------------------------------------------------------
# Examples:
#   `test(mixed-19): xfail ...`               → mixed-19
#   `test(pathfinding): xfail ...`            → pathfinding
#   `fix(autonomy)+test(mixed-20): ...`       → mixed-20

ARC_ID_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^test\(([^)]+)\):", re.IGNORECASE),
    re.compile(r"^fix\(([^)]+)\)\s*\+\s*test\(([^)]+)\):", re.IGNORECASE),
)


def _arc_id_from_subject(subject: str) -> str:
    for pat in ARC_ID_PATTERNS:
        m = pat.match(subject)
        if m:
            # Take last group (in fix+test combos, the test arc is informative)
            return m.groups()[-1].strip().lower()
    return ""


# ---------------------------------------------------------------------------
# Git blame — find the introducing commit for a specific file:line
# ---------------------------------------------------------------------------


def _git_blame(file: str, line: int) -> tuple[str, str, str]:
    """Return (commit_sha, commit_subject, commit_date) for file:line."""
    try:
        # `git log -L<line>,<line>:<file>` shows commits touching that line.
        # Reversed → oldest first → that's the introducer.
        result = subprocess.run(
            ["git", "log", "--reverse", "--format=%H%n%s%n%cs", "-L", f"{line},{line}:{file}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ("", "", "")
    if result.returncode != 0:
        return ("", "", "")
    lines = result.stdout.splitlines()
    if len(lines) < 3:
        return ("", "", "")
    return (lines[0][:12], lines[1], lines[2])


# ---------------------------------------------------------------------------
# Enrichment + reporting
# ---------------------------------------------------------------------------


def enrich(entries: list[XfailEntry]) -> list[XfailEntry]:
    """Add git blame, classification, and arc-id to each entry.

    Mutates entries in-place AND returns them, for both styles.
    Skipped automatically for rev-mode entries (their `file` field is
    repo-relative but the working tree may not match).
    """
    for entry in entries:
        entry.commit_sha, entry.commit_subject, entry.commit_date = _git_blame(entry.file, entry.line)
        entry.arc_id = _arc_id_from_subject(entry.commit_subject) or entry.commit_sha[:8]
        entry.classification = _classify(entry.reason)
    return entries


def _print_summary(entries: list[XfailEntry], by_arc: bool) -> None:
    print("# xfail inventory")
    print(f"\nTotal: {len(entries)} xfails across {len({e.file for e in entries})} files\n")

    cls_counts = Counter(e.classification for e in entries)
    print("## By classification\n")
    for cls, n in cls_counts.most_common():
        print(f"  {cls:18s} {n:4d}")
    print()

    arc_counts = Counter(e.arc_id for e in entries if e.arc_id)
    print("## By arc-id (top 15)\n")
    for arc, n in arc_counts.most_common(15):
        print(f"  {arc:25s} {n:4d}")
    print()

    if by_arc:
        groups: dict[str, list[XfailEntry]] = defaultdict(list)
        for e in entries:
            groups[e.arc_id or "untagged"].append(e)
        for arc in sorted(groups, key=lambda a: (-len(groups[a]), a)):
            print(f"\n## arc: {arc}  ({len(groups[arc])} entries)\n")
            for e in groups[arc]:
                print(f"  {e.to_summary_row()}")
    else:
        print("## All entries (oldest first)\n")
        for e in sorted(entries, key=lambda x: x.commit_date or "9999-99-99"):
            print(f"  {e.to_summary_row()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--by-arc", action="store_true", help="group by arc-id")
    parser.add_argument("--count-only", action="store_true", help="print just `N xfails`")
    parser.add_argument("--rev", default=None, help="scan a specific git revision instead of working tree")
    args = parser.parse_args(argv)

    entries = find_xfail_markers(rev=args.rev)
    if args.rev is None:
        entries = enrich(entries)

    if args.count_only:
        print(f"{len(entries)} xfails")
        return 0
    if args.json:
        print(json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False))
        return 0

    _print_summary(entries, by_arc=args.by_arc)
    return 0


# Back-compat re-exports for callers that still import from this module.
# The gate originally imported `find_xfails` and `count_at_rev`; both now
# come from xfail_scanner. Re-export so neither moves.
from scripts.xfail_scanner import (  # noqa: E402, F401
    _find_xfails_in_file as _find_xfails_in_file,
)
from scripts.xfail_scanner import count_at_rev as count_at_rev  # noqa: E402, F401, PLC0414
from scripts.xfail_scanner import find_xfail_markers as find_xfails  # noqa: E402, F401, PLC0414

if __name__ == "__main__":
    sys.exit(main())
