"""Fail-honestly sweep for orphaned delegated executions.

A server restart (or crash) kills workers mid-run but leaves their records
in `executing`/`queued` forever — the UI then shows tasks "running" for
days and the user gets silence instead of a terminal answer (self-review
finding, 2026-07-20: records stuck 22 DAYS). This sweep closes any
non-terminal execution whose heartbeat has gone quiet far longer than the
worker watchdogs allow, so every task always reaches an honest end state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.server.issue_ledger import record_issue

log = logging.getLogger(__name__)

# Live workers refresh their heartbeat on every event, and the in-run
# watchdogs give up after minutes — 15 quiet minutes on a non-terminal
# record means nobody is driving it.
_STALE_AFTER_S = 15 * 60.0
_SWEEP_INTERVAL_S = 10 * 60.0
# Foreign spellings this sweep still recognises on top of
# task_bot_runtime.TERMINAL_STATES, which is the vocabulary the ledger actually
# WRITES: the workboard's "done", the pre-completion "verified", and
# succeeded/passed/error from non-ledger producers. Same alias list as
# chat_v2_announcements, and derived from the writer for the same reason: the
# literal that used to sit here disagreed with it in BOTH directions.
#
# It omitted "abandoned", so an already-ended record -- ALLOWED_TRANSITIONS
# gives it no successor at all -- was rewritten to "failed" with a made-up "no
# activity for N min (likely a restart) and did not finish", erasing its real
# ending and filing an issue about a task nothing had interrupted.
#
# It listed "blocked", so the one state this module exists to rescue was the one
# it skipped. blocked goes back to queued/claimed/executing, so it is a pause,
# not an ending; every other waiting state (requested/queued/claimed/
# awaiting_proof) was already swept and blocked was the lone exception.
_SWEEP_TERMINAL_ALIASES = frozenset({"done", "verified", "succeeded", "passed", "error"})
_TERMINAL = task_bot_runtime.TERMINAL_STATES | _SWEEP_TERMINAL_ALIASES


def _stamped_at(record: dict[str, Any]) -> datetime | None:
    raw = str(record.get("last_heartbeat_at") or record.get("updated_at") or record.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return stamped.astimezone(timezone.utc)


def _age_seconds(record: dict[str, Any]) -> float | None:
    stamped = _stamped_at(record)
    if stamped is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - stamped).total_seconds())


def sweep_stale_executions(
    repo_root: str | Path | None = None,
    *,
    max_idle_s: float = _STALE_AFTER_S,
    orphaned_before: datetime | None = None,
) -> int:
    """Fail every non-terminal execution idle beyond max_idle_s. Returns count.

    ``orphaned_before`` switches the test from "quiet for a while" to "cannot
    possibly be running", and is how the startup pass works. A record last
    touched before THIS process booted was owned by a process that no longer
    exists, so waiting out an idle timer proves nothing already unknown.
    Without it a restart left the user watching a task that had been dead since
    the moment they restarted -- for 15 quiet minutes plus up to another 10
    until the next sweep, and a restart is exactly when someone is sitting
    there watching.

    A worker belonging to the *current* process stamps a time after boot, so it
    is never touched. If the outgoing process manages a last heartbeat while we
    start, its record simply falls through to the ordinary idle sweep: this
    under-reaps rather than over-reaps, which is the safe direction.
    """
    closed = 0
    for row in task_bot_runtime.list_executions(repo_root, refresh=False):
        execution_id = str(row.get("execution_id") or "").strip()
        state = str(row.get("state") or "").lower()
        if not execution_id or state in _TERMINAL:
            continue
        full = task_bot_runtime.get_execution(execution_id, repo_root) or {}
        state = str(full.get("state") or state).lower()
        if state in _TERMINAL:
            continue
        if orphaned_before is not None:
            stamped = _stamped_at(full)
            # Unknown age is not evidence of being old; the idle sweep still
            # catches it later.
            if stamped is None or stamped >= orphaned_before:
                continue
            summary = "This task was interrupted by a restart and did not finish."
            note = "orphaned by restart"
        else:
            age = _age_seconds(full)
            if age is None or age < max_idle_s:
                continue
            minutes = int(age // 60)
            summary = (
                f"This task was interrupted (no activity for {minutes} min — likely a restart) and did not finish."
            )
            note = f"{minutes} min idle"
        try:
            task_bot_runtime.fail_execution(
                execution_id,
                actor="stale-sweep",
                summary=summary,
                blocker="stale_interrupted",
                repo_root=repo_root,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning("stale sweep could not close %s: %s", execution_id, exc)
            continue
        closed += 1
        record_issue(
            surface="chat-worker",
            kind="stale_interrupted",
            message=f"closed orphaned execution ({note}): {str(full.get('summary') or '')[:120]}",
            context={"execution_id": execution_id},
            repo_root=repo_root,
        )
    if closed:
        log.info("stale execution sweep closed %d orphaned record(s)", closed)
    return closed


async def run_stale_execution_sweeper(repo_root: str | Path | None = None) -> None:
    """Startup + periodic sweep; cancelled with the app."""
    booted_at = datetime.now(timezone.utc)
    try:
        # Anything last touched before we booted belongs to a process that is
        # gone. Close it now rather than making the user watch a dead task for
        # the length of an idle timer.
        closed = await asyncio.to_thread(sweep_stale_executions, repo_root, orphaned_before=booted_at)
        if closed:
            log.info("startup closed %d execution(s) orphaned by the previous process", closed)
    except (OSError, RuntimeError, TypeError, ValueError):
        log.warning("startup orphan reap failed", exc_info=True)
    while True:
        try:
            await asyncio.to_thread(sweep_stale_executions, repo_root)
        except (OSError, RuntimeError, TypeError, ValueError):
            log.warning("stale execution sweep failed", exc_info=True)
        await asyncio.sleep(_SWEEP_INTERVAL_S)


__all__ = ["run_stale_execution_sweeper", "sweep_stale_executions"]
