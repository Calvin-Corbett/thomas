"""Finishing a run is not the same as satisfying what was asked.

The rubric's first row used to read

    complete the requested goal: <the entire goal, restated>   =>  met

with evidence amounting to "the process exited 0 and git shows a delta". Restating
someone's whole ask and stamping it `met` asserts that every requirement inside it
was satisfied. Nothing had examined any of them -- which is why every sub-criterion
directly beneath that row is honestly `unverified`.

The row now measures what it can actually see: whether the run finished without
error. The goal text moves into the evidence, and the requirement rows underneath
keep carrying the ask itself.

This matters beyond wording. `met` on that row is the only thing in a prose-goal
report that reads as success, and a person scanning the rubric sees their own
sentence next to a green word.
"""

from __future__ import annotations

from thomas.forge.anvil.run_report import _build_rubric_mapping

GOAL = (
    "Build countdown.html - a countdown timer with Start, Pause and Reset "
    "buttons that all work"
)


def _mapping(*, ok: bool = True, validations=None):
    return _build_rubric_mapping(
        GOAL,
        "",
        validations if validations is not None else [{"passed": True}],
        ok=ok,
        outcome="completed" if ok else "failed",
        reason="1 file(s) changed",
    )


def test_the_first_row_does_not_restate_the_goal_as_something_met() -> None:
    first = _mapping()[0]

    assert first["criterion"] == "the run finished without error"
    assert "complete the requested goal" not in first["criterion"]
    # The specific promise that read as verified must not appear beside "met".
    assert "Start, Pause and Reset" not in first["criterion"]
    assert first["status"] == "met"


def test_the_goal_text_is_not_lost() -> None:
    """Moved, not deleted -- the evidence still carries what was asked."""
    first = _mapping()[0]

    assert "Start, Pause and Reset" in first["evidence"]
    assert "outcome=completed" in first["evidence"]


def test_a_failed_run_still_reports_not_met() -> None:
    first = _mapping(ok=False)[0]

    assert first["status"] == "not_met"
    assert first["criterion"] == "the run finished without error"


def test_a_prose_goal_still_produces_the_unverified_requirement_row() -> None:
    """The honest half must survive this change: a prose goal has no bullets, so
    nothing was checked one by one, and the rubric has to say so."""
    rows = _mapping()

    unverified = [r for r in rows if r["status"] == "unverified"]
    assert unverified, f"no unverified row for a prose goal: {rows}"
    assert any("not individually verified" in r["evidence"] or "checklist" in r["evidence"] for r in unverified)


def test_a_checklist_goal_still_lists_each_requirement_unverified() -> None:
    goal = (
        "Build countdown.html. Requirements:\n"
        "- A Start button that begins counting down\n"
        "- A Reset button that returns the display to 00:00\n"
    )
    rows = _build_rubric_mapping(
        goal, "", [{"passed": True}], ok=True, outcome="completed", reason="1 file(s) changed"
    )

    assert rows[0]["criterion"] == "the run finished without error"
    criteria = [r["criterion"] for r in rows[1:]]
    assert any("Start button" in c for c in criteria), criteria
    assert any("Reset button" in c for c in criteria), criteria
    assert all(r["status"] == "unverified" for r in rows[1:]), rows[1:]
