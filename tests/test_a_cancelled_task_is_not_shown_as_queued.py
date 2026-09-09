"""A task the owner stopped must not be displayed as work still waiting.

`cancelled` was the ONE state in `task_bot_states.VALID_STATES` with no entry in
Mission Control's `_DELEGATION_STATE_ROOM_STATUS`, and the lookup falls back to
``("inbox", "queued")``. So a run the owner deliberately stopped appeared on the
board as QUEUED work still waiting to start.

It also missed the terminal set, which was an inline literal
``{"completed", "verified", "failed", "abandoned"}`` sitting three lines under a
comment that reads:

    FREEZE elapsed for finished work: a task that ran for 3 minutes must not
    display "7h" just because it finished 7 hours ago.

A cancelled task is finished, so its elapsed time ticked up live forever --
exactly the bug that comment exists to prevent.

Both sets are now derived from the writer's own vocabulary rather than spelled
out a second time, because the defect was never a wrong value: it was two
vocabularies for the same idea, the same shape as an icon and its heading being
chosen by two different failure tests.

`("done", "cancelled")` rather than `("review", "failed")`: stopping a run on
purpose is an ending, not something to go and look at, and `task_bot_states`
says so at its own line -- "'cancelled' is its own ending. Stopping a run on
purpose is not a failure."
"""

from __future__ import annotations

# From task_bot_runtime, not task_bot_states: the latter is an untracked
# in-flight split of the former, so a tracked file that imports it breaks a fresh
# checkout. task_bot_runtime exports both names before and after that split.
from thomas.core.task_bot_runtime import TERMINAL_STATES, VALID_STATES
from thomas.server.routes.mission_control_routes import (
    _DELEGATION_ACTIVE_STATES,
    _DELEGATION_STATE_ROOM_STATUS,
    _DELEGATION_TERMINAL_STATES,
)


def test_every_real_state_has_a_room() -> None:
    """The fallback is ("inbox", "queued"), so a gap here invents pending work."""

    missing = sorted(VALID_STATES - set(_DELEGATION_STATE_ROOM_STATUS))
    assert not missing, (
        f"{missing} have no Mission Control mapping, so they fall back to "
        '("inbox", "queued") and are displayed as work still waiting to start'
    )


def test_every_terminal_state_is_treated_as_finished() -> None:
    """Otherwise the elapsed timer runs forever on work that already ended."""

    missing = sorted(TERMINAL_STATES - _DELEGATION_TERMINAL_STATES)
    assert not missing, (
        f"{missing} are terminal to the state machine but not to Mission "
        "Control, so their elapsed time keeps counting up after they ended"
    )


def test_a_cancelled_task_is_not_queued_and_not_active() -> None:
    room, status = _DELEGATION_STATE_ROOM_STATUS["cancelled"]
    assert (room, status) != ("inbox", "queued"), (
        "a cancelled task is shown as queued work waiting to start"
    )
    assert status != "queued" and room != "inbox"
    assert "cancelled" not in _DELEGATION_ACTIVE_STATES, (
        "a cancelled task is counted among the active ones"
    )
    assert "cancelled" in _DELEGATION_TERMINAL_STATES


def test_cancelling_is_not_reported_as_failing() -> None:
    """`task_bot_states` is explicit that a deliberate stop is not a failure."""

    _, status = _DELEGATION_STATE_ROOM_STATUS["cancelled"]
    assert status != "failed", (
        "a run the owner stopped on purpose is reported as failed; "
        "task_bot_states says \"'cancelled' is its own ending. Stopping a run "
        'on purpose is not a failure."'
    )


def test_the_terminal_set_is_derived_rather_than_retyped() -> None:
    """The defect was two vocabularies, not one wrong value.

    If someone re-spells the set inline, it can drift from TERMINAL_STATES again
    and this whole class comes back.
    """

    import inspect

    from thomas.server.routes import mission_control_routes

    source = inspect.getsource(mission_control_routes)
    assert 'is_terminal = state in {"completed"' not in source, (
        "the terminal check is back to an inline literal, which is how it came "
        "to disagree with TERMINAL_STATES about `cancelled` in the first place"
    )
    assert "_DELEGATION_TERMINAL_STATES = TERMINAL_STATES" in source, (
        "the terminal set is no longer derived from task_bot_states.TERMINAL_STATES"
    )
