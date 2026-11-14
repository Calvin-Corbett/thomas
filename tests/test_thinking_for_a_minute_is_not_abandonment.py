"""An agent that pauses to think must not have its work reassigned.

`DEFAULT_MAX_IDLE_MINUTES` was 1.0. An agent that thinks, runs a test suite, or
waits on the gate ladder is quiet for longer than a minute as a matter of course,
so the sweep declared live agents dead and handed their tasks to someone else.

Measured on 2026-09-09: one sweep marked two agents inactive, one of them at
**1.01 minutes** idle while actively committing, the other at 13 minutes having
just sent a detailed status report.

The reassignment is not the worst of it. The task lands in Up For Grabs while it is
still in Active Tasks, so the board is self-inconsistent; the claims gate then
refuses that agent, and the refusal cascades through every gate that reads the
board. An agent that paused for sixty seconds could put itself into a state it
could not commit its way out of. That is the likeliest reason several agents
reported being blocked with nothing obviously wrong.

Abandonment and liveness are different questions and cannot share a number. The
same mistake in a different place is `agent_presence.DEFAULT_STALE_SECONDS = 120`,
which is fine as a heartbeat signal and was separately being used to decide who
still holds scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from crew.tasks.base import (  # noqa: E402
    DEFAULT_MAX_AGENT_SILENCE_MINUTES,
    DEFAULT_MAX_IDLE_MINUTES,
    DEFAULT_SESSION_LEASE_MINUTES,
)

from thomas.core.agent_presence import DEFAULT_RECENT_ACTIVITY_SECONDS  # noqa: E402

# Long enough that a real agent does it routinely without being gone.
A_LONG_THINK_MINUTES = 10.0


def test_a_ten_minute_think_is_not_abandonment():
    """The load-bearing case. At the old value of 1.0 this failed."""
    assert DEFAULT_MAX_IDLE_MINUTES > A_LONG_THINK_MINUTES, (
        f"an agent quiet for {A_LONG_THINK_MINUTES} minutes would have its work reassigned"
    )


def test_silence_and_lease_are_also_abandonment_windows():
    """All three decide 'is this agent gone', so all three need the same answer."""
    assert DEFAULT_MAX_AGENT_SILENCE_MINUTES > A_LONG_THINK_MINUTES
    assert DEFAULT_SESSION_LEASE_MINUTES > A_LONG_THINK_MINUTES


def test_the_sweep_agrees_with_the_presence_layer():
    """Two thresholds for 'gone' that disagree produce a window with no owner.

    Below the shorter one an agent holds scope but has lost its task; above it the
    reverse. Keeping them equal means scope and tasks are released at one moment.
    """
    assert DEFAULT_MAX_IDLE_MINUTES * 60 >= DEFAULT_RECENT_ACTIVITY_SECONDS


def test_it_still_expires_eventually():
    """Protection must not weaken into 'never sweep'. A dead agent must let go."""
    assert DEFAULT_MAX_IDLE_MINUTES < 24 * 60, "a threshold this long is the claim-rot bug again"
