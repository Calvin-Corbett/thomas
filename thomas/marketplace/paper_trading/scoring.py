"""Outcome scoring + track-record summary — the part that compounds.

Each journal entry pairs a thesis with the realized result. Scoring updates the
entry's P&L and a coarse thesis_outcome, and can write a durable "lesson" into
Thomas's memory engine so future proposals are informed by past calls.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from thomas.marketplace.paper_trading._types import (
    JournalEntry,
    ThesisOutcome,
    TrackRecord,
)

log = logging.getLogger(__name__)

# A move smaller than this (in %) is treated as noise, not a validated thesis.
_NOISE_PCT = 0.5

# What a duck-typed memory engine can realistically fail with: a missing or
# mis-shaped add_event (AttributeError/TypeError), a rejected payload
# (ValueError/LookupError), its SQLite store (sqlite3.Error), the files behind it
# (OSError), or an engine that reports its own failure as RuntimeError. Matches
# the tuple orchestrator/brain.py already uses for the same memory writes.
_MEMORY_WRITE_FAULTS = (
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    sqlite3.Error,
)


def score_open_entry(
    entry: JournalEntry,
    *,
    current_price: float,
    still_open: bool,
) -> JournalEntry:
    """Update an entry with the latest price and a coarse thesis verdict.

    The thesis verdict is intentionally simple and direction-aware: a long that
    is up validates, down invalidates; vice-versa for a short. A model can later
    refine the ``lesson`` text; this gives an honest, mechanical baseline.
    """
    if current_price > 0:
        entry.last_price = round(current_price, 4)

    direction = 1.0 if entry.side == "buy" else -1.0
    if entry.entry_price > 0 and current_price > 0:
        move_pct = ((current_price - entry.entry_price) / entry.entry_price) * 100.0
        pnl_pct = direction * move_pct
        entry.unrealized_plpc = round(pnl_pct, 4)
        entry.unrealized_pl = round(direction * (current_price - entry.entry_price) * entry.qty, 2)

    if still_open:
        entry.thesis_outcome = ThesisOutcome.OPEN.value
        return entry

    # Position is closed — promote unrealized into realized and judge the thesis.
    entry.realized_pl = entry.unrealized_pl
    if not entry.closed_at:
        import time

        entry.closed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if abs(entry.unrealized_plpc) < _NOISE_PCT:
        entry.thesis_outcome = ThesisOutcome.INCONCLUSIVE.value
    elif entry.unrealized_plpc > 0:
        entry.thesis_outcome = ThesisOutcome.VALIDATED.value
    else:
        entry.thesis_outcome = ThesisOutcome.INVALIDATED.value
    return entry


def summarize_track_record(entries: list[JournalEntry]) -> TrackRecord:
    tr = TrackRecord(total=len(entries))
    for e in entries:
        is_closed = bool(e.closed_at)
        if is_closed:
            tr.closed_count += 1
            tr.total_realized_pl += e.realized_pl
            if e.realized_pl > 0:
                tr.wins += 1
            elif e.realized_pl < 0:
                tr.losses += 1
            if e.thesis_outcome == ThesisOutcome.VALIDATED.value:
                tr.thesis_validated += 1
            elif e.thesis_outcome == ThesisOutcome.INVALIDATED.value:
                tr.thesis_invalidated += 1
        else:
            tr.open_count += 1
            tr.total_unrealized_pl += e.unrealized_pl

    decided = tr.wins + tr.losses
    tr.win_rate = round((tr.wins / decided) * 100.0, 1) if decided else 0.0
    tr.avg_realized_pl = round(tr.total_realized_pl / tr.closed_count, 2) if tr.closed_count else 0.0
    tr.total_realized_pl = round(tr.total_realized_pl, 2)
    tr.total_unrealized_pl = round(tr.total_unrealized_pl, 2)

    if tr.closed_count == 0:
        tr.notes.append("No closed trades yet — track record is still forming.")
    elif tr.win_rate >= 55:
        tr.notes.append(f"{tr.win_rate:.0f}% win rate over {decided} decided trades.")
    else:
        tr.notes.append(f"Win rate {tr.win_rate:.0f}% — review invalidated theses for patterns.")
    return tr


def build_lesson(entry: JournalEntry) -> str:
    """A one-line, human-readable lesson scaffold for memory + UI."""
    verdict = entry.thesis_outcome
    pnl = entry.realized_pl if entry.closed_at else entry.unrealized_pl
    sign = "+" if pnl >= 0 else ""
    return (
        f"[{entry.side.upper()} {entry.symbol}] thesis={entry.thesis!r} "
        f"outcome={verdict} pnl={sign}{pnl:.2f}. "
        f"Invalidation was: {entry.invalidation!r}."
    )


def record_lesson(memory_engine: Any, entry: JournalEntry, *, thread: str = "paper-trading") -> bool:
    """Write a durable lesson into Thomas's memory engine. Best-effort.

    Returns True on success. Never raises — a memory hiccup must not break the
    trading loop.
    """
    if memory_engine is None:
        return False
    try:
        add_event = getattr(memory_engine, "add_event", None)
        if not callable(add_event):
            return False
        add_event(
            thread,
            "paper_trade_lesson",
            build_lesson(entry),
            {
                "symbol": entry.symbol,
                "side": entry.side,
                "thesis_outcome": entry.thesis_outcome,
                "realized_pl": entry.realized_pl,
                "proposal_id": entry.proposal_id,
            },
        )
        return True
    except _MEMORY_WRITE_FAULTS:
        log.debug("paper-trading lesson write failed for %s", entry.proposal_id, exc_info=True)
        return False
