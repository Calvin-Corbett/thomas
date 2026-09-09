"""A slow first token must not be mistaken for an empty response."""

from __future__ import annotations

import asyncio

import pytest

from thomas.server import chat_delegation_canvas_worker as worker


async def _slow_stream(first_token_delay: float):
    """A reasoning model: silent for a while, then it speaks."""
    await asyncio.sleep(first_token_delay)
    yield "thought"
    yield "answer"


@pytest.mark.asyncio
async def test_a_model_that_thinks_longer_than_a_poll_slice_is_still_heard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression that made every Canvas run fail.

    The cancellation poll used to be `wait_for(events.__anext__(), slice_s)` in a
    retry loop. wait_for cancels its awaitable on timeout, which tore the
    generator down mid-request; the next slice then got StopAsyncIteration and
    the run was reported as "0 events, 0 tokens" -- indistinguishable from a
    model that returned nothing. Codex thinks for 5-30s before its first token,
    so it never survived a single slice.
    """
    monkeypatch.setattr(worker, "_CANCEL_POLL_S", 0.02)
    events = _slow_stream(0.14)  # ~7 poll slices of thinking

    got = await worker._next_event(events, budget_s=5.0, cancelled=lambda: False)

    assert got == "thought"
    # ...and the generator is still alive for the rest of the response.
    assert await worker._next_event(events, budget_s=5.0, cancelled=lambda: False) == "answer"


@pytest.mark.asyncio
async def test_exhausted_stream_still_reports_stop_async_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely finished stream must remain distinguishable from a slow one."""
    monkeypatch.setattr(worker, "_CANCEL_POLL_S", 0.02)
    events = _slow_stream(0.0)

    assert await worker._next_event(events, budget_s=5.0, cancelled=lambda: False) == "thought"
    assert await worker._next_event(events, budget_s=5.0, cancelled=lambda: False) == "answer"
    with pytest.raises(StopAsyncIteration):
        await worker._next_event(events, budget_s=5.0, cancelled=lambda: False)


@pytest.mark.asyncio
async def test_budget_exhaustion_still_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deadline is unchanged -- slicing must not make the wait unbounded."""
    monkeypatch.setattr(worker, "_CANCEL_POLL_S", 0.02)
    events = _slow_stream(5.0)

    with pytest.raises(asyncio.TimeoutError):
        await worker._next_event(events, budget_s=0.08, cancelled=lambda: False)


@pytest.mark.asyncio
async def test_cancel_is_noticed_within_a_slice(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason the wait is sliced at all: cancel must not wait out the budget."""
    monkeypatch.setattr(worker, "_CANCEL_POLL_S", 0.02)
    events = _slow_stream(30.0)
    polls = {"n": 0}

    def cancelled() -> bool:
        polls["n"] += 1
        return polls["n"] > 2

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(worker._CanvasCancelled):
        await worker._next_event(events, budget_s=600.0, cancelled=cancelled)
    assert loop.time() - started < 1.0
