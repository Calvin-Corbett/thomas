"""A model adapter whose row turns off mid-stream: the stream in flight finishes, the next one sees the right adapter.

``stream_current_provider`` looks the adapter up through the models slot once per stream. A row that registers an adapter
and then turns off takes it away with its undo; a stream already running keeps the function it started with, and the next
stream asks again.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core import llm_adapters
from thomas.core.llm_slot import models
from thomas.core.llm_transport_pool import stream_current_provider

PROVIDER = "leaving_provider"


def _owner(provider: str = PROVIDER) -> Any:
    async def builtin(*_a: Any, **_k: Any):
        yield "builtin"

    return SimpleNamespace(
        config=SimpleNamespace(provider=provider, api_key="", model="m"),
        _stream_openai=lambda messages, tools: builtin(),
    )


def _adapter(name: str, gate: asyncio.Event | None = None, started: asyncio.Event | None = None):
    closed: list[str] = []

    async def stream(owner: Any, messages: Any, tools: Any, *, turn_user_content: Any = None):
        try:
            yield f"{name}:1"
            if started is not None:
                started.set()
            if gate is not None:
                await gate.wait()
            yield f"{name}:2"
        finally:
            closed.append(name)

    return stream, closed


async def _collect(owner: Any) -> list[Any]:
    return [event async for event in stream_current_provider(owner, [], None)]


@pytest.fixture(autouse=True)
def _clean_table():
    llm_adapters._table.pop(PROVIDER, None)
    yield
    llm_adapters._table.pop(PROVIDER, None)


def test_no_adapter_registered_uses_the_built_in_provider() -> None:
    assert asyncio.run(_collect(_owner())) == ["builtin"]


def test_an_adapter_answers_for_its_provider() -> None:
    stream, closed = _adapter("a")
    undo = models().adapter(PROVIDER, stream)
    try:
        assert asyncio.run(_collect(_owner())) == ["a:1", "a:2"]
    finally:
        undo()
    assert closed == ["a"]


def test_an_adapter_that_leaves_mid_stream_lets_the_stream_finish_and_the_next_sees_none() -> None:
    async def scenario() -> tuple[list[Any], list[Any]]:
        gate, started = asyncio.Event(), asyncio.Event()
        stream, _ = _adapter("a", gate, started)
        undo = models().adapter(PROVIDER, stream)
        task = asyncio.ensure_future(_collect(_owner()))
        await started.wait()
        undo()  # the row turns off while the stream is in flight
        assert llm_adapters.lookup(PROVIDER) is None
        gate.set()
        return await task, await _collect(_owner())

    in_flight, after = asyncio.run(scenario())
    assert in_flight == ["a:1", "a:2"]
    assert after == ["builtin"]


def test_an_adapter_that_comes_back_is_seen_by_the_next_stream_only() -> None:
    async def scenario() -> tuple[list[Any], list[Any], list[Any]]:
        gate, started = asyncio.Event(), asyncio.Event()
        first, _ = _adapter("first", gate, started)
        undo_first = models().adapter(PROVIDER, first)
        running = asyncio.ensure_future(_collect(_owner()))
        await started.wait()
        undo_first()
        second, _ = _adapter("second")
        undo_second = models().adapter(PROVIDER, second)  # the row turns back on, with a new adapter
        try:
            next_events = await _collect(_owner())
            gate.set()
            return await running, next_events, await _collect(_owner())
        finally:
            undo_second()

    in_flight, next_events, third = asyncio.run(scenario())
    assert in_flight == ["first:1", "first:2"]
    assert next_events == ["second:1", "second:2"]
    assert third == ["second:1", "second:2"]


def test_an_adapter_that_fails_mid_stream_fails_the_stream_cleanly_and_the_next_still_works() -> None:
    async def broken(owner: Any, messages: Any, tools: Any, *, turn_user_content: Any = None):
        yield "partial"
        raise RuntimeError("adapter went away")

    undo = models().adapter(PROVIDER, broken)

    async def scenario() -> list[Any]:
        seen: list[Any] = []
        with pytest.raises(RuntimeError, match="adapter went away"):
            async for event in stream_current_provider(_owner(), [], None):
                seen.append(event)
        undo()
        return seen + await _collect(_owner())

    assert asyncio.run(scenario()) == ["partial", "builtin"]


def test_a_stream_abandoned_early_closes_the_adapter() -> None:
    stream, closed = _adapter("a")
    undo = models().adapter(PROVIDER, stream)

    async def scenario() -> None:
        gen = stream_current_provider(_owner(), [], None)
        assert await gen.__anext__() == "a:1"
        await gen.aclose()

    try:
        asyncio.run(scenario())
    finally:
        undo()
    assert closed == ["a"]
