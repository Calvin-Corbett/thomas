#!/usr/bin/env python3
"""Sprawl detector — the merge-debt alarm.

Returns a non-zero exit and prints a clear warning when DIRTY worktrees exceed
the configured ceiling, lists the offenders, and recommends ``thomas consolidate``
(a future consolidation command — referenced here, not implemented).

Default-safe: with no worktrees beyond the main checkout this is a quiet no-op
(exit 0, no alarm). Surfaced by the startup brief alongside the ledger.

Usage:
    python scripts/crew/worktree_debt.py            # full report, exit 1 if over
    python scripts/crew/worktree_debt.py --summary  # one-line summary
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _force_utf8_streams() -> None:
    """UTF-8 stdout/stderr so glyphs render on a cp1252 console instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


_force_utf8_streams()

# scripts/crew/worktree_debt.py -> parents[2] == repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.crew import worktree_ledger
except ImportError:  # pragma: no cover - import path varies by run context
    import worktree_ledger  # type: ignore

CONSOLIDATE_HINT = "Recommended: run `thomas consolidate` to merge or retire stale/dirty worktrees."


@dataclass
class DebtReport:
    over_ceiling: bool
    dirty_count: int
    ceiling: int
    dirty: list[dict[str, object]] = field(default_factory=list)
    stale: list[dict[str, object]] = field(default_factory=list)
    summary: str = ""


def assess_debt(root: Path | None = None) -> DebtReport:
    """Build a merge-debt report from a freshly collected ledger."""
    ledger = worktree_ledger.collect(root)

    def _entry(row: worktree_ledger.WorktreeRow) -> dict[str, object]:
        return {
            "branch": row.branch or row.path,
            "path": row.path,
            "uncommitted": row.uncommitted_count,
            "days_since_last_commit": row.days_since_last_commit,
            "purpose": row.purpose,
        }

    return DebtReport(
        over_ceiling=ledger.over_ceiling,
        dirty_count=ledger.dirty_count,
        ceiling=ledger.config.max_dirty_worktrees,
        dirty=[_entry(row) for row in ledger.dirty_worktrees],
        stale=[_entry(row) for row in ledger.stale_worktrees],
        summary=worktree_ledger.summary_line(ledger),
    )


def render_report(report: DebtReport) -> str:
    lines: list[str] = []
    if report.over_ceiling:
        lines.append(f"⚠ MERGE DEBT: {report.dirty_count} DIRTY worktree(s) at/above the ceiling of {report.ceiling}.")
        for entry in report.dirty:
            age = entry.get("days_since_last_commit")
            age_text = "unknown" if age is None else f"{age}d"
            lines.append(
                f"  - {entry['branch']}: {entry['uncommitted']} uncommitted, last commit {age_text} "
                f"({entry['purpose']})"
            )
        lines.append(CONSOLIDATE_HINT)
    else:
        lines.append(f"✓ worktree debt OK: {report.dirty_count} dirty / ceiling {report.ceiling}.")
        if report.stale:
            lines.append(f"  note: {len(report.stale)} stale worktree(s) — consider retiring them.")
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect git worktree merge debt over the configured ceiling.")
    parser.add_argument("--root", default=str(ROOT), help="Repository root.")
    parser.add_argument("--summary", action="store_true", help="Print a one-line summary only.")
    args = parser.parse_args(argv)

    report = assess_debt(Path(args.root).expanduser())
    if args.summary:
        print(report.summary)
    else:
        print(render_report(report))
    return 1 if report.over_ceiling else 0


if __name__ == "__main__":
    raise SystemExit(run())
