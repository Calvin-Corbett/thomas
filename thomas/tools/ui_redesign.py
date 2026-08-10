"""Let Thomas turn on Redesign mode himself.

When someone says "I don't like how this looks", the useful reply is not a
paragraph about where the settings live — it is putting them straight into the
mode where they point at the thing and say what is wrong.

Natural-language UI control was deliberately removed from the chat stream (see
``chat_v2_ui_control``); the sanctioned route is a structured capability. This
is that capability. Calling it emits a ``tool_start`` event carrying this
tool's name, which the browser already receives, and the shell turns Redesign
mode on when it sees it.

The tool deliberately does NOT select anything or make any change. It arms the
mode and hands control back to the person — what gets picked, and whether
anything is applied at all, stays their decision.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult

_TOOL_NAME = "ui.redesign"


class RedesignUiTool(Tool):
    name = _TOOL_NAME
    category = "ui"
    description = (
        "Turn on Redesign mode in the user's Thomas window so they can point at "
        "parts of the interface and say what should change. Use this when they "
        "say they dislike, want to change, move, resize, recolour, rename, or "
        "restyle something they can see on screen — instead of describing where "
        "settings live. The cursor becomes a hammer and a banner explains the "
        "mode. Do not use it for changes to files, data, or behaviour."
    )
    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": (
                    "One short sentence shown to the user saying what you understood "
                    "they want to change, e.g. 'the sidebar icons look wrong'."
                ),
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        reason = str((args or {}).get("reason") or "").strip()[:200]
        # The browser acts on the tool_start event; this result is what Thomas
        # reads back, so it tells him what the user is now looking at and what
        # he should say next. It never claims a change was made.
        return ToolResult(
            ok=True,
            data={
                "mode": "redesign",
                "armed": True,
                "reason": reason,
                "say_next": (
                    "Redesign mode is now on in the user's window. Their cursor is a "
                    "hammer and a banner reads 'Redesign mode'. Tell them to click the "
                    "parts they want changed — they can pick several — then press Lock "
                    "in and type what should be different. Nothing has changed yet."
                    + (f" They were talking about: {reason}" if reason else "")
                ),
            },
        )


def register_ui_redesign_tools(registry: Any) -> None:
    """Register the Redesign-mode capability."""
    registry.register(RedesignUiTool())


__all__ = ["RedesignUiTool", "register_ui_redesign_tools"]
