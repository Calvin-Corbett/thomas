"""What a forced stop does about a step that outlasts its limit: Stop now reaches it, and it is not forgotten."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging

import pytest

from tests.plugin_stop_fixture import ends, ignores_being_cancelled, providing, quiet, turns
from thomas.core.kernel import Kernel, context, stop


@pytest.fixture(autouse=True)
def _small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.01)


def test_stop_now_ends_a_stuck_drain_step_at_once_rather_than_at_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 3600)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        fork.ctx.on_drain(lambda: asyncio.Event().wait())
        stopping = asyncio.create_task(stop(fork))
        await turns()

        await ends(asyncio.create_task(stop(fork, force=True)))

        assert "ended before it finished" in str(stopping.result().errors[0])

    asyncio.run(scenario())


def test_stop_now_cancels_an_owned_task_again_because_one_cancel_was_not_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 3600)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ended: list[str] = []

        async def swallows_one_cancel() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                ended.append("swallowed the first")
            try:
                await asyncio.Event().wait()
            finally:
                ended.append("ended by the second")

        fork.ctx.task(swallows_one_cancel, name="once")
        await turns()
        stopping = asyncio.create_task(stop(fork))
        await turns()
        assert ended == ["swallowed the first"]

        await ends(asyncio.create_task(stop(fork, force=True)))

        assert ended == ["swallowed the first", "ended by the second"]
        await stopping

    asyncio.run(scenario())


def test_a_drain_step_a_forced_stop_ends_at_the_limit_still_costs_only_itself() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran: list[str] = []

        async def next_step() -> None:
            ran.append("next drain step")

        fork.ctx.on_drain(lambda: asyncio.Event().wait())
        fork.ctx.on_drain(next_step)

        held = await stop(fork, force=True)

        assert ran == ["next drain step"]
        assert [str(error) for error in held.errors] == ["a drain step for 'plugin:quiet' was ended before it finished"]

    asyncio.run(scenario())


def test_a_press_on_a_stuck_drain_step_cancels_it_once_and_gives_it_one_limit() -> None:
    """It used to be cancelled and waited for twice, which held Stop now for twice what the spec says."""

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        release = asyncio.Event()
        running = asyncio.Event()
        cancels: list[str] = []

        async def counts_its_cancels() -> None:
            running.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancels.append("cancelled")

        fork.ctx.on_drain(counts_its_cancels)
        stopping = asyncio.create_task(stop(fork))
        await running.wait()

        try:
            await ends(asyncio.create_task(stop(fork, force=True)))
            await ends(stopping)
        finally:
            release.set()
        await turns()

        assert cancels == ["cancelled"]
        assert [type(error).__name__ for error in stopping.result().errors] == ["KernelError"]
        assert "left drain step" in str(stopping.result().errors[0])

    asyncio.run(scenario())


def test_a_slow_drain_step_gets_its_time_on_a_forced_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force is not a reason to skip cleaning up, here as on a stop step."""
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 10.0)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran: list[str] = []

        async def slow() -> None:
            await turns()
            ran.append("finished")

        fork.ctx.on_drain(slow)

        held = await stop(fork, force=True)

        assert ran == ["finished"]
        assert held.errors == ()

    asyncio.run(scenario())


def test_the_limit_on_a_step_a_press_ended_does_not_fall_on_the_step_after_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.1)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        stuck = asyncio.Event()

        async def after_it() -> None:
            await asyncio.Event().wait()

        async def hangs() -> None:
            stuck.set()
            await asyncio.Event().wait()

        fork.ctx.on_stopped(after_it)
        fork.ctx.on_stopped(hangs)
        stopping = asyncio.create_task(stop(fork))
        await stuck.wait()

        fork.ctx.cancel_work()
        await ends(stopping)

        errors = [str(error) for error in stopping.result().errors]
        assert len(errors) == 2
        assert not [error for error in errors if "left" in error]  # both ended, and neither ignored a cancel

    asyncio.run(scenario())


def test_the_limit_on_a_step_that_ended_in_time_does_not_fall_on_the_step_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forced, because a plain stop sets no limit. The first step's would fall while the second is running."""
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.2)

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        finished: list[str] = []

        async def second() -> None:
            await asyncio.sleep(0.3)
            finished.append("second")

        async def first() -> None:
            monkeypatch.setattr(
                context, "FORCED_STEP_SECONDS", 3600
            )  # so only the first step's limit can end the second
            finished.append("first")

        fork.ctx.on_stopped(second)
        fork.ctx.on_stopped(first)

        held = await stop(fork, force=True)

        assert finished == ["first", "second"], held.errors
        assert held.errors == ()

    asyncio.run(scenario())


def test_two_presses_during_one_stuck_step_leave_it_behind_once() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran: list[str] = []
        release = asyncio.Event()
        stuck = asyncio.Event()

        async def after_it() -> None:
            ran.append("the next step")

        async def stubborn() -> None:
            stuck.set()
            await ignores_being_cancelled(release)

        fork.ctx.on_stopped(after_it)
        fork.ctx.on_stopped(stubborn)
        stopping = asyncio.create_task(stop(fork))
        await stuck.wait()

        fork.ctx.cancel_work()
        fork.ctx.cancel_work()
        await ends(stopping)
        await asyncio.sleep(0.05)

        assert ran == ["the next step"]
        assert len([error for error in stopping.result().errors if "left" in str(error)]) == 1
        release.set()
        await turns()

    asyncio.run(scenario())


def test_a_press_finds_nothing_left_to_leave_in_a_dependant_that_has_finished(caplog: pytest.LogCaptureFixture) -> None:
    """The stop is held up in the provider, and a press reaches every scope in it, finished or not."""

    async def scenario() -> None:
        kernel = Kernel()
        order: list[str] = []
        provider = kernel.mount(providing("provider", "thing", order=order))
        kernel.mount(providing("dependant", inject=("thing",), order=order))
        working = asyncio.Event()

        async def work() -> None:
            async with provider.ctx.busy():
                working.set()
                await asyncio.Event().wait()

        running = asyncio.create_task(work())
        await working.wait()
        stopping = asyncio.create_task(stop(provider))
        while "dependant cleaned up" not in order:
            await asyncio.sleep(0)

        await stop(provider, force=True)
        await stopping
        await asyncio.sleep(0.05)

        assert running.cancelled()
        assert "left" not in caplog.text

    with caplog.at_level(logging.ERROR, logger="thomas.core.kernel.context"):
        asyncio.run(scenario())


def test_a_step_left_behind_that_ends_cancelled_has_nothing_to_report() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        release = asyncio.Event()
        reported: list[dict] = []
        asyncio.get_running_loop().set_exception_handler(lambda _loop, context: reported.append(context))

        async def ends_cancelled() -> None:
            await ignores_being_cancelled(release)
            raise asyncio.CancelledError

        fork.ctx.on_drain(ends_cancelled)

        await ends(asyncio.create_task(stop(fork, force=True)))
        release.set()
        await turns()

        assert reported == []

    asyncio.run(scenario())


@pytest.mark.parametrize("force", [False, True], ids=["plain", "forced"])
def test_a_stop_leaves_no_waiter_of_its_own_running(force: bool) -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        release = asyncio.Event()
        working = asyncio.Event()

        async def work() -> None:
            async with fork.ctx.busy():
                working.set()
                await ignores_being_cancelled(release)

        async def let_go() -> None:
            await turns()
            if not force:
                release.set()

        fork.ctx.task(lambda: asyncio.Event().wait(), name="owned")
        running = asyncio.create_task(work(), name="the work")
        await working.wait()
        letting_go = asyncio.create_task(let_go())

        await ends(asyncio.create_task(stop(fork, force=force)))
        await letting_go
        await turns()

        left = asyncio.all_tasks() - {asyncio.current_task()}
        assert {task.get_name() for task in left} == ({"the work"} if force else set())
        release.set()
        await running

    asyncio.run(scenario())


def test_a_stop_cancelled_during_a_drain_step_cancels_that_step() -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ended: list[str] = []

        async def step() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                ended.append("step ended")

        fork.ctx.on_drain(step)
        stopping = asyncio.create_task(stop(fork))
        await turns()

        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping
        await turns()

        assert ended == ["step ended"]

    asyncio.run(scenario())


def test_a_stop_step_left_behind_that_ends_later_does_not_run_the_next_step_beside_the_one_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", 0.2)  # above the 15.6 ms a Windows clock can see

    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        order: list[str] = []
        release = asyncio.Event()

        async def last() -> None:
            order.append("last step on a scope already gone" if fork.disposed else "last step")

        async def next_step() -> None:
            order.append("next step began")
            release.set()
            for _ in range(5):  # enough turns for the step left behind to wake, whatever the limit does to this one
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(0)
            order.append("next step finished")

        fork.ctx.on_stopped(last)
        fork.ctx.on_stopped(next_step)
        fork.ctx.on_stopped(functools.partial(ignores_being_cancelled, release))

        stopping = asyncio.create_task(stop(fork, force=True))
        await ends(stopping)
        await turns()

        assert order == ["next step began", "next step finished", "last step"]
        assert stopping.result().name == "quiet"  # it finished, rather than ending with an error of its own

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["on_drain", "on_stopped"])
def test_a_step_left_behind_that_fails_later_is_logged_rather_than_lost(
    kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        release = asyncio.Event()

        async def fails_once_let_go() -> None:
            await ignores_being_cancelled(release)
            raise OSError("fell over long after the stop")

        getattr(fork.ctx, kind)(fails_once_let_go)

        with caplog.at_level(logging.WARNING, logger="thomas.core.kernel.context"):
            await ends(asyncio.create_task(stop(fork, force=True)))
            release.set()
            await turns()

        # By this log, not the one asyncio writes for a failure nothing read, which holds the same words.
        assert "that a stop went on without failed later: fell over long after the stop" in caplog.text

    asyncio.run(scenario())
