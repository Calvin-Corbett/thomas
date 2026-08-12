"""A probe that guesses which control to press has no standing to call a game broken.

The browser harness decides which button starts a game by matching words in its
label. `star-catcher.html` offers "Start Over", "Start Game" and "Play Again";
the restart control comes first in the document, so it got clicked on a fresh
page where correctly nothing happens — and the harness reported a working game
as dead. Its canvas was painted the whole time. `freedom-transit.html` failed
the same way on the pause probe while actually responding to both a click and a
keypress.

That selector is a keyword classifier reading prose to make a semantic
judgement, and it failed exactly as that always does: a word match cannot tell
"Start Game" from "Start Over". Adding a visibility filter was not enough,
because the restart button is visible too.

So the probes are observations, not verdicts. Strong POSITIVE evidence when a
control does react; no evidence at all when it does not.
"""

from __future__ import annotations

from pathlib import Path

ANVIL = Path(__file__).resolve().parents[1] / "thomas" / "forge" / "anvil"
HARNESS = ANVIL / "web_artifact_smoke_assets.py"
SMOKE = ANVIL / "web_artifact_smoke.py"


def _harness() -> str:
    return HARNESS.read_text(encoding="utf-8")


def test_a_start_probe_that_saw_nothing_is_not_an_error() -> None:
    text = _harness()

    assert 'pushUnique(state.errors, "Start control produced no visible state change")' not in text
    assert "may not be the real start control" in text


def test_a_pause_probe_that_found_no_resume_is_not_an_error() -> None:
    text = _harness()

    assert 'pushUnique(state.errors, "Pause control produced no visible Resume control")' not in text
    assert "the pause may not have engaged" in text


def test_notes_are_a_declared_channel_separate_from_errors() -> None:
    """Without its own bucket a note would either be dropped or land back in
    `errors`, which is what failed the build."""
    text = _harness()

    assert "notes: []," in text
    assert "state.notes" in text


def test_a_note_reaches_the_summary_rather_than_being_dropped() -> None:
    """Demoting a check must not mean hiding it. The reader still needs to know
    a control was pressed and nothing happened."""
    text = SMOKE.read_text(encoding="utf-8")

    assert 'receipt.get("notes")' in text


def test_real_page_defects_still_fail() -> None:
    """The checks that READ the artifact are the ones that found true defects,
    and none of them are softened here.

    Comments are stripped before searching. An earlier version of this test
    matched the blank-canvas message anywhere in the file, and when that message
    was reworded the old phrasing survived inside a comment explaining the
    change -- so the guard kept passing while nothing produced the string. A
    test satisfied by a comment is the exact rubber stamp it exists to prevent,
    which is worth remembering: even a check written against this failure mode
    fell into it.
    """
    code_only = "\n".join(
        line for line in SMOKE.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("#")
    )

    assert 'receipt.get("errors")' in code_only, "uncaught JS errors must still fail"
    assert 'receipt.get("console_errors")' in code_only
    assert "local_failures" in code_only, "a missing LOCAL asset must still fail"
    assert "problems.append(" in code_only, "a blank canvas must still be recorded as a problem"
    assert "nothing was ever drawn to the canvas" in code_only
