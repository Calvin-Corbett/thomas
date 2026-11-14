"""Turning a plugin off lets its running work finish, dependants first, and leaves nothing behind."""

from __future__ import annotations

import asyncio

import pytest

from thomas.core.kernel import Kernel, KernelError, SelfStop, Unplugged, stop, unplug


def _quiet(ctx, config):
    return None


_quiet.name = "quiet"


def _provides(ctx, config):
    ctx.set("thing", "the newer value")


_provides.name = "provides"


def _needs(ctx, config):
    return None


_needs.name = "needs"
_needs.inject = ("thing",)


async def _turns(count: int = 5) -> None:
    """Hand the event loop a few turns, so a stop that was woken has run as far as it will."""
    for _ in range(count):
        await asyncio.sleep(0)


def test_stopping_waits_for_work_in_progress() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        release = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                await release.wait()

        running = asyncio.create_task(work())
        await asyncio.sleep(0)
        stopping = asyncio.create_task(stop(fork))
        await asyncio.sleep(0)

        assert fork.state == "unloading"
        assert ctx.working == 1

        release.set()
        held = await stopping
        await running

        assert isinstance(held, Unplugged)
        assert fork.state == "disposed"

    asyncio.run(scenario())


def test_force_ends_the_work_instead_of_waiting() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx

        async def work() -> None:
            async with ctx.busy():
                await asyncio.Event().wait()

        running = asyncio.create_task(work())
        await asyncio.sleep(0)

        await stop(fork, force=True)

        assert fork.state == "disposed"
        assert running.cancelled()

    asyncio.run(scenario())


def test_a_task_a_plugin_owns_is_cancelled_when_it_stops() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        task = fork.ctx.task(lambda: asyncio.Event().wait(), name="forever")
        await asyncio.sleep(0)

        await stop(fork)

        assert task.cancelled()

    asyncio.run(scenario())


def test_a_task_does_not_outlive_a_plugin_that_fell_over_in_apply() -> None:
    """Its scope is gone by the time ``apply`` raises, so no stop could ever find this work."""

    async def scenario() -> None:
        kernel = Kernel()
        kernel.mark_ready()
        tasks = []

        def falls_over(ctx, config):
            tasks.append(ctx.task(lambda: asyncio.Event().wait(), name="work"))
            raise OSError("apply fell over")

        falls_over.name = "falls-over"

        with pytest.raises(OSError):
            kernel.mount(falls_over)
        await _turns()

        assert tasks[0].cancelled()

    asyncio.run(scenario())


def test_a_task_does_not_outlive_a_start_that_failed() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        tasks = []

        def fall_over():
            raise OSError("starting fell over")

        def starts_badly(ctx, config):
            ctx.on_ready(lambda: tasks.append(ctx.task(lambda: asyncio.Event().wait(), name="work")))
            ctx.on_ready(fall_over)

        starts_badly.name = "starts-badly"
        fork = kernel.mount(starts_badly)

        kernel.mark_ready()
        await _turns()

        assert fork.state == "failed"
        assert tasks[0].cancelled()

    asyncio.run(scenario())


def test_a_task_ends_when_a_service_its_plugin_needs_is_withdrawn() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        provider = kernel.mount(_provides)
        dependant = kernel.mount(_needs)
        ended = []

        async def work() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                ended.append("work ended")

        dependant.ctx.task(work, name="work")
        await _turns()

        unplug(provider)
        await _turns()

        assert dependant.state == "pending"
        assert ended == ["work ended"]

    asyncio.run(scenario())


def test_tasks_that_have_ended_leave_nothing_on_their_scope() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        before = fork.ctx.pending_effects

        for _ in range(100):
            await fork.ctx.task(_turns, name="short")
        await _turns()

        assert fork.ctx.pending_effects == before

    asyncio.run(scenario())


def test_a_stop_can_leave_up_a_dependant_that_was_running_before_its_provider_came() -> None:
    """What a host needs to take back a plugin that failed the moment it arrived, before anything could have used it."""

    async def scenario() -> None:
        kernel = Kernel()
        kernel.root.set("thing", "the older value")
        dependant = kernel.mount(_needs)
        provider = kernel.mount(_provides)
        scope = dependant.ctx
        release = asyncio.Event()

        async def work() -> None:
            async with scope.busy():
                await release.wait()

        running = asyncio.create_task(work())
        await asyncio.sleep(0)

        await stop(provider, force=True, spare=[dependant])

        assert provider.state == "disposed"
        assert dependant.ctx is scope
        assert not running.done()
        release.set()
        await running

    asyncio.run(scenario())


def test_drain_steps_run_before_the_wait_so_new_work_stops_arriving_first() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        order = []
        release = asyncio.Event()

        async def step() -> None:
            order.append("routes left")
            release.set()

        async def work() -> None:
            async with ctx.busy():
                await release.wait()
                order.append("work finished")

        ctx.on_drain(step)
        running = asyncio.create_task(work())
        await asyncio.sleep(0)

        await stop(fork)
        await running

        assert order == ["routes left", "work finished"]

    asyncio.run(scenario())


def test_a_plugin_cannot_stop_itself_from_inside_its_own_work() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)

        async with fork.ctx.busy():
            with pytest.raises(SelfStop):
                await stop(fork)

        assert fork.state == "active"

    asyncio.run(scenario())


def test_dependants_stop_first_and_come_back_with_the_provider() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        order = []

        def provider(ctx, config):
            ctx.set("thing", 1)

        def dependant(ctx, config):
            async def step() -> None:
                order.append("dependant drained")

            ctx.on_drain(step)

        provider.name = "provider"
        dependant.name = "dependant"
        dependant.inject = ("thing",)
        provider_fork = kernel.mount(provider)
        dependant_fork = kernel.mount(dependant)

        async def provider_step() -> None:
            order.append("provider drained")

        provider_fork.ctx.on_drain(provider_step)

        held = await stop(provider_fork)

        assert order == ["dependant drained", "provider drained"]
        assert dependant_fork.state == "pending"

        held.replug()
        assert dependant_fork.state == "active"

    asyncio.run(scenario())


def test_on_ready_waits_for_the_host_then_runs_at_once_for_a_late_plugin() -> None:
    kernel = Kernel()
    started = []

    def plugin(ctx, config):
        ctx.on_ready(lambda: started.append(ctx.label))

    plugin.name = "early"
    kernel.mount(plugin)
    assert started == []

    kernel.mark_ready()
    assert started == ["plugin:early"]

    def late(ctx, config):
        ctx.on_ready(lambda: started.append(ctx.label))

    late.name = "late"
    kernel.mount(late)
    assert started == ["plugin:early", "plugin:late"]


def test_a_plugin_that_fails_at_ready_is_failed_and_its_neighbour_still_starts() -> None:
    kernel = Kernel()
    started = []

    def bad(ctx, config):
        def start() -> None:
            raise RuntimeError("boom")

        ctx.on_ready(start)

    def good(ctx, config):
        ctx.on_ready(lambda: started.append("good"))

    bad.name = "bad"
    good.name = "good"
    bad_fork = kernel.mount(bad)
    kernel.mount(good)

    kernel.mark_ready()

    assert bad_fork.state == "failed"
    assert started == ["good"]


def test_a_bad_drain_step_does_not_cost_the_stop_and_strict_hears_about_it() -> None:
    async def scenario() -> None:
        async def bad() -> None:
            raise RuntimeError("boom")

        forgiving = Kernel().mount(_quiet)
        forgiving.ctx.on_drain(bad)
        await stop(forgiving)
        assert forgiving.state == "disposed"

        strict = Kernel().mount(_quiet)
        strict.ctx.on_drain(bad)
        with pytest.raises(RuntimeError, match="boom"):
            await strict.ctx.drain(strict=True)

    asyncio.run(scenario())


def test_strict_hears_about_a_plugin_that_fails_at_ready() -> None:
    kernel = Kernel()

    def bad(ctx, config):
        def start() -> None:
            raise RuntimeError("boom")

        ctx.on_ready(start)

    bad.name = "bad"
    fork = kernel.mount(bad)

    with pytest.raises(RuntimeError, match="boom"):
        kernel.mark_ready(strict=True)

    assert fork.state == "failed"


def test_a_task_that_dies_does_not_stop_the_plugin_and_is_logged(caplog) -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)

        async def dies() -> None:
            raise RuntimeError("boom")

        task = fork.ctx.task(dies, name="dies")
        await asyncio.wait({task})

        assert fork.state == "active"

    asyncio.run(scenario())
    assert "dies" in caplog.text


def test_a_hundred_cycles_leave_nothing_behind() -> None:
    async def scenario() -> None:
        kernel = Kernel()
        cleaned_up = []

        def plugin(ctx, config):
            async def clean_up() -> None:
                cleaned_up.append(ctx.label)

            ctx.set("service", 1)
            ctx.on("event", lambda: None)
            ctx.task(lambda: asyncio.Event().wait(), name="forever")
            ctx.on_stopped(clean_up)

        plugin.name = "cycled"
        before = kernel.root.pending_effects

        for _ in range(100):
            await stop(kernel.mount(plugin))

        assert kernel.root.pending_effects == before
        assert kernel.bus.handler_count("event") == 0
        assert not kernel.root.has("service")
        assert kernel.mounted() == []
        assert len(cleaned_up) == 100

    asyncio.run(scenario())


def test_a_forced_stop_ends_the_work_and_still_cleans_up() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        order = []
        working = asyncio.Event()

        async def work() -> None:
            async with ctx.busy():
                working.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    order.append("work ended")

        async def clean_up() -> None:
            order.append("cleaned up")

        ctx.on_stopped(clean_up)
        running = asyncio.create_task(work())
        await working.wait()

        await stop(fork, force=True)

        assert order == ["work ended", "cleaned up"]
        assert running.cancelled()

    asyncio.run(scenario())


def test_force_ends_a_stuck_stop_step_and_the_rest_still_run() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        order = []
        stuck = asyncio.Event()

        async def older() -> None:
            order.append("older step")

        async def hangs() -> None:
            stuck.set()
            await asyncio.Event().wait()

        ctx.on_stopped(older)
        ctx.on_stopped(hangs)
        stopping = asyncio.create_task(stop(fork))
        await stuck.wait()

        assert fork.state == "unloading"
        assert ctx.working == 1  # a status page must not read "waiting for nothing" here

        ctx.cancel_work()
        held = await stopping

        assert fork.state == "disposed"
        assert order == ["older step"]
        assert [type(error) for error in held.errors] == [KernelError]
        assert "ended" in str(held.errors[0])

    asyncio.run(scenario())


def test_a_bad_stop_step_does_not_cost_the_stop_and_strict_hears_about_it() -> None:
    async def scenario() -> None:
        ran = []

        async def bad() -> None:
            raise RuntimeError("boom")

        async def good() -> None:
            ran.append("good")

        forgiving = Kernel().mount(_quiet)
        forgiving.ctx.on_stopped(good)
        forgiving.ctx.on_stopped(bad)
        held = await stop(forgiving)

        assert forgiving.state == "disposed"
        assert ran == ["good"]
        assert [str(error) for error in held.errors] == ["boom"]

        strict = Kernel().mount(_quiet)
        strict.ctx.on_stopped(good)
        strict.ctx.on_stopped(bad)
        with pytest.raises(RuntimeError, match="boom"):
            await strict.ctx.drain(strict=True)

        assert ran == ["good", "good"]  # teardown still finished before it spoke up

    asyncio.run(scenario())


def test_what_went_wrong_while_stopping_comes_back_with_the_plugin() -> None:
    async def scenario() -> None:
        kernel = Kernel()

        async def bad_drain() -> None:
            raise RuntimeError("drain")

        async def bad_step() -> None:
            raise RuntimeError("dependant step")

        def provider(ctx, config):
            ctx.set("thing", 1)
            ctx.on_drain(bad_drain)

        def dependant(ctx, config):
            ctx.on_stopped(bad_step)

        provider.name = "provider"
        dependant.name = "dependant"
        dependant.inject = ("thing",)
        provider_fork = kernel.mount(provider)
        kernel.mount(dependant)

        held = await stop(provider_fork)

        assert [str(error) for error in held.errors] == ["dependant step", "drain"]

        clean = await stop(kernel.mount(_quiet))
        assert clean.errors == ()

    asyncio.run(scenario())


def test_stop_steps_run_once_and_every_stop_waits_for_them() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        ran = []
        stepping = asyncio.Event()
        release = asyncio.Event()

        async def clean_up() -> None:
            ran.append("cleaned up")
            stepping.set()
            await release.wait()

        ctx.on_stopped(clean_up)
        first = asyncio.create_task(ctx.drain())
        await stepping.wait()
        second = asyncio.create_task(ctx.drain())
        await _turns()

        assert not first.done()
        assert not second.done()

        release.set()
        await asyncio.gather(first, second)

        assert ran == ["cleaned up"]

    asyncio.run(scenario())


def test_a_cancelled_stop_leaves_the_step_running_for_the_next_stop_to_finish() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)
        ctx = fork.ctx
        ran = []
        stepping = asyncio.Event()
        release = asyncio.Event()

        async def clean_up() -> None:
            ran.append("began")
            stepping.set()
            await release.wait()
            ran.append("finished")

        ctx.on_stopped(clean_up)
        stopping = asyncio.create_task(stop(fork))
        await stepping.wait()
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping

        again = asyncio.create_task(stop(fork))
        await _turns()
        assert not again.done()

        release.set()
        await again

        assert ran == ["began", "finished"]
        assert fork.state == "disposed"

    asyncio.run(scenario())


def test_a_stop_step_cannot_stop_its_own_plugin() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(_quiet)

        async def stops_itself() -> None:
            await stop(fork)

        fork.ctx.on_stopped(stops_itself)

        held = await stop(fork)

        assert fork.state == "disposed"
        assert [type(error) for error in held.errors] == [SelfStop]

    asyncio.run(scenario())
