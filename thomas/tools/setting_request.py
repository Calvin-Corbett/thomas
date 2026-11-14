"""``settings.request_change``: Thomas asks you to change one of his settings, on a card.

Owner direction, 2026-09-22: "if he's going to change a toggle, it should be
announced ... he puts like a card ... says, hey, do you want me to do this? It
will require a password, here's what it is ... And then the user gets to
decide". And instead of sending you to Settings when a setting blocks him:
"you can just pull it up to them and show them, hey, here is a setting you need
to change. Press yes to change or no".

This tool can only *ask*. It posts a card and waits for your answer. The card is
where you decide. Raising a limit then needs your Windows PIN or password at the
one Thomas prompt, and the server enforces that whatever this tool, the card or
the model says (``thomas/server/dial_elevation.py``). Nothing in this file can
change a setting. "Gates are walls, not words": the wall is on the server.
"""

from __future__ import annotations

import asyncio
from typing import Any

from thomas.core.owner_wait import awaiting_owner
from thomas.core.session_scope import active_chat_id
from thomas.core.user_questions import UserQuestionBook, question_book
from thomas.tools.ask_user import DEFAULT_TIMEOUT_S
from thomas.tools.base import Tool, ToolResult

# The settings Thomas may ask about, with the labels the Chat menu shows
# (thomas/server/web/js/chat_preferences.js DIAL_FIELDS; a test pins the two
# together). ``dial`` is the server's name, ``client_key`` the page's.
SETTINGS: dict[str, dict[str, Any]] = {
    "autonomy": {
        "dial": "autonomy",
        "client_key": "autonomy",
        "label": "Autonomy",
        "values": {"1": "Chat only", "2": "Assist", "3": "Agent", "4": "Full autonomy", "5": "Autopilot"},
    },
    "file_access": {
        "dial": "file_access",
        "client_key": "fileAccess",
        "label": "Files Thomas can change",
        "values": {"workspace": "Thomas's own space", "project": "This project", "pc": "Anywhere on my PC"},
    },
    "internet": {
        "dial": "guardrails",
        "client_key": "guardrails",
        "label": "Reaching the internet",
        "values": {"fortress": "Off", "guarded": "Normal", "open": "Open"},
    },
}

# What the card answers with. "Yes" is sent only after the change was applied
# (and, for a raised limit, after the password prompt approved it).
APPROVED = "Yes"
DECLINED = "No"
PASSWORD_REFUSED = "Password not approved"


class SettingRequestTool(Tool):
    name = "settings.request_change"
    category = "self"
    description = (
        "Find any setting by name or plain words, including Express, planner, plugins and voice. "
        "Omit value to locate it. Returns a card; only the person's press can apply a change. "
        "Ask the owner to change one of your own settings when it is what stops the task: "
        "autonomy, the files you can change, or internet reach. Shows them a card saying what "
        "you want to change and why, with Yes / No; raising a limit also asks for their "
        "Windows PIN or password. Use this instead of telling them to go to Settings. It only "
        "asks: the change happens only if they approve, and applies from their next message."
    )
    parameters = {
        "type": "object",
        "properties": {
            "setting": {
                "type": "string",
                "description": "Setting name or words such as turn on Express or where is voice.",
            },
            "value": {
                "type": "string",
                "description": (
                    "The level you are asking for. autonomy: 1-5 (4 Full autonomy, 5 Autopilot); "
                    "file_access: workspace, project or pc; internet: fortress, guarded or open."
                ),
            },
            "reason": {
                "type": "string",
                "description": "One or two plain sentences: what you are trying to do and why this setting stops it.",
            },
        },
        "required": ["setting"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        *,
        book: UserQuestionBook | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        session_id: str = "",
    ) -> None:
        self._book = book or question_book()
        self._timeout_s = float(timeout_s)
        # The chat that asked. Chat's inline operator knows it and passes it; a
        # worker run binds it with session_scope. The card shows only in that chat.
        self._session_id = str(session_id or "")

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        setting = str(args.get("setting") or "").strip().lower()
        from thomas.core.settings_knowledge import provider

        controls = provider()
        if controls is not None:
            try:
                card = controls.request(setting, args.get("value"), self._session_id or active_chat_id())
            except (ValueError, KeyError) as exc:
                return ToolResult(ok=False, error=str(exc))
            if card.get("ok") is False:
                return ToolResult(ok=False, error=card.get("error", "Setting not found."))
            return ToolResult(ok=True, data={"card": card, "message": "Waiting for your press. Nothing has changed."})
        spec = SETTINGS.get(setting)
        if spec is None:
            return ToolResult(ok=False, error=f"Unknown setting. Ask about one of: {', '.join(sorted(SETTINGS))}.")
        value = str(args.get("value") or "").strip().lower()
        if value not in spec["values"]:
            return ToolResult(
                ok=False, error=f"{spec['label']} has no level {value!r}; use one of {list(spec['values'])}."
            )
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return ToolResult(ok=False, error="Say why: the card shows your reason to the owner.")

        value_label = spec["values"][value]
        record = self._book.ask(
            question=f"Thomas wants to change {spec['label']} to {value_label}",
            options=[{"label": APPROVED}, {"label": DECLINED}],
            session_id=self._session_id or active_chat_id(),
            kind="setting_change",
            details={
                "setting": setting,
                "dial": spec["dial"],
                "client_key": spec["client_key"],
                "label": spec["label"],
                "value": value,
                "value_label": value_label,
                "reason": reason,
            },
        )
        try:
            with awaiting_owner():
                answer = await self._book.wait(record.id, timeout_s=self._timeout_s)
        except asyncio.TimeoutError:
            return ToolResult(
                ok=False, error=f"No answer about {spec['label']}; it is unchanged. Do not ask again this turn."
            )
        chosen = (answer.get("selected") or [""])[0]
        if chosen == APPROVED:
            return ToolResult(
                ok=True,
                data=f"Approved. {spec['label']} is now {value_label}; it applies from the owner's next message.",
            )
        if chosen == PASSWORD_REFUSED:
            return ToolResult(
                ok=False,
                error=f"The owner pressed Yes but the password prompt was not approved; {spec['label']} is unchanged.",
            )
        return ToolResult(
            ok=False,
            error=f"The owner said no; {spec['label']} is unchanged. Carry on within it and say what it limits.",
        )


def register_setting_request_tool(registry: Any) -> None:
    registry.register(SettingRequestTool())


__all__ = [
    "APPROVED",
    "DECLINED",
    "PASSWORD_REFUSED",
    "SETTINGS",
    "SettingRequestTool",
    "register_setting_request_tool",
]
