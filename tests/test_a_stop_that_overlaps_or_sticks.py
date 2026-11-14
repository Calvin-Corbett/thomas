"""A stop keeps its promises when force ends it, a step sticks, or a second stop arrives during the first."""

from __future__ import annotations

import asyncio

import pytest

from tests.plugin_stop_fixture import ends, providing, quiet, turns
from thomas.core.kernel import ContextDisposed, Kernel, KernelError, context, stop


def test_a_forced_press_just_before_the_stop_steps_start_does_not_skip_them() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        ran = []
        working = asyncio.Event()
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        async def clean_up() -> None:
            ran.append("cleaned up")

        async def work() -> None:
            async with ctx.busy():
                working.set()
                await release.wait()

        def press_as_soon_as_they_are_due() -> None:
            if ctx._closing is None:
                loop.call_soon(press_as_soon_as_they_are_due)
            else:
                ctx.cancel_work()

        ctx.on_stopped(clean_up)
        running = asyncio.create_task(work())
        await working.wait()
        stopping = asyncio.create_task(stop(fork))
        await turns()

        release.set()
        loop.call_soon(press_as_soon_as_they_are_due)
        held = await stopping
        await running

        assert ran == ["cleaned up"]
        assert held.errors == ()

    asyncio.run(scenario())


def test_a_forced_stop_ends_a_stop_step_that_sticks_and_the_rest_still_run(monkeypatch) -> None:
    """Shutdown is forced and has no second press, so a stuck step must end by itself."""
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.01)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran = []

        async def older() -> None:
            ran.append("older step")

        async def hangs() -> None:
            await asyncio.Event().wait()

        fork.ctx.on_stopped(older)
        fork.ctx.on_stopped(hangs)
        stopping = asyncio.create_task(stop(fork, force=True))
        await ends(stopping)

        assert fork.state == "disposed"
        assert ran == ["older step"]
        assert [type(error) for error in stopping.result().errors] == [KernelError]

    asyncio.run(scenario())


def test_a_forced_stop_lets_a_step_that_is_only_slow_finish() -> None:
    """Force must not turn every stop step that awaits into one that was cut off, or shutdown cleans up nothing."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran = []

        async def slow() -> None:
            await turns()
            ran.append("finished")

        fork.ctx.on_stopped(slow)

        held = await stop(fork, force=True)

        assert ran == ["finished"]
        assert held.errors == ()

    asyncio.run(scenario())


def test_a_press_during_one_stuck_step_also_covers_the_step_after_it(monkeypatch) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.01)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        stuck = asyncio.Event()

        async def hangs_later() -> None:
            await asyncio.Event().wait()

        async def hangs() -> None:
            stuck.set()
            await asyncio.Event().wait()

        ctx.on_stopped(hangs_later)
        ctx.on_stopped(hangs)
        stopping = asyncio.create_task(stop(fork))
        await stuck.wait()

        ctx.cancel_work()
        await ends(stopping)

        assert fork.state == "disposed"
        assert len(stopping.result().errors) == 2

    asyncio.run(scenario())


def test_a_forced_stop_takes_no_new_work() -> None:
    """Otherwise work that arrives after the press is waited for, and the force did not hold."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        refused = []

        async def drained() -> None:
            try:
                async with ctx.busy():
                    refused.append("busy was allowed")
            except ContextDisposed:
                refused.append("busy")
            try:
                ctx.task(lambda: asyncio.Event().wait(), name="late")
            except ContextDisposed:
                refused.append("task")

        ctx.on_drain(drained)

        await stop(fork, force=True)

        assert refused == ["busy", "task"]

    asyncio.run(scenario())


def test_two_stops_of_one_plugin_are_one_stop() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran = []

        async def clean_up() -> None:
            ran.append("cleaned up")

        fork.ctx.on_stopped(clean_up)

        first, second = await asyncio.gather(stop(fork), stop(fork))

        assert first is second
        assert ran == ["cleaned up"]
        assert await stop(fork) is first  # and one that comes after it has finished gets the same answer

    asyncio.run(scenario())


def test_a_forced_stop_ends_the_wait_of_a_plain_stop_already_running() -> None:
    """This is shutdown arriving during a plain off, with the work held up in a dependant."""

    async def scenario() -> None:
        kernel = Kernel()
        order = []
        provider = kernel.mount(providing("provider", "thing", order=order))
        dependant = kernel.mount(providing("dependant", inject=("thing",), order=order))
        working = asyncio.Event()

        async def work() -> None:
            async with dependant.ctx.busy():
                working.set()
                await asyncio.Event().wait()

        running = asyncio.create_task(work())
        await working.wait()
        plain = asyncio.create_task(stop(provider))
        await turns()
        assert provider.state == "unloading"

        forced = await stop(provider, force=True)

        assert await plain is forced
        assert running.cancelled()
        assert order == ["dependant cleaned up", "provider cleaned up"]

    asyncio.run(scenario())


def test_a_stop_waiting_on_one_that_is_cancelled_takes_over() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran = []
        stepping = asyncio.Event()
        release = asyncio.Event()

        async def clean_up() -> None:
            stepping.set()
            await release.wait()
            ran.append("cleaned up")

        fork.ctx.on_stopped(clean_up)
        first = asyncio.create_task(stop(fork))
        await stepping.wait()
        second = asyncio.create_task(stop(fork))
        await turns()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await turns()
        assert not second.done()

        release.set()
        held = await second

        assert held.name == "quiet"
        assert ran == ["cleaned up"]
        assert fork.state == "disposed"

    asyncio.run(scenario())


def test_a_stop_that_takes_over_waits_for_the_work_the_cancelled_stop_was_waiting_for() -> None:
    """The second stop passes through that wait again, or its stop steps would run under work still going."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        order = []
        working = asyncio.Event()
        release = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                working.set()
                await release.wait()
                order.append("work finished")

        async def clean_up() -> None:
            order.append("cleaned up")

        ctx.on_stopped(clean_up)
        running = asyncio.create_task(work())
        await working.wait()
        first = asyncio.create_task(stop(fork))
        await turns()
        second = asyncio.create_task(stop(fork))
        await turns()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await turns()

        assert order == []
        assert not second.done()

        release.set()
        await ends(second)
        await running

        assert order == ["work finished", "cleaned up"]
        assert fork.state == "disposed"

    asyncio.run(scenario())
