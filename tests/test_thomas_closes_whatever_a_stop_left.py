"""A forced stop can leave code running that Python cannot end, and the process has to close around it.

``asyncio.run`` cancels every task left and waits with no limit, so one that ignores being cancelled kept the process open
with its port already closed: the lock stayed, and a restart that had been asked for never happened.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import gc
import logging
import sys
import threading
from collections.abc import AsyncIterator, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import thomas.core.kernel
from tests import closing_thomas_fixture as closing
from tests.plugin_stop_fixture import quiet
from thomas.core.kernel import Context, Kernel, context, stop
from thomas.server import app_lifecycle

SMALL = 0.05
LONGER_THAN_THE_LIMIT = SMALL * 4
A_LITTLE_LATER = 1.0


@pytest.mark.parametrize(
    ("row", "named"),
    [
        pytest.param("owned_task", "left owned task plugin:owned_task:the owned task running", id="an-owned-task"),
        pytest.param("drain_step", "left drain step ignores_being_cancelled running", id="a-drain-step"),
        pytest.param("stop_step", "left stop step ignores_being_cancelled running", id="a-stop-step"),
    ],
)
def test_thomas_closes_and_releases_its_lock_with_a_row_that_will_not_end(row: str, named: str, tmp_path: Path) -> None:
    said = closing.serve_in_a_process_of_its_own(tmp_path, row)

    assert any(named in line for line in said), said
    assert any("Thomas closed with" in line and "still running" in line for line in said), said
    assert said.index(closing.LOCK_RELEASED) < said.index(closing.SERVE_RETURNED)


def test_a_restart_goes_ahead_with_a_row_that_will_not_end(tmp_path: Path) -> None:
    said = closing.serve_in_a_process_of_its_own(tmp_path, "owned_task", ending=closing.RESTART)

    assert said.index(closing.NEW_SERVER) < said.index(closing.LOCK_RELEASED) < said.index(closing.SERVE_RETURNED)


def test_ctrl_c_closes_thomas_and_releases_its_lock_with_a_row_that_will_not_end(tmp_path: Path) -> None:
    """The press has to stop the server before the close begins: the close itself waits for every task with no limit."""
    said = closing.serve_in_a_process_of_its_own(tmp_path, "owned_task", ending=closing.CTRL_C)

    assert any("left owned task plugin:owned_task:the owned task running" in line for line in said), said
    assert "[thomas] Stopped by user." in said
    assert (
        said.index("[thomas] Stopped by user.") < said.index(closing.LOCK_RELEASED) < said.index(closing.SERVE_RETURNED)
    )


@pytest.mark.parametrize(
    ("scenario", "said"),
    [
        pytest.param("one_press", ["its finally ran", closing.INTERRUPTED, "python's handler"], id="one-press"),
        pytest.param(
            "a_press_wakes_a_loop_asleep_in_its_wait",
            ["it woke the loop", "its finally ran", closing.INTERRUPTED, "python's handler"],
            id="a-press-wakes-the-loop",
        ),
        pytest.param(
            "a_second_press_while_it_cleans_up",
            ["its finally began", closing.INTERRUPTED, "python's handler"],
            id="a-second-press-does-not-wait-for-the-clean-up",
        ),
        pytest.param(
            "a_press_as_it_ends", [closing.INTERRUPTED, "python's handler"], id="a-press-with-nothing-to-cancel"
        ),
        pytest.param(
            "a_press_with_a_handler_of_its_own",
            ["its own handler ran", "it carried on", "its own handler"],
            id="a-handler-someone-else-set-keeps-the-press",
        ),
        pytest.param("sets_a_handler_of_its_own", ["its own handler"], id="a-handler-set-as-it-ran-stays"),
    ],
)
def test_ctrl_c_does_what_it_does_on_python_3_12(scenario: str, said: list[str], tmp_path: Path) -> None:
    assert closing.press_in_a_process_of_its_own(tmp_path, scenario) == said


def _closes(main: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """The real close, on a thread so that a hang fails this test and leaves the rest running."""
    ended: dict[str, Any] = {}

    def run() -> None:
        try:
            ended["result"] = app_lifecycle._run_and_close(main())
        except app_lifecycle._ServerRestartRequested as raised:
            ended["raised"] = raised

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(closing.A_HANG)
    assert not thread.is_alive(), "it never closed"
    if "raised" in ended:
        raise ended["raised"]
    return ended["result"]


def _an_owned_task(ctx: Context) -> None:
    ctx.task(closing.ignores_being_cancelled, name="the stubborn one")


def _a_drain_step(ctx: Context) -> None:
    ctx.on_drain(closing.ignores_being_cancelled)


def _a_stop_step(ctx: Context) -> None:
    ctx.on_stopped(closing.ignores_being_cancelled)


def _running_work(ctx: Context) -> None:
    async def work() -> None:
        async with ctx.busy():
            await closing.ignores_being_cancelled()

    asyncio.get_running_loop().create_task(work(), name="the stubborn one")


async def _a_forced_stop_leaves(plant: Callable[[Context], None] = _an_owned_task) -> None:
    """What ``stop_all`` does at shutdown, to a plugin with something in it that will not end."""
    fork = Kernel().mount(quiet)
    plant(fork.ctx)
    await asyncio.sleep(0)  # work has to be running to be left running
    await stop(fork, force=True)


@pytest.fixture(autouse=True)
def _small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", SMALL)


@pytest.fixture(autouse=True)
def _held_here(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    held: list[Any] = []
    monkeypatch.setattr(app_lifecycle, "_CLOSED_AROUND", held)
    return held


@pytest.mark.parametrize("plant", [_an_owned_task, _a_drain_step, _a_stop_step, _running_work])
def test_the_loop_closes_around_whatever_a_forced_stop_left(
    plant: Callable[[Context], None], caplog: pytest.LogCaptureFixture
) -> None:
    loops: list[asyncio.AbstractEventLoop] = []

    async def main() -> str:
        loops.append(asyncio.get_running_loop())
        await _a_forced_stop_leaves(plant)
        return "served"

    with caplog.at_level(logging.ERROR, logger="thomas.server.app_lifecycle"):
        assert _closes(main) == "served"

    assert "still running" in caplog.text
    assert loops[0].is_closed()


def test_a_request_a_stop_left_cannot_hold_the_close_through_its_connection(tmp_path: Path) -> None:
    """aiohttp's task for a connection awaits its request's, so a cancel ends at code that ignores it and neither ends.

    The wait for other tasks has no limit, so it was a wait for that request: the lock stayed and no restart happened.
    """
    said = closing.press_in_a_process_of_its_own(tmp_path, "a_request_left_running")

    assert "the request is running" in said
    assert any("left work GET /held/{id} running" in line for line in said), said
    assert any("Thomas closed with" in line and "RequestHandler.start" in line for line in said), said


def test_what_awaits_left_code_goes_with_it_however_long_the_line(_held_here: list[Any]) -> None:
    """Each of these ends only when the one it awaits does, so none of them may have the wait with no limit."""

    async def waits_for(task: asyncio.Task[Any]) -> None:
        await task

    async def main() -> None:
        loop = asyncio.get_running_loop()
        fork = Kernel().mount(quiet)

        async def work() -> None:
            async with fork.ctx.busy():
                await closing.ignores_being_cancelled()

        nearest = loop.create_task(work())
        await asyncio.sleep(0)
        next_along = loop.create_task(waits_for(nearest))
        loop.create_task(waits_for(next_along))
        await asyncio.sleep(0)
        await stop(fork, force=True)

    _closes(main)

    assert len(_held_here) == 3


def test_an_owned_task_whose_scope_went_with_no_stop_cannot_hold_the_close() -> None:
    """A row refused as it mounts goes by ``dispose``, which cannot wait, so no stop ever looks at this task again."""

    async def main() -> None:
        fork = Kernel().mount(quiet)
        _an_owned_task(fork.ctx)
        await asyncio.sleep(0)
        fork.dispose()

    _closes(main)


def test_what_the_server_raised_still_reaches_serve() -> None:
    """It is how a restart is asked for, so losing it here would be a close with no restart."""

    async def main() -> None:
        await _a_forced_stop_leaves()
        raise app_lifecycle._ServerRestartRequested()

    with pytest.raises(app_lifecycle._ServerRestartRequested):
        _closes(main)


def test_the_last_cancel_ends_a_finally_that_was_waiting_and_python_finishes_the_close() -> None:
    """A stop gave up on it, but it only needed a second cancel. Nothing is stuck, so nothing is closed around.

    A drain step, because nothing else cancels one twice: going away cancels an owned task again, and that would end it.
    """
    seen: list[Any] = []

    async def waits_in_its_finally() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.Event().wait()

    async def main() -> None:
        seen.append(asyncio.get_running_loop())
        await _a_forced_stop_leaves(lambda ctx: ctx.on_drain(waits_in_its_finally))

    _closes(main)

    assert app_lifecycle._CLOSED_AROUND == []
    assert seen[0].is_closed()


def test_a_task_no_stop_gave_up_on_gets_as_long_as_it_takes() -> None:
    """Cancelled work tidying up is a shielded save finishing, not code that will not end, and it has no limit here."""
    tidied: list[str] = []

    async def tidies_up() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(LONGER_THAN_THE_LIMIT)
            tidied.append("tidied up")
            raise

    async def main() -> None:
        asyncio.get_running_loop().create_task(tidies_up())
        await _a_forced_stop_leaves()

    _closes(main)

    assert tidied == ["tidied up"]


def test_a_stuck_task_never_runs_again_not_even_its_finally(_held_here: list[Any]) -> None:
    """Python runs a collected coroutine's ``finally``, which after a restart would be old code beside the new server."""
    ran: list[str] = []

    async def has_a_finally() -> None:
        try:
            await closing.ignores_being_cancelled()
        finally:
            ran.append("the finally")

    async def main() -> None:
        await _a_forced_stop_leaves(lambda ctx: ctx.task(has_a_finally, name="the stubborn one"))

    _closes(main)
    gc.collect()

    assert len(_held_here) == 1
    assert ran == []


def test_the_kernel_asked_is_the_one_running_now_and_not_the_one_this_module_saw_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restart re-imports every module but this one, so what the next server's stops left is in another kernel."""
    the_next_generations = SimpleNamespace(left_behind=lambda: left, FORCED_STEP_SECONDS=SMALL)
    left: set[Any] = set()

    async def main() -> None:
        left.add(asyncio.get_running_loop().create_task(closing.ignores_being_cancelled(), name="the stubborn one"))
        await asyncio.sleep(0)

    monkeypatch.setattr(thomas.core.kernel, "context", the_next_generations)

    _closes(main)

    assert list(left) == app_lifecycle._CLOSED_AROUND


def test_with_nothing_stuck_it_is_python_s_own_close() -> None:
    """Open generators and the thread pool are its to finish, and no stop has left anything for this to change."""
    closed: list[str] = []
    held: list[Any] = []

    async def generator() -> AsyncIterator[None]:
        try:
            yield
        finally:
            closed.append("the generator")

    async def main() -> None:
        held.append(asyncio.get_running_loop())
        left_open = generator()
        await left_open.__anext__()
        held.append(left_open)  # held so that only the close can finish it, not the garbage collector
        await asyncio.to_thread(closed.append, "the thread ran")

    _closes(main)

    assert closed == ["the thread ran", "the generator"]
    assert held[0].is_closed()


class _SaysWhenItShutsDown(ThreadPoolExecutor):
    def __init__(self, closed: list[str]) -> None:
        super().__init__()
        self._closed = closed

    def shutdown(self, wait: bool = True, **kwargs: Any) -> None:
        if wait:  # closing the loop calls this again, by then with nothing to wait for
            self._closed.append("the thread pool")
        super().shutdown(wait, **kwargs)


def test_with_nothing_stuck_the_close_goes_in_python_s_order() -> None:
    """Tasks, then open generators, then the thread pool, because each can still be using what comes after it."""
    closed: list[str] = []
    held: list[Any] = []

    async def task() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            closed.append("the task")

    async def generator() -> AsyncIterator[None]:
        try:
            yield
        finally:
            closed.append("the generator")

    async def main() -> None:
        asyncio.get_running_loop().set_default_executor(_SaysWhenItShutsDown(closed))
        left_open = generator()
        await left_open.__anext__()
        held.append(left_open)
        asyncio.get_running_loop().create_task(task())
        await asyncio.sleep(0)

    _closes(main)

    assert closed == ["the task", "the generator", "the thread pool"]


def test_a_task_that_fails_as_it_is_cancelled_is_reported_as_python_reports_it() -> None:
    reported: list[Any] = []

    async def fails() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            raise OSError("it fell over on its way out")

    async def main() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _loop, details: reported.append(details["exception"]))
        asyncio.get_running_loop().create_task(fails())
        await asyncio.sleep(0)

    _closes(main)

    assert [str(error) for error in reported] == ["it fell over on its way out"]


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="Python limits this wait from 3.12, and before that it has no limit"
)
def test_a_thread_that_will_not_end_cannot_hold_the_close_past_python_s_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thomas could only release its lock once this returned, so losing the limit is a close that hangs."""
    monkeypatch.setattr(asyncio.constants, "THREAD_JOIN_TIMEOUT", SMALL)
    release = threading.Event()
    letting_go = threading.Timer(A_LITTLE_LATER, release.set)  # a close that ignores the limit returns after this
    letting_go.start()

    async def main() -> None:
        asyncio.get_running_loop().run_in_executor(None, release.wait)

    try:
        with pytest.warns(RuntimeWarning, match="did not finishing joining"):
            _closes(main)

        assert not release.is_set()
    finally:
        letting_go.cancel()
        release.set()


def test_a_close_that_fails_still_closes_the_loop() -> None:
    class _WillNotShutDown(ThreadPoolExecutor):
        def shutdown(self, wait: bool = True, **kwargs: Any) -> None:
            super().shutdown(wait, **kwargs)
            if wait:  # closing the loop calls this again, and that is the call that has to go through
                raise OSError("the pool fell over")

    seen: list[Any] = []

    async def main() -> None:
        seen.append(asyncio.get_running_loop())
        seen[0].set_default_executor(_WillNotShutDown())

    with pytest.raises(OSError, match="the pool fell over"):
        app_lifecycle._run_and_close(main())

    assert seen[0].is_closed()


def test_a_cancel_no_one_pressed_for_stays_a_cancel() -> None:
    """``KeyboardInterrupt`` would read as you stopping Thomas, where this is a crash for ``serve`` to restart from."""

    async def main() -> None:
        asyncio.current_task().cancel()
        await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError):
        app_lifecycle._run_and_close(main())


def test_the_loop_is_the_current_one_while_it_runs() -> None:
    """Code that asks for the current loop outside a task, as older libraries do, must be given this one."""
    seen: list[bool] = []

    async def main() -> None:
        seen.append(asyncio.get_event_loop_policy().get_event_loop() is asyncio.get_running_loop())

    _closes(main)

    assert seen == [True]


@pytest.mark.parametrize("stuck", [True, False], ids=["something-stuck", "nothing-stuck"])
def test_the_loop_is_no_longer_the_current_one(stuck: bool) -> None:
    current: list[Any] = []

    async def main() -> None:
        if stuck:
            await _a_forced_stop_leaves()

    def closes_then_looks() -> None:
        app_lifecycle._run_and_close(main())
        current.append(asyncio.get_event_loop_policy()._local._loop)

    thread = threading.Thread(target=closes_then_looks, daemon=True)
    thread.start()
    thread.join(closing.A_HANG)

    assert current == [None]
