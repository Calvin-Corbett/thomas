"""Read Thomas's self-change projects without importing the server into the tools layer."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from thomas.tools.base import Tool, ToolResult


class SelfProjectsTool(Tool):
    name = "self.projects"
    category = "self"
    description = (
        "List Thomas's own self-change projects and where each stands. Use when asked what Thomas is working on "
        "in itself or whether any of those projects are running."
    )
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "How many projects to list. Default 20."}},
    }

    def __init__(self, reader: Callable[[], dict[str, Any]]) -> None:
        self._reader = reader

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            limit = max(1, int(args.get("limit") or 20))
        except (TypeError, ValueError):
            limit = 20
        report = await asyncio.to_thread(self._reader)
        unreadable = report.get("unreadable") or []
        rows = report.get("projects") or []
        lines: list[str] = []
        if unreadable:
            lines.append("Some project copies could not be read, so this list may be missing projects:")
            lines.extend(f"- {sentence}" for sentence in unreadable)
        for row in rows[:limit]:
            cid = str(row.get("conversation_id") or "")
            detail = str(row.get("detail") or "")
            lines.append(
                f"- {row.get('title') or cid} ({cid}): {row.get('state') or ''}{' -- ' + detail if detail else ''}"
            )
        if not rows:
            lines.append("No self-change project is listed." if unreadable else "No self-change project is going.")
        return ToolResult(ok=True, data="\n".join(lines))


def register_self_projects_tools(registry: Any, reader: Callable[[], dict[str, Any]]) -> None:
    registry.register(SelfProjectsTool(reader))


__all__ = ["SelfProjectsTool", "register_self_projects_tools"]
