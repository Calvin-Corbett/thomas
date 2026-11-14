"""Ordered tool execution for Build helpers with concurrent independent reads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from thomas.core.events import AgentEvent, EventType

log = logging.getLogger(__name__)


async def build_tool_result(
    run_one: Callable[[dict[str, Any]], Awaitable[AgentEvent]], tc: dict[str, Any], loop: Any, iteration: int
) -> AgentEvent:
    """Keep one failed Build tool from discarding the rest of its batch."""
    try:
        return await run_one(tc)
    except Exception as error:
        tc_id = str(tc.get("id", ""))
        tool_name = str(tc.get("name") or "tool")
        log.debug("Build tool %r failed: %s", tool_name, error, exc_info=True)
        await loop._audit_action(
            kind="tool_action_exception",
            tool_call_id=tc_id,
            tool_name=tool_name,
            decision="FAILED",
            reason=f"{type(error).__name__}: {error}",
            payload={},
        )
        result = f"Tool execution failed before completion: {error}"
        return AgentEvent(
            type=EventType.TOOL_RESULT,
            data={
                "tool_id": tc_id,
                "tool_name": tool_name,
                "result": result,
                "result_text": result,
                "ok": False,
                "duration_ms": 0,
            },
            iteration=iteration,
        )


_READ_NAMES = frozenset(
    {
        "fs.read_file",
        "fs.list_dir",
        "fs.search",
        "code.search",
        "code.find_definition",
        "code.find_references",
        "code.project_structure",
    }
)


async def execute_build_tool_batch(
    calls: list[dict[str, Any]],
    run_one: Callable[[dict[str, Any]], Awaitable[AgentEvent]],
) -> AsyncIterator[AgentEvent]:
    """Run contiguous read groups together; await every group before a non-read call."""
    pending: list[dict[str, Any]] = []
    for call in calls:
        is_read = str(call.get("name") or "") in _READ_NAMES
        if is_read:
            pending.append(call)
            if len(pending) < 4:
                continue
        if pending:
            for event in await asyncio.gather(*(run_one(read) for read in pending)):
                yield event
            pending.clear()
        if not is_read:
            yield await run_one(call)
    if pending:
        for event in await asyncio.gather(*(run_one(read) for read in pending)):
            yield event
