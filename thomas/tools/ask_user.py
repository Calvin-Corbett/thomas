"""``ask_user``: the model asks the person a structured question and waits.

Frontier parity with Claude Code's AskUserQuestion and ChatGPT's clarifying
prompts. The tool registers the question in the shared book, the UI or the
CLI renders the options, the answer comes back as this tool's result and the
same run continues. If nobody answers in time the model is told so and told
to proceed on a stated assumption, never to spin.
"""

from __future__ import annotations

import asyncio
from typing import Any

from thomas.core.session_scope import active_session_id
from thomas.core.user_questions import UserQuestionBook, question_book
from thomas.tools.base import Tool, ToolResult

DEFAULT_TIMEOUT_S = 20 * 60.0


class AskUserTool(Tool):
    name = "ask_user"
    category = "interaction"
    description = (
        "Ask the person one clear question with 2-4 short options when a decision is theirs to make and the "
        "answer changes what you build. The run pauses until they answer. Do not use it for things you can "
        "decide yourself, verify in the code, or find in the task."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question, one sentence, ending in a question mark."},
            "options": {
                "type": "array",
                "description": "2 to 4 choices. Put your recommended one first and say so in its description.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "1-5 words shown on the button."},
                        "description": {"type": "string", "description": "What choosing it means, one line."},
                    },
                    "required": ["label"],
                },
            },
            "multi_select": {"type": "boolean", "description": "Let the person pick more than one. Default false."},
            "allow_free_text": {
                "type": "boolean",
                "description": "Offer a free-text answer as well (or instead of options). Default false.",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    def __init__(self, *, book: UserQuestionBook | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._book = book or question_book()
        self._timeout_s = float(timeout_s)

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        question = str(args.get("question") or "").strip()
        if not question:
            return ToolResult(ok=False, error="ask_user needs a question.")
        raw_options = args.get("options") or []
        options: list[dict[str, str]] = []
        for item in raw_options if isinstance(raw_options, list) else []:
            if isinstance(item, str):
                item = {"label": item}
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if label:
                options.append({"label": label, "description": str(item.get("description") or "").strip()})
        allow_free_text = bool(args.get("allow_free_text", False))
        if len(options) < 2 and not allow_free_text:
            return ToolResult(ok=False, error="ask_user needs at least two options, or allow_free_text=true.")
        if len(options) > 6:
            options = options[:6]

        record = self._book.ask(
            question=question,
            options=options,
            multi_select=bool(args.get("multi_select", False)),
            allow_free_text=allow_free_text,
            session_id=active_session_id(),  # bound by the runner; a model-supplied _session_id is ignored
        )
        try:
            answer = await self._book.wait(record.id, timeout_s=self._timeout_s)
        except asyncio.TimeoutError:
            minutes = max(1, int(round(self._timeout_s / 60))) if self._timeout_s >= 60 else 0
            wait_text = f"{minutes} minutes" if minutes else f"{self._timeout_s:g} seconds"
            return ToolResult(
                ok=False,
                error=(
                    f"No answer from the person within {wait_text}. Do not ask again. Proceed with your best "
                    "assumption, state the assumption plainly in your reply, and make it easy to change later."
                ),
            )
        selected = list(answer.get("selected") or [])
        other = str(answer.get("other") or "")
        summary = ", ".join(selected) if selected else (other or "(no selection)")
        return ToolResult(
            ok=True,
            data={
                "question": question,
                "selected": selected,
                "other": other,
                "answer": summary if not (selected and other) else f"{summary}; note: {other}",
            },
        )


def register_ask_user_tool(registry: Any) -> None:
    registry.register(AskUserTool())


__all__ = ["AskUserTool", "DEFAULT_TIMEOUT_S", "register_ask_user_tool"]
