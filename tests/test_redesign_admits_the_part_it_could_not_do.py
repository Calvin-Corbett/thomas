"""Redesign admits the part of an ask that its locked target cannot carry (2026-09-06).

You asked that AI Redesign be able to change anything. Pointing at the
"Workspaces" heading in the sidebar and asking "hide this whole Workspaces
section, I never use it" hid the heading, reported "Changed 1 thing", and left
Mission Control, System Map and the rest of the section on screen. The model
can only touch the locked targets, and nothing told it what to do when the
ask reaches beyond them, so it did the part it could and reported the whole
as done. The contract now says: do what the target allows AND put the target
in "unsupported" with what remains and where to point next. The runtime
already keeps a target that appears in both lists, so the result carries
both the change and the admission.
"""

from __future__ import annotations

from thomas.server.routes import ui_redesign_runtime as rt

TARGETS = [
    {"uiId": "chat.sidebar.workspaces.heading", "label": "Workspaces heading", "text": "WORKSPACES", "component": "h3"}
]


def test_the_contract_tells_the_model_what_to_do_with_an_ask_wider_than_its_target() -> None:
    hint = rt._SCHEMA_HINT.lower()
    assert "beyond" in hint and "unsupported" in hint
    assert "point at" in hint


def test_a_target_can_be_changed_and_still_admit_the_rest() -> None:
    layout, rejected = rt._plan_layout([{"target": 0, "hidden": True}], TARGETS)
    assert rejected == [] and layout and layout[0]["hidden"] is True
    admitted = rt._plan_unsupported(
        [
            {
                "target": 0,
                "reason": "only the heading is locked; the section's items are separate elements, point at them too",
            }
        ],
        TARGETS,
    )
    assert admitted and admitted[0]["target_index"] == 0 and "point at them" in admitted[0]["reason"]


def test_the_model_is_told_the_current_size_so_a_relative_size_ask_can_be_met() -> None:
    """ "Make this search box twice as tall and round its corners fully" rounded the
    corners and dropped the height without a word: the target line never said how
    tall the box was, so twice as tall had nothing to be computed from."""
    lines = rt._target_lines(
        [
            {
                "uiId": "chat.sidebar~~label > input",
                "label": "search box",
                "component": "input",
                "box": {"width": 208, "height": 29},
            }
        ]
    )
    assert "208" in lines and "29" in lines and "px" in lines
    hint = rt._SCHEMA_HINT.lower()
    assert "twice as" in hint or "relative size" in hint
