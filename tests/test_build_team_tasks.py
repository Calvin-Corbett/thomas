"""Owned builder cleanup cannot outlive the parent tool call."""

from __future__ import annotations

import asyncio

import pytest

from thomas.forge.anvil.build_team_tasks import drain_owned, owned_events, run_owned_builders


@pytest.mark.asyncio
async def test_failure_cancels_and_joins_siblings():
    entered, closed = asyncio.Event(), asyncio.Event()

    async def child(index, _job):
        if index == 0:
            await entered.wait()
            raise ValueError("one child failed")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            closed.set()

    with pytest.raises(ValueError, match="one child failed"):
        await run_owned_builders([{}, {}], child, deadline=asyncio.get_running_loop().time() + 10, team_id="failure")
    assert closed.is_set()
    assert not any(task.get_name().startswith("build:failure:") for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_owned_stream_preserves_context_and_closes_on_early_exit():
    from contextvars import ContextVar

    marker = ContextVar("owned-stream-marker", default="parent")
    closed = asyncio.Event()

    async def stream():
        token = marker.set("producer")
        try:
            yield marker.get()
            await asyncio.sleep(0)
            yield marker.get()
            await asyncio.Event().wait()
        finally:
            marker.reset(token)
            closed.set()

    seen = []
    async with owned_events(stream(), deadline=asyncio.get_running_loop().time() + 10, name="context-stream") as events:
        async for event in events:
            seen.append(event)
            assert marker.get() == "parent"
            if len(seen) == 2:
                break
    assert seen == ["producer", "producer"] and closed.is_set()
    assert not any(task.get_name().startswith("context-stream") for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_owned_stream_timeout_and_repeated_stop_join_producer_cleanup(monkeypatch):
    monkeypatch.delattr(asyncio, "timeout", raising=False)
    monkeypatch.delattr(asyncio, "TaskGroup", raising=False)
    cleaning, release, closed = (asyncio.Event() for _ in range(3))

    async def stream():
        try:
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            cleaning.set()
            await release.wait()
            closed.set()

    async def run():
        async with owned_events(
            stream(), deadline=asyncio.get_running_loop().time() + 0.02, name="deadline-stream"
        ) as events:
            async for _ in events:
                pass

    parent = asyncio.create_task(run())
    await cleaning.wait()
    parent.cancel()
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done() and not closed.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert closed.is_set()
    assert not any(task.get_name().startswith("deadline-stream") for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_owned_client_close_survives_repeated_stop():
    cleaning, release, closed = (asyncio.Event() for _ in range(3))

    async def close():
        cleaning.set()
        await release.wait()
        closed.set()

    parent = asyncio.create_task(drain_owned(close()))
    await cleaning.wait()
    parent.cancel()
    await asyncio.sleep(0)
    parent.cancel()
    assert not parent.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert closed.is_set()


@pytest.mark.asyncio
async def test_repeated_stop_waits_for_child_cleanup():
    entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))

    async def child(_index, _job):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            closed.set()

    parent = asyncio.create_task(
        run_owned_builders([{}], child, deadline=asyncio.get_running_loop().time() + 10, team_id="stop")
    )
    await entered.wait()
    parent.cancel()
    await cleaning.wait()
    parent.cancel()
    await asyncio.sleep(0)
    assert not parent.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await parent
    assert closed.is_set()


@pytest.mark.asyncio
async def test_deadline_joins_children_without_python_311_task_apis(monkeypatch):
    monkeypatch.delattr(asyncio, "TaskGroup", raising=False)
    monkeypatch.delattr(asyncio, "timeout_at", raising=False)
    closed = asyncio.Event()

    async def child(_index, _job):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    with pytest.raises(asyncio.TimeoutError):
        await run_owned_builders([{}], child, deadline=asyncio.get_running_loop().time() + 0.02, team_id="deadline")
    assert closed.is_set()


@pytest.mark.asyncio
async def test_producer_cleanup_failure_after_terminal_event_is_not_success():
    async def stream():
        try:
            yield "done"
            await asyncio.Event().wait()
        finally:
            raise ValueError("stream cleanup failed")

    with pytest.raises(ValueError, match="stream cleanup failed"):
        async with owned_events(
            stream(), deadline=asyncio.get_running_loop().time() + 10, name="failure-stream"
        ) as events:
            async for event in events:
                assert event == "done"
                break
