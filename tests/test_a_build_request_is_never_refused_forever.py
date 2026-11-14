"""A build request must not be refused outright.

Observed live on 2026-09-21. "Build dice.html ... then open it and confirm the
button works" came back:

    Task hand-off failed: Build task needs correction: uncited_acceptance

An ordinary request, refused. `submit_build_task` calls `validate_dispatch`
without `repair_attempts`, so it defaults to 0; `MAX_REPAIRS` is 2, so
`budget_spent` is always False, `dispatch_anyway` is always False, and
`may_dispatch` collapses to `ok`. The escape hatch was unreachable code and the
validator could refuse forever -- the one thing its own docstring says it must
never do, and what Rule 0 forbids.

There is no repair loop at that call site: chat sends one structured
`send_task` and intake either dispatches it or does not. So the repair budget
is not "untouched", it is *already spent* -- there is no second attempt to
spend it on. Saying so is what makes the designed behaviour reachable: the task
goes out, the uncited acceptance items are dropped, and the end state degrades
to `completed_unverified` rather than the work never starting.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.praxis.dispatch_validate import (
    END_STATE_UNVERIFIED,
    MAX_REPAIRS,
    UNCITED_ACCEPTANCE,
    validate_dispatch,
)

_PAYLOAD = {
    "instructions": "Build dice.html with a roll button.",
    "surface": "task",
    "kind": "code",
    "deliverable_format": "",
    "needs_build": True,
    "project": {"mode": "new"},
    # The shape the live model actually produced: acceptance that does not quote
    # the instructions verbatim.
    # `cites` must be a verbatim quote from `instructions`; this paraphrases,
    # which is exactly what the live model did.
    "acceptance": [{"id": "a1", "kind": "file_exists", "path": "dice.html", "cites": "the button must roll a number"}],
}


def test_an_uncited_acceptance_item_still_blocks_when_repairs_remain() -> None:
    """The validator is not being defanged: with a repair possible, it holds."""
    verdict = validate_dispatch(_PAYLOAD, repair_attempts=0)
    assert UNCITED_ACCEPTANCE in verdict.errors
    assert verdict.may_dispatch is False


def test_with_no_repair_left_the_task_goes_out_anyway() -> None:
    """Rule 0: the work starts, degraded and annotated, rather than never."""
    verdict = validate_dispatch(_PAYLOAD, repair_attempts=MAX_REPAIRS)
    assert verdict.may_dispatch is True
    assert verdict.dropped_acceptance == (0,), "the uncited item should be dropped, not silently kept"
    assert verdict.best_end_state == END_STATE_UNVERIFIED
    assert UNCITED_ACCEPTANCE in verdict.errors, "the reason must survive onto the card"


def test_intake_says_the_budget_is_spent_because_it_cannot_repair() -> None:
    """The call site is what decides. A reachable escape hatch nothing reaches
    is exactly the bug this file exists about, so pin the wiring."""
    src = (Path(__file__).resolve().parents[1] / "thomas" / "server" / "praxis" / "intake.py").read_text(
        encoding="utf-8"
    )
    assert "repair_attempts=" in src, "intake still lets repair_attempts default to 0, so it can refuse forever"
