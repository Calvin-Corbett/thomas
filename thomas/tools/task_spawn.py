"""Host-independent, bounded delegation lifecycle for ``task.spawn``."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)
ChildRunner = Callable[[str, str, str], AsyncIterator[dict[str, Any]]]
ChildRecorder = Callable[[str, dict[str, Any]], None]


class SpawnAgentTool(Tool):
    name = "task.spawn"
    category = "agents"
    description = (
        "Hand one self-contained piece of this task to another agent and wait for its result. "
        "Use it when the work splits into independent parts. Give each a title and a complete brief. "
        "Do small tasks yourself; a spawned agent cannot spawn further agents."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short name shown beside the agent's steps."},
            "instructions": {
                "type": "string",
                "description": "Complete brief; the agent cannot see your conversation.",
            },
        },
        "required": ["title", "instructions"],
    }

    def __init__(self, *, run_child: ChildRunner, record_event: ChildRecorder) -> None:
        self._run_child = run_child
        self._record_event = record_event

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        title = str(args.get("title") or "").strip() or "helper"
        instructions = str(args.get("instructions") or "").strip()
        if not instructions:
            return ToolResult(ok=False, error="instructions are required: the agent cannot see your conversation")
        child_id = "child_" + uuid.uuid4().hex[:12]

        def record(event: dict[str, Any]) -> None:
            self._record_event(title, {**event, "child_id": child_id})

        record({"type": "progress", "text": f"Spawned {title}"})
        answer: list[str] = []
        failure: str | None = None
        try:
            async for event in self._run_child(child_id, title, instructions):
                record(event)
                kind = str(event.get("type") or "")
                if kind == "text":
                    answer.append(str(event.get("text") or ""))
                elif kind == "error" and failure is None:
                    failure = str(event.get("error") or event.get("text") or "worker failed")
        except asyncio.CancelledError:
            record({"type": "progress", "text": f"{title} cancelled"})
            raise
        except (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError, TimeoutError) as exc:
            log.warning("Spawned agent %r failed: %s", title, exc, exc_info=True)
            record({"type": "error", "error": str(exc) or type(exc).__name__})
            return ToolResult(ok=False, error=f"{title} failed: {exc}")

        text = "".join(answer).strip()
        if failure is not None:
            return ToolResult(ok=False, data=text or None, error=f"{title} failed: {failure}")
        record({"type": "progress", "text": f"{title} finished"})
        return ToolResult(ok=True, data=text or f"{title} finished with nothing to report")
