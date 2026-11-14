"""The Build lead's two tools for working with you mid-run: ``plan.update`` and ``ask.user``.

``plan.update`` is the Steps card: the lead writes its steps and marks them as they start and finish, and every call
becomes one ``plan`` event whose items carry when each step started and finished, so the card can show durations
without the browser guessing. ``ask.user`` is the one way the lead can stop and ask you something: the question goes
to the run's control folder (``run_control``), the card shows it, and the lead waits, with the pass clock stopped,
until you answer or 20 minutes pass.

Only the agent-loop lead gets them, and only on a run the server launched with a control folder; a run without one
is unchanged. Neither tool touches the project, which is why the translator reports them as reads.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .run_control import RunControl, now_ms

PLAN_STATUSES = ("pending", "in_progress", "completed", "blocked")
MAX_PLAN_ITEMS = 30
TOOL_NAMES = frozenset({"plan.update", "ask.user"})
_NO_ANSWER = "No answer in 20 minutes: go with the recommended option and say so in your reply."
_NO_ANSWER_NO_PICK = "No answer in 20 minutes: go with the option you judge best and say so in your reply."


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _stamp(previous: dict[str, Any] | None, status: str, now: int) -> tuple[int | None, int | None]:
    """``(started_at, done_at)`` for a step now at ``status``, given what it was in the previous plan."""
    started = previous.get("started_at") if previous else None
    done = previous.get("done_at") if previous else None
    if status == "pending":
        return None, None
    if status == "in_progress":
        return started or now, None
    if status == "completed":
        # A step that jumps straight from pending to done never said when it started; it keeps no start time
        # rather than an invented one.
        still_done = bool(previous and previous.get("status") == "completed" and done)
        return started, (done if still_done else now)
    return started, None  # blocked


class PlanUpdateTool(Tool):
    name = "plan.update"
    category = "build"
    description = (
        "Show the person your plan as a list of steps, and keep it current. Use it at the start of any task with "
        "three or more steps, and again whenever a step starts or finishes (or is blocked). Send the whole list "
        "every time; it replaces the previous one. owner is the helper doing that step (its title), empty for you."
    )
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "maxItems": MAX_PLAN_ITEMS,
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The step, in a few plain words"},
                        "status": {"type": "string", "enum": list(PLAN_STATUSES)},
                        "owner": {"type": "string", "description": "The helper doing this step; empty for you"},
                    },
                    "required": ["text", "status"],
                },
            }
        },
        "required": ["items"],
    }

    def __init__(self, emit: Callable[[dict[str, Any]], None]) -> None:
        self._emit = emit
        self._items: list[dict[str, Any]] = []
        self._next_id = 1

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        raw = args.get("items")
        if not isinstance(raw, list) or not raw:
            return ToolResult(ok=False, error="items must list at least one step")
        if len(raw) > MAX_PLAN_ITEMS:
            return ToolResult(ok=False, error=f"a plan holds at most {MAX_PLAN_ITEMS} steps")
        # Steps keep their identity by their words, so a step that is reworded is a new step.
        previous = {_clean(item["text"], 300).casefold(): item for item in self._items}
        now = now_ms()
        items: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                return ToolResult(ok=False, error="each step needs text and status")
            text = _clean(entry.get("text"), 300)
            status = str(entry.get("status") or "pending").strip().lower()
            if not text:
                return ToolResult(ok=False, error="a step has no text")
            if status not in PLAN_STATUSES:
                return ToolResult(ok=False, error=f"status must be one of {', '.join(PLAN_STATUSES)}")
            before = previous.pop(text.casefold(), None)
            if before is None:
                step_id, self._next_id = f"s{self._next_id}", self._next_id + 1
            else:
                step_id = before["id"]
            started_at, done_at = _stamp(before, status, now)
            items.append(
                {
                    "id": step_id,
                    "text": text,
                    "status": status,
                    "owner": _clean(entry.get("owner"), 80),
                    "started_at": started_at,
                    "done_at": done_at,
                }
            )
        self._items = items
        done = sum(1 for item in items if item["status"] == "completed")
        summary = f"{done} of {len(items)} done"
        self._emit({"fc": "plan", "text": summary, "items": [dict(item) for item in items]})
        return ToolResult(ok=True, data=f"Plan shown to the person: {summary}.")


class AskUserTool(Tool):
    name = "ask.user"
    category = "build"
    description = (
        "Ask the person to make a decision that is genuinely theirs: taste, scope, or a trade-off with no right "
        "answer. Give 2 to 4 options, each a short label with a one-line description, and name the one you "
        "recommend. Never use it to ask permission to continue, or to confirm something you can check yourself. "
        "You wait for the answer (up to 20 minutes); other work you started keeps going."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The decision, as one plain question"},
            "options": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "A few words"},
                        "description": {"type": "string", "description": "What choosing it means"},
                    },
                    "required": ["label"],
                },
            },
            "recommended": {"type": "string", "description": "The label of the option you recommend"},
            "allow_free_text": {"type": "boolean", "description": "Whether the person may answer in their own words"},
        },
        "required": ["question", "options"],
    }

    def __init__(self, control: RunControl) -> None:
        self._control = control

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        question = " ".join(str(args.get("question") or "").split())[:1000]
        if not question:
            return ToolResult(ok=False, error="question is empty")
        raw = args.get("options")
        if not isinstance(raw, list) or not 2 <= len(raw) <= 4:
            return ToolResult(ok=False, error="give 2 to 4 options")
        recommended = _clean(args.get("recommended"), 120).casefold()
        options: list[dict[str, Any]] = []
        for entry in raw:
            label = _clean(entry.get("label") if isinstance(entry, dict) else entry, 120)
            if not label:
                return ToolResult(ok=False, error="every option needs a label")
            if any(option["label"].casefold() == label.casefold() for option in options):
                return ToolResult(ok=False, error=f"two options are both labelled {label!r}")
            description = _clean(entry.get("description"), 400) if isinstance(entry, dict) else ""
            options.append({"label": label, "description": description, "recommended": label.casefold() == recommended})
        default = next((option["label"] for option in options if option["recommended"]), "")
        _question_id, answer = await self._control.ask(
            question, options, allow_free_text=bool(args.get("allow_free_text")), default=default
        )
        if answer is None:
            return ToolResult(ok=True, data=_NO_ANSWER if default else _NO_ANSWER_NO_PICK)
        if any(option["label"].casefold() == answer.strip().casefold() for option in options):
            return ToolResult(ok=True, data=f"The person chose: {answer.strip()}")
        return ToolResult(ok=True, data=f"The person answered in their own words: {answer.strip()}")


def lead_tools(control: RunControl, emit: Callable[[dict[str, Any]], None]) -> list[Tool]:
    """The lead's tools for one run. Made once per run, so the plan carries its step times across passes."""
    return [PlanUpdateTool(emit), AskUserTool(control)]


__all__ = ["MAX_PLAN_ITEMS", "PLAN_STATUSES", "TOOL_NAMES", "AskUserTool", "PlanUpdateTool", "lead_tools"]
