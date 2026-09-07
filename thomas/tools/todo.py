"""``todo.write``: the model keeps a visible checklist for multi-step work.

Frontier parity with Claude Code's TodoWrite. The list lives in the shared
todo book; the chat page polls it and draws the plan and its progress under
the reply. The tool touches nothing else, so the policy treats it as safe.
"""

from __future__ import annotations

from typing import Any

from thomas.core.session_scope import active_session_id
from thomas.core.todo_book import MAX_ITEMS, STATUSES, TodoBook, normalize_items, todo_book
from thomas.tools.base import Tool, ToolResult


class TodoWriteTool(Tool):
    name = "todo.write"
    description = (
        "Keep a short visible checklist while you work on anything with three or more steps. "
        "Call it once with the plan (every item pending, the first in_progress), then again each time an "
        "item finishes: the whole list is replaced on every call, so send every item every time. Exactly one "
        "item may be in_progress. An empty items list clears the checklist. Do not use it for a single step."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "What the list is for, a few words."},
            "items": {
                "type": "array",
                "description": f"The full list, in order (at most {MAX_ITEMS}).",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "One step, imperative, short."},
                        "status": {
                            "type": "string",
                            "enum": list(STATUSES),
                            "description": "pending, in_progress or done.",
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        "required": ["items"],
    }

    def __init__(self, *, book: TodoBook | None = None) -> None:
        self._book = book or todo_book()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raw_items = args.get("items")
        if raw_items is None or not isinstance(raw_items, list):
            return ToolResult(ok=False, error="todo.write needs an items list (send [] to clear).")
        items = normalize_items(raw_items)
        if raw_items and not items:
            return ToolResult(ok=False, error="Every item needs non-empty text.")
        active = [i["text"] for i in items if i["status"] == "in_progress"]
        if len(active) > 1:
            return ToolResult(
                ok=False, error="Only one item may be in_progress at a time; mark the others pending or done."
            )
        # The session comes from the runner, never from the model's arguments.
        record = self._book.write(active_session_id(), title=str(args.get("title") or ""), items=items)
        if record is None:
            return ToolResult(ok=True, data={"cleared": True, "count": 0, "done": 0, "remaining": 0, "in_progress": ""})
        done = sum(1 for i in items if i["status"] == "done")
        return ToolResult(
            ok=True,
            data={
                "count": len(items),
                "done": done,
                "remaining": len(items) - done,
                "in_progress": active[0] if active else "",
                "title": record["title"],
            },
        )


def register_todo_tool(registry: Any) -> None:
    registry.register(TodoWriteTool())


__all__ = ["TodoWriteTool", "register_todo_tool"]
