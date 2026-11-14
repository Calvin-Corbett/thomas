"""Cleaning up comes after a plugin's work has ended, and while the plugin is still plugged in."""

from __future__ import annotations

import asyncio

import pytest

from tests.plugin_stop_fixture import ends, providing, quiet, turns
from thomas.core.kernel import ContextDisposed, Kernel, SelfStop, stop, unplug


def test_stop_steps_wait_for_running_work_and_for_owned_tasks() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        order = []
        release = asyncio.Event()
        working = asyncio.Event()
        owned_started = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                working.set()
                await release.wait()
                order.append("work finished")

        async def owned() -> None:
            owned_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)  # a task may take a turn to end, and the step must still come after it
                order.append("task ended")

        async def drained() -> None:
            order.append("drained")
            release.set()

        async def clean_up() -> None:
            order.append("cleaned up")

        ctx.on_drain(drained)
        ctx.on_stopped(clean_up)
        running = asyncio.create_task(work())
        ctx.task(owned, name="owned")
        await working.wait()
        await owned_started.wait()

        await stop(fork)
        await running

        assert order == ["drained", "work finished", "task ended", "cleaned up"]

    asyncio.run(scenario())


def test_a_stop_step_finds_the_plugin_still_plugged_in() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        seen = {}

        def plugin(ctx, config):
            async def clean_up() -> None:
                seen.update(service=ctx["service"], handlers=kernel.bus.handler_count("event"))

            ctx.set("service", "still here")
            ctx.on("event", lambda: None)
            ctx.on_stopped(clean_up)

        plugin.name = "attached"
        fork = kernel.mount(plugin)

        await stop(fork)

        assert seen == {"service": "still here", "handlers": 1}
        assert not kernel.root.has("service")
        assert fork.state == "disposed"

    asyncio.run(scenario())


def test_work_that_starts_as_the_last_work_ends_is_waited_for_too() -> None:
    """The stop is woken by the first piece ending, and must look again rather than trust that it was woken."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        order = []
        first = asyncio.Event()
        second = asyncio.Event()
        working = asyncio.Event()
        in_second = asyncio.Event()
        stop_is_waiting = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                working.set()
                await first.wait()
            async with ctx.busy():  # no pause, so this has begun before the stop gets its turn
                in_second.set()
                await second.wait()
                order.append("second finished")

        async def drained() -> None:
            stop_is_waiting.set()

        async def clean_up() -> None:
            order.append("cleaned up")

        ctx.on_drain(drained)
        ctx.on_stopped(clean_up)
        owned = ctx.task(lambda: asyncio.Event().wait(), name="owned")
        running = asyncio.create_task(work())
        await working.wait()
        stopping = asyncio.create_task(stop(fork))
        await stop_is_waiting.wait()

        first.set()
        await in_second.wait()
        await turns()

        assert order == []
        assert fork.state == "unloading"
        assert not owned.done()  # the second piece of work may depend on it, so it outlives that work too

        second.set()
        await stopping
        await running
        assert order == ["second finished", "cleaned up"]
        assert owned.cancelled()

    asyncio.run(scenario())


def test_nothing_new_can_start_once_stop_steps_have_begun() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        refused = []

        async def clean_up() -> None:
            try:
                async with ctx.busy():
                    refused.append("busy was allowed")
            except ContextDisposed:
                refused.append("busy")
            try:
                ctx.task(lambda: asyncio.Event().wait(), name="late")
            except ContextDisposed:
                refused.append("task")

        ctx.on_stopped(clean_up)

        await stop(fork)

        assert refused == ["busy", "task"]

    asyncio.run(scenario())


def test_stop_steps_run_newest_first_like_every_other_undo() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        order = []

        def step(name):
            async def run() -> None:
                order.append(name)

            return run

        fork.ctx.on_stopped(step("opened first"))
        fork.ctx.on_stopped(step("opened second"))

        await stop(fork)

        assert order == ["opened second", "opened first"]

    asyncio.run(scenario())


def test_taking_a_plugin_off_without_a_stop_says_its_stop_steps_did_not_run(caplog) -> None:
    async def scenario() -> None:
        ran = []

        async def clean_up() -> None:
            ran.append("cleaned up")

        skipped = Kernel().mount(quiet)
        skipped.ctx.on_stopped(clean_up)
        unplug(skipped)

        assert ran == []
        assert "plugin:quiet" in caplog.text
        assert "1 stop step" in caplog.text

        caplog.clear()
        stopped = Kernel().mount(quiet)
        stopped.ctx.on_stopped(clean_up)
        await stop(stopped)

        assert ran == ["cleaned up"]
        assert "stop step" not in caplog.text

    asyncio.run(scenario())


def test_a_task_that_starts_a_replacement_as_it_ends_cannot_hold_a_stop_open() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        rounds = []
        started = asyncio.Event()

        async def supervised() -> None:
            rounds.append("started")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                ctx.task(supervised, name="supervised")

        ctx.task(supervised, name="supervised")
        await started.wait()
        stopping = asyncio.create_task(stop(fork))
        await ends(stopping)

        assert fork.state == "disposed"
        assert rounds == ["started"]

    asyncio.run(scenario())


def test_work_cannot_wait_for_a_stop_that_is_waiting_for_it() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ctx = fork.ctx
        outcome = []
        working = asyncio.Event()
        release = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                working.set()
                await release.wait()
                with pytest.raises(SelfStop):
                    await stop(fork)
                outcome.append("refused")

        running = asyncio.create_task(work())
        await working.wait()
        stopping = asyncio.create_task(stop(fork))
        await turns()

        release.set()
        await ends(stopping)
        await running

        assert outcome == ["refused"]

    asyncio.run(scenario())


def test_an_owned_task_cannot_stop_its_own_plugin() -> None:
    """It would wait for itself, because a stop ends a plugin's tasks before it can finish."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)

        async def work() -> None:
            await stop(fork)

        task = fork.ctx.task(work, name="work")
        await ends(task)

        assert isinstance(task.exception(), SelfStop)
        assert fork.state == "active"

    asyncio.run(scenario())


def test_an_owned_task_cannot_stop_what_it_depends_on_either() -> None:
    """A stop of its provider stops it first, so that wait is the same one."""

    async def scenario() -> None:
        kernel = Kernel()
        order: list[str] = []
        provider = kernel.mount(providing("provider", "thing", order=order))
        dependant = kernel.mount(providing("dependant", inject=("thing",), order=order))

        async def work() -> None:
            await stop(provider)

        task = dependant.ctx.task(work, name="work")
        await ends(task)

        assert isinstance(task.exception(), SelfStop)
        assert order == []

    asyncio.run(scenario())


def test_starting_a_task_leaves_the_caller_free_to_stop_the_plugin() -> None:
    """Only the task is inside the plugin's work. Whoever started it may be the host, turning the plugin off."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)

        fork.ctx.task(lambda: asyncio.Event().wait(), name="work")

        assert not fork.ctx.inside
        await stop(fork)
        assert fork.state == "disposed"

    asyncio.run(scenario())
