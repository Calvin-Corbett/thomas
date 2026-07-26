"""A follow-up turn must not be failed for files nobody asked for."""

from __future__ import annotations

from thomas.server.chat_delegation_artifact_verification import (
    _explicit_request_text,
    _requested_names,
)

# Exactly what chat_delegation.py appends when it seeds a follow-up workspace.
SEEDED = (
    "rerun the chart\n\n"
    "[The workspace already contains the earlier deliverable(s): "
    "chart-data.csv, chart-data.xlsx, chart.png. Modify those files in place.]"
)


def test_the_seeded_workspace_note_is_not_a_request() -> None:
    """The single most common worker failure in Calvin's history.

    "rerun the chart" was failed with "missing exact requested artifact
    chart-data.xlsx" -- a file nobody had asked for. The note lists what the
    PREVIOUS run left behind so the worker edits those files instead of asking
    the user to re-upload them; the requested-artifact scanner read the names as
    a demand and required every one of them back.
    """
    assert _requested_names(SEEDED) == []


def test_a_real_request_in_the_same_prompt_still_counts() -> None:
    """The exclusion must be narrow: a genuine ask alongside the note stands."""
    prompt = (
        "rerun the chart and also save summary.md\n\n"
        "[The workspace already contains the earlier deliverable(s): "
        "chart-data.csv, chart-data.xlsx. Modify those files in place.]"
    )

    assert _requested_names(prompt) == ["summary.md"]


def test_the_users_own_words_survive_the_excision() -> None:
    assert _explicit_request_text(SEEDED).strip().startswith("rerun the chart")
    assert "chart-data.xlsx" not in _explicit_request_text(SEEDED)


def test_attachment_bodies_are_still_excluded() -> None:
    """The pre-existing exclusion must keep working."""
    prompt = "write me a guide\n\n[Attached documents]\nsee reference.docx for style\n"

    assert _requested_names(prompt) == []


def test_a_prompt_without_the_note_is_untouched() -> None:
    assert _requested_names("make me report.pdf") == ["report.pdf"]
