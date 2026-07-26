"""A follow-up must be able to SEE the file it was asked to change."""

from __future__ import annotations

from thomas.server.chat_delegation_artifact_verification import _requested_names
from thomas.server.chat_delegation_deliverable import prompt_needs_handoff
from thomas.server.chat_delegation_workspace import prompt_allows_workspace_seed


def test_an_edit_that_names_no_pronoun_still_gets_the_files() -> None:
    """The failure this fixes.

    "change tuesday to 9 and add sat 7" is plainly about the chart from one
    turn earlier, but it contains none of the pronouns the follow-up patterns
    look for. Seeding shared that strict gate, so nothing was copied, the
    worker opened an empty directory, produced nothing, and the run was
    recorded as failed(no_evidence).
    """
    for edit in (
        "change tuesday to 9 and add sat 7",
        "can you update that to include saturday",
        "change the title",
        "swap the colors",
    ):
        assert prompt_allows_workspace_seed(edit), edit


def test_a_self_contained_new_build_gets_a_clean_workspace() -> None:
    """The one case where earlier files are certainly irrelevant."""
    for fresh in (
        "make me a bar chart of my weekly miles: mon 3, tue 5",
        "build me a pong web game",
        "write me a poem about cats",
        "create a dashboard for my sales",
    ):
        assert not prompt_allows_workspace_seed(fresh), fresh


def test_seeding_is_strictly_more_permissive_than_the_handoff() -> None:
    """The two gates have opposite risk: attaching prior conversation can make a
    worker build the wrong thing, while withholding files makes an edit
    impossible. Anything that earns the handoff must also earn the files."""
    for followup in ("rerun the chart", "add a 6th row to it", "make it blue", "fix the typo in it"):
        assert prompt_needs_handoff(followup), followup
        assert prompt_allows_workspace_seed(followup), followup


def test_the_permissive_note_is_not_an_order() -> None:
    """A request that only MIGHT be a follow-up gets the files but not a
    directive to edit them -- otherwise a new build is told to modify a chart."""
    assert not prompt_needs_handoff("change tuesday to 9 and add sat 7")
    assert prompt_allows_workspace_seed("change tuesday to 9 and add sat 7")


def test_neither_note_is_read_as_a_request_for_those_files() -> None:
    """Both note forms name files; neither is the user asking for them."""
    directive = (
        "rerun the chart\n\n[The workspace already contains the earlier deliverable(s): "
        "chart-data.csv, chart.png. Modify those files in place.]"
    )
    permissive = (
        "change tuesday to 9\n\n[Earlier files from this conversation are already in the "
        "workspace: chart-data.csv, chart-data.xlsx. Use or edit them only if this request "
        "refers to them.]"
    )

    assert _requested_names(directive) == []
    assert _requested_names(permissive) == []


def test_an_empty_prompt_seeds_nothing() -> None:
    assert not prompt_allows_workspace_seed("")
    assert not prompt_allows_workspace_seed("   ")
