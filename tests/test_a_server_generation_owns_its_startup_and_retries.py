"""A server owns the checks its startup schedules, and a task keeps its own server while others enter or retire on
the same loop."""

from __future__ import annotations

import asyncio
import contextvars
import threading

import pytest

from tests import restart_check_support as support
from thomas.server.precard import workers


@pytest.mark.parametrize("stop_outer", [True, False])
def test_a_bound_task_does_not_take_another_generations_signal(stop_outer: bool) -> None:
    async def run() -> None:
        outer, inner = threading.Event(), threading.Event()
        proceed = asyncio.Event()

        async def owned() -> tuple[bool, bool, bool]:
            await proceed.wait()
            before = workers.generation_stopping()
            threaded = await workers.off_the_loop(workers.generation_stopping)
            return before, threaded, workers.generation_stopping()

        with workers.generation(outer):
            task = asyncio.create_task(owned())
            with workers.generation(inner):
                (outer if stop_outer else inner).set()
                proceed.set()
                assert await task == (stop_outer, stop_outer, stop_outer)

    asyncio.run(run())


def test_an_older_generation_retiring_leaves_the_newer_binding() -> None:
    async def run() -> None:
        outer, inner = threading.Event(), threading.Event()
        entered_outer, entered_inner = asyncio.Event(), asyncio.Event()
        retire_outer, retire_inner = asyncio.Event(), asyncio.Event()

        async def generation(signal: threading.Event, entered: asyncio.Event, retire: asyncio.Event) -> None:
            with workers.generation(signal):
                entered.set()
                await retire.wait()

        first = asyncio.create_task(generation(outer, entered_outer, retire_outer))
        await asyncio.wait_for(entered_outer.wait(), 5)  # every wait is bounded: a broken API fails, never hangs
        second = asyncio.create_task(generation(inner, entered_inner, retire_inner), context=contextvars.Context())
        try:
            await asyncio.wait_for(entered_inner.wait(), 5)
            outer.set()
            retire_outer.set()
            await asyncio.wait_for(first, 5)
            probe = asyncio.create_task(
                workers.off_the_loop(workers.generation_stopping), context=contextvars.Context()
            )
            assert await asyncio.wait_for(probe, 5) is False
            inner.set()
            probe = asyncio.create_task(
                workers.off_the_loop(workers.generation_stopping), context=contextvars.Context()
            )
            assert await asyncio.wait_for(probe, 5) is True
        finally:
            retire_outer.set()
            retire_inner.set()
            await asyncio.wait_for(asyncio.gather(first, second), 5)

    asyncio.run(run())


def test_startup_check_inherits_server_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    async def setup(_app: object) -> None:
        seen.append(await workers.off_the_loop(workers.generation_stopping))

    support.serve_once(monkeypatch, setup=setup, restart=False)
    assert seen == [False]
    assert not workers.generation_stopping()
