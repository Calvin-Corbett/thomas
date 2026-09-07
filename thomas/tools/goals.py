"""``goal.add`` / ``goal.list`` / ``goal.done``: standing requirements for a project.

A goal is what the acceptance contract holds every turn to; it stays open
and is checked again each turn (see ``thomas.core.goal_book``). These tools
let Thomas record one when you state it, list them, and retire one that no
longer applies. A goal that holds is not closed: that is the normal state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core import goal_book
from thomas.tools.base import Tool, ToolResult


class GoalAddTool(Tool):
    name = "goal.add"
    category = "goals"
    description = (
        "Record a standing goal for this project: a requirement every later turn is held to. It stays open; "
        "a goal that holds today is still checked tomorrow. Use it when the user states something that must "
        "stay true (a quality bar, a constraint, an outcome), not for one-off steps."
    )
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The goal, in one sentence"}},
        "required": ["text"],
    }

    def __init__(self, root: Path):
        self._root = Path(root)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            goal = goal_book.add_goal(self._root, str(args.get("text") or ""))
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc))
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not save the goal: {exc}")
        return ToolResult(ok=True, data=f"goal {goal['id']} added: {goal['text']}")


class GoalListTool(Tool):
    name = "goal.list"
    category = "goals"
    description = "List this project's standing goals, and the retired ones when include_done is true."
    parameters = {
        "type": "object",
        "properties": {"include_done": {"type": "boolean", "description": "Also list retired goals (default false)"}},
    }

    def __init__(self, root: Path):
        self._root = Path(root)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        goals = goal_book.list_goals(self._root, include_done=bool(args.get("include_done")))
        if not goals:
            return ToolResult(ok=True, data="no goals recorded for this project")
        lines = []
        for g in goals:
            state = "retired" if g.get("done") else "standing"
            note = f" ({g.get('note')})" if g.get("note") else ""
            lines.append(f"{g.get('id')} [{state}] {g.get('text')}{note}")
        return ToolResult(ok=True, data="\n".join(lines))


class GoalDoneTool(Tool):
    name = "goal.done"
    category = "goals"
    description = (
        "Retire a goal that no longer applies (the user dropped or replaced it), not because it holds: a standing "
        "goal that holds stays open and is checked again every turn. Say why in note."
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "The goal id from goal.list, e.g. g1"},
            "note": {"type": "string", "description": "Why it no longer applies"},
        },
        "required": ["id"],
    }

    def __init__(self, root: Path):
        self._root = Path(root)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        goal_id = str(args.get("id") or "").strip()
        try:
            closed = goal_book.close_goal(self._root, goal_id, note=str(args.get("note") or ""))
        except OSError as exc:
            return ToolResult(ok=False, error=f"could not save the goal: {exc}")
        if not closed:
            return ToolResult(ok=False, error=f"no open goal with id {goal_id!r}; see goal.list")
        return ToolResult(ok=True, data=f"goal {goal_id} retired")


def register_goal_tools(registry: Any, root: Path) -> None:
    registry.register(GoalAddTool(root))
    registry.register(GoalListTool(root))
    registry.register(GoalDoneTool(root))


__all__ = ["GoalAddTool", "GoalDoneTool", "GoalListTool", "register_goal_tools"]
