"""The watchdog that cancels the stream honours the effort the user chose.

Two watchdogs guard a delegated worker and they disagreed. `_supervisor_worker_timeout_s`
reads the effort dial and grants 360s for "max"/"exhaustive" — the Thorough setting in
the UI. `_next_worker_event`, which is the one that actually cancels the event stream,
took no effort argument at all and always used the 120s idle constant.

The stricter spelling wins, so the dial was inert: pick Thorough, get killed at two
minutes anyway. And the kill is not gentle — the timeout path cancels the pending
`__anext__()`, which destroys the generator, after which StopAsyncIteration reads as
"the worker said nothing" rather than "we stopped listening".

The invariant these tests pin is agreement, not a number: whatever window the
supervisor grants for a given effort is the window the stream actually gets. Pinning
360 alone would go stale the moment either constant moved.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from thomas.server.chat_delegation_deliverable import _WorkerRetry
from thomas.server.chat_delegation_runner import (
    _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S,
    _next_worker_event,
    _supervisor_worker_timeout_s,
)
from thomas.server.chat_delegation_worker_config import _WORKER_IDLE_EVENT_TIMEOUT_S


class _SilentStream:
    """A worker that is thinking and has not emitted anything yet."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def __aiter__(self):  # noqa: ANN204 - test double
        return self

    async def __anext__(self):  # noqa: ANN204 - test double
        await asyncio.sleep(self.delay)
        return {"type": "progress", "text": "still working"}


def test_the_stream_watchdog_can_be_told_how_long_to_wait() -> None:
    """Without this parameter the effort dial cannot reach the watchdog at all."""

    params = inspect.signature(_next_worker_event).parameters
    assert "timeout_s" in params, (
        "_next_worker_event takes no timeout, so it can only use the fixed idle "
        "constant and the Thorough setting is inert"
    )


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        ("max", _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S),
        ("exhaustive", _MAX_EFFORT_IDLE_EVENT_TIMEOUT_S),
        ("balanced", _WORKER_IDLE_EVENT_TIMEOUT_S),
        ("cheap", _WORKER_IDLE_EVENT_TIMEOUT_S),
    ],
)
def test_the_two_watchdogs_agree_for_every_effort(effort: str, expected: float) -> None:
    assert _supervisor_worker_timeout_s({"effort": effort}, has_progress=True) == expected


def test_a_thorough_run_gets_more_than_the_default_window() -> None:
    """The whole point of the dial. If these ever equal, Thorough means nothing."""

    thorough = _supervisor_worker_timeout_s({"effort": "max"}, has_progress=True)
    standard = _supervisor_worker_timeout_s({"effort": "balanced"}, has_progress=True)
    assert thorough > standard


def test_the_watchdog_still_fires_when_a_worker_is_genuinely_silent() -> None:
    """Widening the window must not remove the guard: a hung worker still ends.

    The timeout path raises `_WorkerRetry` rather than returning None -- returning
    None is the StopAsyncIteration case, which means the worker finished. The two
    must stay distinguishable, because conflating them is how "we stopped listening"
    became "the worker said nothing".
    """

    async def go() -> object:
        return await _next_worker_event(_SilentStream(5.0), saw_event=True, timeout_s=0.05)

    with pytest.raises(_WorkerRetry, match="no next event"):
        asyncio.run(go())


def test_an_event_that_arrives_inside_the_window_is_returned() -> None:
    """The control. A test that only proves timeouts happen would pass on a
    watchdog that fired instantly and killed every run."""

    async def go() -> object:
        return await _next_worker_event(_SilentStream(0.01), saw_event=True, timeout_s=5.0)

    event = asyncio.run(go())
    assert event is not None and event.get("type") == "progress"
