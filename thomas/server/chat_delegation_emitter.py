from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

# Failures the best-effort notification path swallows (with logging).  The
# production notifier (thomas.notifications.delegation_hooks) is itself
# hardened to never raise; this guard exists for injected notifiers and
# import-time failures.  A notification failure must never break delegation.
_NOTIFY_EXCEPTIONS = (
    ImportError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    LookupError,
)


class _DelegationEmitter:
    def __init__(
        self,
        emit_event: Callable[[dict[str, Any]], Awaitable[None]],
        notifier: Callable[..., Any] | None = None,
    ) -> None:
        self._emit_event = emit_event
        self._notifier = notifier

    async def _notify_lifecycle(self, event: str, record: dict[str, Any], text: str = "") -> None:
        """Best-effort user notification (CAP-045); never raises."""
        try:
            notifier = self._notifier
            if notifier is None:
                # CAP-045: server emits Smart-Notification-Center notifications on
                # delegation lifecycle. This is a deliberate server->notifications
                # edge that still needs declaring in thomas/_architecture.py
                # (server.depends_on += "notifications"); the import is kept
                # function-level and fail-silent so it never loads at boot and a
                # notification failure never breaks delegation.
                from thomas.notifications.delegation_hooks import emit_delegation_notification

                notifier = emit_delegation_notification
            await asyncio.to_thread(notifier, event, record, text=text)
        except _NOTIFY_EXCEPTIONS:
            log.warning(
                "delegation %s notification failed (execution_id=%s)",
                event,
                record.get("execution_id", ""),
                exc_info=True,
            )

    async def approval_needed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        """Notify that a delegation is paused waiting for user approval."""
        await self._notify_lifecycle("approval_needed", record, text)

    async def started(self, record: dict[str, Any], *, specialist_id: str, bot: Any) -> None:
        await self._emit_event(
            {
                "type": "delegation_started",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "queued"),
                "summary": record.get("summary", ""),
                "last_progress": record.get("last_progress", ""),
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                "proof_status": record.get("proof_status", "missing"),
                "receipt": record.get("receipt") or {},
                **bot.to_event_dict(),
            }
        )

    async def progress(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._emit_event(
            {
                "type": "delegation_progress",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": record.get("state", "executing"),
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                "proof_status": record.get("proof_status", "missing"),
                "receipt": record.get("receipt") or {},
                **bot.to_event_dict(),
            }
        )

    async def completed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._emit_event(
            {
                "type": "delegation_completed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "completed",
                "summary": record.get("summary", ""),
                "last_progress": text or record.get("last_progress", ""),
                "artifact_url": record.get("artifact_url", ""),
                "artifact_name": record.get("artifact_name", ""),
                "artifact_kind": record.get("artifact_kind", ""),
                "artifacts": record.get("artifacts") or [],
                "proof_status": record.get("proof_status", "missing"),
                "proof": record.get("proof") or {},
                "receipt": record.get("receipt") or {},
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                "canvas_review_status": record.get("canvas_review_status", ""),
                **bot.to_event_dict(),
            }
        )
        await self._notify_lifecycle("completed", record, text)

    async def failed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._emit_event(
            {
                "type": "delegation_failed",
                "execution_id": record.get("execution_id", ""),
                "task_id": record.get("task_id", ""),
                "session_id": record.get("session_id", ""),
                "backend_type": record.get("backend_type", ""),
                "state": "failed",
                "summary": record.get("summary", ""),
                "last_progress": text,
                "proof_status": record.get("proof_status", "failed"),
                "proof": record.get("proof") or {},
                "receipt": record.get("receipt") or {},
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )
        await self._notify_lifecycle("failed", record, text)


class _ThreadsafeDelegationEmitter:
    def __init__(self, emitter: _DelegationEmitter, loop: asyncio.AbstractEventLoop) -> None:
        self._emitter = emitter
        self._loop = loop

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        coro = getattr(self._emitter, method)(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(future)

    async def started(self, record: dict[str, Any], *, specialist_id: str, bot: Any) -> None:
        await self._call("started", record, specialist_id=specialist_id, bot=bot)

    async def progress(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._call("progress", record, specialist_id=specialist_id, bot=bot, text=text)

    async def completed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._call("completed", record, specialist_id=specialist_id, bot=bot, text=text)

    async def failed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str) -> None:
        await self._call("failed", record, specialist_id=specialist_id, bot=bot, text=text)

    async def approval_needed(self, record: dict[str, Any], *, specialist_id: str, bot: Any, text: str = "") -> None:
        await self._call("approval_needed", record, specialist_id=specialist_id, bot=bot, text=text)
