"""Thomas arming Redesign mode is a structured capability, not prose.

Natural-language UI control was deliberately removed from the chat stream, so
"turn on redesign mode" must travel as a tool the browser recognises by name.
The tool arms the mode and stops there — it never selects anything and never
claims a change was made.
"""

from __future__ import annotations

import asyncio

from thomas.tools.registry import ToolRegistry
from thomas.tools.ui_redesign import register_ui_redesign_tools


def _tool():
    registry = ToolRegistry()
    register_ui_redesign_tools(registry)
    return registry.get("ui.redesign")


def test_the_tool_registers_under_the_name_the_shell_listens_for() -> None:
    tool = _tool()
    assert tool is not None
    # chat.html matches on this exact string; renaming it silently unwires the
    # only path Thomas has to turn the mode on.
    assert tool.name == "ui.redesign"


def test_arming_the_mode_never_claims_a_change_was_made() -> None:
    result = asyncio.run(_tool().safe_execute({"reason": "the sidebar icons look wrong"}))

    assert result.ok is True
    assert result.data["armed"] is True
    assert result.data["reason"] == "the sidebar icons look wrong"
    say = result.data["say_next"]
    assert "Nothing has changed yet" in say
    assert "hammer" in say


def test_the_reason_is_optional_and_bounded() -> None:
    result = asyncio.run(_tool().safe_execute({}))
    assert result.ok is True
    assert result.data["reason"] == ""

    long = asyncio.run(_tool().safe_execute({"reason": "x" * 500}))
    assert len(long.data["reason"]) == 200


def test_the_description_steers_it_at_looks_not_behaviour() -> None:
    description = _tool().description.lower()
    for cue in ("dislike", "point at", "on screen"):
        assert cue in description
    # It must not be reached for edits to files, data, or behaviour.
    assert "do not use it for changes to files, data, or behaviour" in description
