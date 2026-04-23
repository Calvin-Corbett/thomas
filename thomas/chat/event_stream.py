"""Unified NDJSON event dispatcher.

Replaces the fragmented event emission scattered across
``chat_stream_events.py``, and routing paths in ``chat_aiohttp.py``.

All events go through ``EventDispatcher.emit()`` which handles:
    - JSON serialisation
    - Newline framing
    - Error wrapping
    - Event logging for debugging
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

# Type alias for the send function (writes bytes to StreamResponse)
SendFn = Callable[[bytes], Awaitable[None]]


class EventDispatcher:
    """Unified NDJSON event emitter for chat streaming.

    Usage::

        dispatcher = EventDispatcher(response.write)

        await dispatcher.emit({"type": "thinking", "text": "..."})
        await dispatcher.emit({"type": "text", "text": "Hello"})
        await dispatcher.emit_done(session_id="abc", thinking_summary="...")

    All events are NDJSON: one JSON object per line, terminated by ``\\n``.
    """

    def __init__(self, send_fn: SendFn) -> None:
        self._send = send_fn
        self._event_count = 0
        self._started_at = time.monotonic()
        self._history: list[dict[str, Any]] = []

    async def emit(self, event: dict[str, Any]) -> None:
        """Emit a single NDJSON event.

        Retries once on error before permanently dropping the event.
        """
        try:
            line = json.dumps(event, default=str, ensure_ascii=False) + "\n"
            await self._send(line.encode("utf-8"))
            self._event_count += 1
            self._history.append(event)
        except Exception as exc:
            # Attempt one retry
            try:
                log.debug("EventDispatcher.emit retry after error: %s (event type=%s)", exc, event.get("type"))
                line = json.dumps(event, default=str, ensure_ascii=False) + "\n"
                await self._send(line.encode("utf-8"))
                self._event_count += 1
                self._history.append(event)
            except Exception as retry_exc:
                log.warning(
                    "Event permanently dropped after retry: %s (event type=%s, error=%s)",
                    event.get("type"),
                    exc,
                    retry_exc,
                )

    async def emit_text(self, text: str) -> None:
        """Convenience: emit a text chunk."""
        await self.emit({"type": "text", "text": text})

    async def emit_thinking(self, text: str, phase: str = "thinking", duration_ms: int = 0) -> None:
        """Convenience: emit a thinking/reasoning event."""
        await self.emit(
            {
                "type": "thinking",
                "text": text,
                "phase": phase,
                "duration_ms": duration_ms,
            }
        )

    async def emit_delegation(
        self,
        specialist_id: str,
        task: str,
        contract_id: str = "",
    ) -> None:
        """Convenience: emit a specialist delegation event."""
        await self.emit(
            {
                "type": "delegation",
                "specialist_id": specialist_id,
                "task": task,
                "contract_id": contract_id,
            }
        )

    async def emit_agent_activity(
        self,
        agent_id: str,
        status: str,
        current_task: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        """Convenience: emit sub-agent status update."""
        await self.emit(
            {
                "type": "agent_activity",
                "agent_id": agent_id,
                "status": status,
                "current_task": current_task,
                "elapsed_ms": elapsed_ms,
            }
        )

    async def emit_tool_start(
        self,
        tool_name: str,
        tool_id: str = "",
        args: dict[str, Any] | None = None,
    ) -> None:
        """Convenience: emit tool execution start."""
        await self.emit(
            {
                "type": "tool_start",
                "name": tool_name,
                "id": tool_id or tool_name,
                "args": args or {},
            }
        )

    async def emit_tool_result(
        self,
        tool_name: str,
        result: str = "",
        ok: bool = True,
        elapsed_ms: int = 0,
        tool_id: str = "",
    ) -> None:
        """Convenience: emit tool execution result."""
        await self.emit(
            {
                "type": "tool_result",
                "name": tool_name,
                "id": tool_id or tool_name,
                "result": result,
                "ok": ok,
                "ms": elapsed_ms,
            }
        )

    async def emit_memory_refresh(
        self,
        layer: str,
        retrieved_items: int = 0,
        total_tokens: int = 0,
    ) -> None:
        """Convenience: emit memory refresh notification."""
        await self.emit(
            {
                "type": "memory_refresh",
                "layer": layer,
                "retrieved_items": retrieved_items,
                "total_tokens": total_tokens,
            }
        )

    async def emit_error(self, error: str) -> None:
        """Convenience: emit an error event."""
        await self.emit({"type": "error", "error": error})

    async def emit_done(
        self,
        session_id: str = "",
        conversation_version: int = 0,
        thinking_summary: str = "",
        total_thinking_ms: int = 0,
        iterations: int = 0,
        tool_calls: int = 0,
        tokens_used: int = 0,
        specialists_used: list[str] | None = None,
        **extra: Any,
    ) -> None:
        """Emit the final 'done' event with all metadata."""
        elapsed = int((time.monotonic() - self._started_at) * 1000)
        event: dict[str, Any] = {
            "type": "done",
            "session_id": session_id,
            "conversation_version": conversation_version,
            "thinking_summary": thinking_summary,
            "total_thinking_ms": total_thinking_ms,
            "total_elapsed_ms": elapsed,
            "iterations": iterations,
            "tool_calls": tool_calls,
            "tokens_used": tokens_used,
            "event_count": self._event_count,
            "specialists_used": specialists_used or [],
        }
        event.update(extra)
        await self.emit(event)

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started_at) * 1000)
