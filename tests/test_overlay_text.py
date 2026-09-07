"""Redesign can change what an element SAYS, not only how it looks (2026-09-06).

You asked that AI Redesign be able to change anything. Pointing at the Build
list's "New build" button and asking "make this button green with white text
and change its label to Start a build" turned the button green and reported
"Changed 1 thing"; the label stayed. The overlay had no channel for text, so
the model could not name the change and the report did not admit the miss.
A layout entry now carries ``text``: the whole visible text of the element,
short, plain, no markup; the planner accepts it only for a target that shows
text, and says so when it cannot.
"""

from __future__ import annotations

from thomas.server.overlay import records
from thomas.server.routes import ui_redesign_runtime as rt

ANCHOR = {
    "exact": True,
    "fragile": False,
    "component": "button",
    "label": "New build button",
    "policy": "move resize",
    "path": "",
}
ADDRESS = "element:chat:desktop:build.newchat"


def _errors(value: dict) -> list[str]:
    return records._validate_element(ADDRESS, value, ANCHOR)


def test_a_text_value_is_a_valid_element_change() -> None:
    assert _errors({"x": 0, "y": 0, "text": "Start a build"}) == []
    assert _errors({"text": "Start a build"}) == []  # text alone is a change the overlay applies


def test_text_must_be_short_plain_and_canonical() -> None:
    assert any("text" in e for e in _errors({"text": "<b>Start</b>"}))
    assert any("text" in e for e in _errors({"text": "x" * 121}))
    assert any("text" in e for e in _errors({"text": " padded "}))
    assert any("text" in e for e in _errors({"text": "two\nlines"}))
    assert any("text" in e for e in _errors({"text": ""}))


def test_the_planner_accepts_text_for_a_target_that_shows_text() -> None:
    targets = [{"uiId": "build.newchat", "label": "New build button", "text": "New build", "component": "button"}]
    rows = [{"target": 0, "text": "Start a build", "style": {"color": "#ffffff"}}]
    out, rejected = rt._plan_layout(rows, targets)
    assert rejected == []
    assert out and out[0]["text"] == "Start a build" and out[0]["ui_id"] == "build.newchat"


def test_the_planner_refuses_text_for_a_target_that_shows_none() -> None:
    targets = [{"uiId": "chat.sidebar", "label": "sidebar", "text": "", "component": "aside"}]
    out, rejected = rt._plan_layout([{"target": 0, "text": "Hello"}], targets)
    assert out == []
    assert rejected and "text" in rejected[0]["reason"], rejected


def test_the_model_contract_names_the_text_channel() -> None:
    assert '"text"' in rt._SCHEMA_HINT and "what an element says" in rt._SCHEMA_HINT.lower()
    lines = rt._target_lines([{"uiId": "b", "label": "button", "text": "New build", "component": "button"}])
    assert "TEXT" in lines and "New build" in lines
