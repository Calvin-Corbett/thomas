from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class _DelegationEmitter:
    def __init__(self, emit_event: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._emit_event = emit_event

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
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                "is_canvas": bool(record.get("is_canvas")),
                "canvas_html": record.get("canvas_html", ""),
                "canvas_status": record.get("canvas_status", ""),
                **bot.to_event_dict(),
            }
        )

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
                "runtime_profile": record.get("runtime_profile") or {},
                "specialist_id": specialist_id,
                **bot.to_event_dict(),
            }
        )


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
