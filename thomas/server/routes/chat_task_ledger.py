"""Best-effort task-ledger lifecycle updates for the active chat route."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any, cast

from aiohttp import web

from thomas.marketplace.observability.task_ledger import (
    TaskLedgerStore,
    classify_completion_state,
    derive_active_goal,
)
from thomas.server.app_keys import APP_TASK_LEDGER

log = logging.getLogger(__name__)

_FAILED_TURN_PROGRESS = "Thomas could not complete this chat turn safely."


async def _run_ledger_update(
    operation: Callable[[], Any],
    *,
    session_id: str,
    source: str,
) -> None:
    """Keep observability failures from breaking a user-visible chat turn."""
    try:
        await asyncio.to_thread(operation)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        log.warning(
            "Chat task ledger update failed for session %s at %s (%s)",
            session_id[:12],
            source,
            type(exc).__name__,
        )


def _task_ledger(app: web.Application) -> TaskLedgerStore | None:
    return cast(TaskLedgerStore | None, app.get(APP_TASK_LEDGER))


async def record_chat_task_started(
    app: web.Application,
    *,
    session_id: str,
    user_text: str,
    temporary: bool,
) -> None:
    """Record that a validated persistent chat request began execution."""
    ledger = None if temporary else _task_ledger(app)
    if ledger is None:
        return

    def update() -> None:
        current = ledger.get_current(session_id)
        active_goal = derive_active_goal(
            user_text,
            current_goal=current.active_goal if current is not None else "",
        )
        ledger.update(
            session_id,
            active_goal=active_goal,
            status="in_progress",
            missing_inputs=[],
            last_progress="Received user request.",
            source="chat_v2.request",
            force_event=True,
        )

    await _run_ledger_update(update, session_id=session_id, source="chat_v2.request")


async def record_chat_task_pending(
    app: web.Application,
    *,
    session_id: str,
    progress: str,
    temporary: bool,
) -> None:
    """Keep a background Max-mode task open until its reviewed result arrives."""
    ledger = None if temporary else _task_ledger(app)
    if ledger is None:
        return

    def update() -> None:
        ledger.update(
            session_id,
            status="in_progress",
            missing_inputs=[],
            last_progress=progress,
            source="chat_v2.pending",
            force_event=True,
        )

    await _run_ledger_update(
        update,
        session_id=session_id,
        source="chat_v2.pending",
    )


async def record_chat_task_finished(
    app: web.Application,
    *,
    session_id: str,
    assistant_text: str,
    temporary: bool,
) -> None:
    """Classify the final assistant reply and persist its terminal task state."""
    ledger = None if temporary else _task_ledger(app)
    if ledger is None:
        return

    def update() -> None:
        status, missing_inputs, progress = classify_completion_state(assistant_text=assistant_text)
        ledger.update(
            session_id,
            status=status,
            missing_inputs=missing_inputs,
            last_progress=progress or "Turn completed.",
            source="chat_v2.done",
            force_event=True,
        )

    await _run_ledger_update(update, session_id=session_id, source="chat_v2.done")


async def record_chat_task_failed(
    app: web.Application,
    *,
    session_id: str,
    temporary: bool,
) -> None:
    """Record a safe terminal failure without leaking provider details."""
    ledger = None if temporary else _task_ledger(app)
    if ledger is None:
        return

    def update() -> None:
        ledger.update(
            session_id,
            status="blocked",
            missing_inputs=[],
            last_progress=_FAILED_TURN_PROGRESS,
            source="chat_v2.error",
            force_event=True,
        )

    await _run_ledger_update(
        update,
        session_id=session_id,
        source="chat_v2.error",
    )
