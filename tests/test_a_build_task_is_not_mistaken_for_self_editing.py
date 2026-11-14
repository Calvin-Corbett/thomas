"""Asking for a web page must not read as asking to edit Thomas.

Observed 2026-09-20 by driving the UI. "Build me a single-file webpage with a
countdown timer" and "Write a self-contained hello.html page" both came back:

    Ran into a problem
    This task targets the project workspace, but project file access is not enabled.
    Failed

Neither asked for anything about Thomas. The chat model set `workspace` to
`project`, and `coordination_root` resolves that to the live Thomas checkout, so
an ordinary build request was gated as self-development and killed.

The tool's own wording invited it: `project` was described as "the currently
selected project", which is exactly what a person building a web page thinks
they are working in. Nothing said `project` means Thomas's own source code.

Two things are pinned here. The enum has to tell the model what it is really
choosing between, and the refusal -- when it is genuinely a self-edit -- has to
name what it would change and how to allow it, rather than naming an internal
control and stopping. Rule 0: nothing in Thomas says it cannot do something
because of a thing nobody engineered past.
"""

from __future__ import annotations

from thomas.core.send_task_tool import SEND_TASK_TOOL


def _workspace_description() -> str:
    schema = SEND_TASK_TOOL["function"]["parameters"]["properties"]
    return str(schema["workspace"]["description"]).casefold()


def test_the_workspace_enum_says_project_means_thomas_own_source() -> None:
    """The model cannot route correctly if the field does not say what it means."""
    description = _workspace_description()
    assert "thomas" in description, "the description never mentions Thomas's own code"


def test_the_workspace_enum_does_not_call_it_the_selected_project() -> None:
    """The wording that caused the misroute, kept out on purpose.

    "the currently selected project" is what a person building a web page
    believes they are in, so it pulled ordinary work onto the self-edit path.
    """
    assert "currently selected project" not in _workspace_description()


def test_isolated_is_named_as_the_choice_for_building_something_new() -> None:
    description = _workspace_description()
    assert "isolated" in description
    assert "new" in description
