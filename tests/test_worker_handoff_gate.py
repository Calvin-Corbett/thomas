"""The recent-conversation handoff must only attach to follow-up tasks.

A self-contained request must NOT receive the prior-turns handoff: feeding it
earlier task-requests made the worker build the wrong deliverable (a "Build me a
Pong game" task produced an earlier turn's starfield). The handoff is reserved for
prompts that actually reference prior dialogue ("make it blue"). Locks in
``prompt_needs_handoff``.
"""

from __future__ import annotations

import pytest

from thomas.server.chat_delegation_deliverable import prompt_needs_handoff, quality_tier_clause


@pytest.mark.parametrize(
    "prompt",
    [
        "Build me a playable Pong web game as a single self-contained index.html",
        "Build me a colorful animated starfield web page",
        "Create a one-page PDF cheat sheet on how to make a french press",
        "add a dark mode toggle to the site",
        "research the Iran war",
        "write a python script that sorts a CSV by date",
        # GUARD: a fresh-build verb after a continuation adverb must STAY self-contained
        # so the wrong-deliverable bleed ("Build Pong" -> got starfield) cannot reopen.
        "now build me a snake game",
        "then create a landing page for my startup",
        # GUARD: a fresh build whose CONTENT mentions "the same"/"again" is self-contained
        # (audit: over-attach). The content words must not trigger the handoff.
        "make a quiz app that shows the same question twice",
        "build a dashboard that updates itself again every minute",
    ],
)
def test_self_contained_requests_get_no_handoff(prompt: str) -> None:
    assert prompt_needs_handoff(prompt) is False, f"self-contained request should NOT pull handoff: {prompt!r}"


@pytest.mark.parametrize(
    "prompt",
    [
        "make it blue",
        "change it to use arrow keys",
        "do the same again but bigger",
        "now tweak the colors",
        "redo that with a dark background",
        "update it to add a score",
        "keep going",
        # Continuation adverb + modification verb with NO stated target — needs the
        # prior turn to know WHAT to modify (regression: was treated as self-contained).
        "now add a high score",
        "also include a restart button",
        "then remove the sidebar",
        "now add a leaderboard to my app",
        # Bare/visual edits with the pronoun elided (audit: under-attach).
        "smaller",
        "make the text smaller",
        "use a different color",
        "change the font",
        "dark mode",
        # List-references to a previously presented set (audit: under-attach).
        "the second one but red",
        "the first one but in dark mode",
        "give me another one",
        "another one",
    ],
)
def test_referential_followups_get_handoff(prompt: str) -> None:
    assert prompt_needs_handoff(prompt) is True, f"referential follow-up SHOULD pull handoff: {prompt!r}"


@pytest.mark.parametrize(
    "prompt",
    [
        # Ambiguous verbs used as NOUNS in a self-contained build request must NOT
        # re-attach the handoff (would partially reopen the wrong-deliverable bleed).
        "build a continue button for the form",
        "write a redo function for the editor",
        "make a tweak tool for the settings page",
        "create a revert script",
    ],
)
def test_ambiguous_verb_nouns_do_not_pull_handoff(prompt: str) -> None:
    assert prompt_needs_handoff(prompt) is False, f"ambiguous-verb-as-noun must NOT pull handoff: {prompt!r}"


@pytest.mark.parametrize(
    "prompt",
    [
        # The SAME verbs as a LEADING command ARE follow-ups.
        "continue",
        "tweak the colors",
        "redo that with a darker background",
        "keep going",
        "revert the last change",
    ],
)
def test_leading_command_verbs_pull_handoff(prompt: str) -> None:
    assert prompt_needs_handoff(prompt) is True, f"leading follow-up command SHOULD pull handoff: {prompt!r}"


def test_empty_prompt_does_not_pull_handoff() -> None:
    assert prompt_needs_handoff("") is False
    assert prompt_needs_handoff(None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("effort", "marker"),
    [
        ("cheap", "QUICK"),
        ("balanced", "STANDARD"),
        ("diligent", "STANDARD"),
        ("optimal", "STANDARD"),
        ("max", "THOROUGH"),
        ("exhaustive", "THOROUGH"),
    ],
)
def test_quality_tier_clause_maps_effort_to_build_leanness(effort: str, marker: str) -> None:
    assert f"BUILD QUALITY = {marker}" in quality_tier_clause(effort, autonomy_level=4)


def test_quick_tier_forbids_scaffolding_even_at_full_autonomy() -> None:
    """The user's explicit Quick choice must keep the build lean regardless of autonomy
    (the autonomy<->effort coupling promotes pass COUNT, not build leanness)."""
    clause = quality_tier_clause("cheap", autonomy_level=4)
    assert "QUICK" in clause
    assert "scaffolding" in clause.lower() and "do not create" in clause.lower()
