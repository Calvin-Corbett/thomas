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
_TERMINAL = {"completed", "done", "verified", "succeeded", "passed", "failed", "blocked", "error", "cancelled"}


def _age_seconds(record: dict[str, Any]) -> float | None:
    raw = str(record.get("last_heartbeat_at") or record.get("updated_at") or record.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        stamped = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - stamped.astimezone(timezone.utc)).total_seconds())


def sweep_stale_executions(repo_root: str | Path | None = None, *, max_idle_s: float = _STALE_AFTER_S) -> int:
    """Fail every non-terminal execution idle beyond max_idle_s. Returns count."""
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
        age = _age_seconds(full)
        if age is None or age < max_idle_s:
            continue
        minutes = int(age // 60)
        try:
            task_bot_runtime.fail_execution(
                execution_id,
                actor="stale-sweep",
                summary=f"This task was interrupted (no activity for {minutes} min — likely a restart) and did not finish.",
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
            message=f"closed orphaned execution after {minutes} min idle: {str(full.get('summary') or '')[:120]}",
            context={"execution_id": execution_id},
            repo_root=repo_root,
        )
    if closed:
        log.info("stale execution sweep closed %d orphaned record(s)", closed)
    return closed


async def run_stale_execution_sweeper(repo_root: str | Path | None = None) -> None:
    """Startup + periodic sweep; cancelled with the app."""
    while True:
        try:
            await asyncio.to_thread(sweep_stale_executions, repo_root)
        except (OSError, RuntimeError, TypeError, ValueError):
            log.warning("stale execution sweep failed", exc_info=True)
        await asyncio.sleep(_SWEEP_INTERVAL_S)


__all__ = ["run_stale_execution_sweeper", "sweep_stale_executions"]
