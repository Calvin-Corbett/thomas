"""Report-only tool: does the honesty-spine log reconstruct what the model saw?

Reads `shadow/divergence` events already written by
`derive_messages.shadow_diff_if_enabled` (only present on runs where
`THOMAS_HONESTY_SHADOW=1` was set for the process that produced them) and
prints a summary. This tool is diagnostic ONLY -- it never gates a build or a
commit, and it always exits 0, even when the run store cannot be opened at
all.

Comparison scope (stated here, and on every shadow/divergence event this
report reads): the shadow diff compares ROLE + CONTENT of NON-SYSTEM messages
only. System messages are excluded because `_build_messages` assembles them
from memory retrieval, skills context, the autonomy profile, and project
instructions -- live sources the log does not yet capture as context/inject
events. See thomas/marketplace/observability/derive_messages.py for the full
scope statement (what IS and is NOT reconstructed).

The honest zero is always printed as "0 divergences across N compared
turns" -- never as bare success -- because a silent "0 divergences" with no
stated denominator is indistinguishable from a report that never looked at
anything.

When divergences exist, this tool also prints the expected-class/
unclassified split from each event's `reason` tag (see
`derive_messages.classify_divergence`), with the caveat spelled out inline
every time: the tag is a cheap heuristic (tool-role presence), not a
diagnosis of any individual divergence's cause.

A separate, always-printed count covers `shadow/skip` events: turns the
derivation declined to compare at all (a lossy-fallback compaction in that
run's history -- see `derive_messages.NonComparableDerivation`). These are
neither matches nor divergences; counting them anywhere else would be a
guess this tool refuses to make.

Usage:
    python scripts/forge/honesty_shadow_report.py [--db PATH] [--limit N] [--last N]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from thomas.marketplace.observability import derive_messages as dm  # noqa: E402

COMPARISON_SCOPE_HEADER = (
    f"Comparison scope: {dm.COMPARISON_SCOPE} only "
    "(system messages excluded -- not yet captured as context/inject events)."
)

# A fixed, named tuple -- never a bare `except Exception` -- so a report
# failure is always something recognizable (a corrupt db, a bad payload row,
# sqlite unavailable), matching the same fail-safe pattern used throughout
# the honesty-spine plan (see derive_messages.SHADOW_EXCEPTIONS and
# capture_context.CAPTURE_EXCEPTIONS). This tool never fails its exit code,
# but it also never swallows an exception type it cannot name.
_REPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    OSError,
    sqlite3.Error,
    json.JSONDecodeError,
    MemoryError,
)


def _default_db_path() -> Path:
    from thomas.core.config import resolve_thomas_data_dir

    return (Path(resolve_thomas_data_dir()) / ".thomas" / "runs.sqlite3").resolve()


def _collect(db_path: Path, limit: int) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (compared_turns, divergences, skips) -- never raises.

    `compared_turns` counts every model/request event that had at least one
    PRIOR model/request already on its run -- the population a shadow
    comparison could have run against. It is an upper-bound proxy, not proof
    a comparison actually ran: this tool cannot see whether the shadow flag
    was on for the process that produced any given run, since the off
    position leaves no trace in the log by design (that IS the zero-behavior-
    change contract). Runs produced with the flag off inflate this count
    without ever having been compared -- named here so the number is never
    read as stronger evidence than it is.
    """
    from thomas.marketplace.observability import run_store
    from thomas.marketplace.observability import session_log_events as sle

    try:
        run_store.init_db(db_path)
    except OSError:
        return 0, [], []

    try:
        runs = run_store.list_runs(limit=max(1, int(limit)), offset=0, filters={})
    except _REPORT_EXCEPTIONS:  # report-only: a listing failure is still a 0, not a crash
        return 0, [], []

    compared_turns = 0
    divergences: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for run in runs:
        run_id = run.get("run_id")
        if not run_id:
            continue
        try:
            events = list(run_store.stream_replay(run_id))
        except _REPORT_EXCEPTIONS:  # a single unreadable run must not sink the whole report
            continue
        request_count = sum(1 for e in events if e.get("type") == sle.MODEL_REQUEST)
        compared_turns += max(0, request_count - 1)
        divergences.extend({"run_id": run_id, **e} for e in events if e.get("type") == dm.SHADOW_DIVERGENCE)
        skips.extend({"run_id": run_id, **e} for e in events if e.get("type") == dm.SHADOW_SKIP)

    return compared_turns, divergences, skips


def _print_report(
    compared_turns: int, divergences: list[dict[str, Any]], skips: list[dict[str, Any]], last_n: int
) -> None:
    print(COMPARISON_SCOPE_HEADER)
    print(f"{len(divergences)} divergences across {compared_turns} compared turns")
    print(
        f"{len(skips)} skipped as non-comparable "
        "(a compaction event this run cannot faithfully reconstruct -- declined to guess, not counted as a match or a divergence)"
    )
    if skips:
        lossy = sum(1 for s in skips if s.get("reason") == dm.SKIP_REASON_LOSSY_COMPACTION_FALLBACK)
        unverifiable = sum(1 for s in skips if s.get("reason") == dm.SKIP_REASON_COMPACTION_RANGE_UNVERIFIABLE)
        other = len(skips) - lossy - unverifiable
        print(
            f"  -> {lossy} lossy-fallback compaction / {unverifiable} unverifiable splice range"
            + (f" / {other} other" if other else "")
        )

    if not divergences:
        return

    expected = sum(1 for d in divergences if d.get("reason") == dm.REASON_CONTAINS_TOOL_ROLE)
    unclassified = len(divergences) - expected
    print(
        f"  -> {expected} expected-class ({dm.REASON_CONTAINS_TOOL_ROLE}) / {unclassified} {dm.REASON_UNCLASSIFIED} "
        "-- classification is a cheap heuristic (tool-role presence), not a diagnosis; "
        "an expected-class tag does not clear a divergence and an unclassified one is not proof of a bug."
    )

    print(f"\nLast {min(last_n, len(divergences))} divergence(s):")
    for entry in divergences[-last_n:]:
        run_id = str(entry.get("run_id", ""))
        diff_count = entry.get("diff_count", len(entry.get("diffs", [])))
        built_n = entry.get("built_message_count")
        derived_n = entry.get("derived_message_count")
        reason = entry.get("reason", dm.REASON_UNCLASSIFIED)
        print(
            f"- run {run_id}: {diff_count} diff(s), reason={reason} (built={built_n} messages, derived={derived_n} messages)"
        )
        for diff in list(entry.get("diffs", []))[:3]:
            print(f"    idx {diff.get('index')}: built={diff.get('built')!r} derived={diff.get('derived')!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Honesty-spine shadow-diff report -- report-only, always exits 0.")
    parser.add_argument(
        "--db", type=Path, default=None, help="Path to the runs sqlite3 db (default: resolved Thomas data dir)."
    )
    parser.add_argument("--limit", type=int, default=200, help="Max runs to scan, most recently started first.")
    parser.add_argument("--last", type=int, default=10, help="Number of most recent divergences to print in full.")
    args = parser.parse_args(argv)

    db_path = args.db or _default_db_path()

    try:
        compared_turns, divergences, skips = _collect(db_path, args.limit)
    except _REPORT_EXCEPTIONS as e:  # belt-and-suspenders: this tool NEVER fails the exit code
        print(COMPARISON_SCOPE_HEADER)
        print(f"Could not read {db_path}: {type(e).__name__}: {e}")
        print("0 divergences across 0 compared turns")
        print("0 skipped as non-comparable")
        return 0

    _print_report(compared_turns, divergences, skips, max(0, int(args.last)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
