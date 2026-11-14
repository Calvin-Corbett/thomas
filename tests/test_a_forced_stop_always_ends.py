"""A forced stop ends whatever it was waiting for does, because Thomas must always be able to close.

Each of these used to hang Stop now, and shutdown with it. Python cannot end code that ignores being cancelled, so a
forced stop goes on without it and says what it left. A plain stop still waits for as long as it takes.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_stop_fixture import ends, ignores_being_cancelled, quiet, turns
from tests.plugin_view_fixture import ok, row_here, runtime_with, state_of, until
from thomas.core.kernel import Context, ContextDisposed, Kernel, context, stop
from thomas.server import live_routes

HERE = __name__
SMALL = 0.01
released: asyncio.Event | None = None  # what lets a row's stubborn code end, so that the test itself can finish


async def _cleans_up_for_ever(release: asyncio.Event) -> None:
    try:
        await release.wait()
    finally:
        await ignores_being_cancelled(release)


def _task(body: Callable[..., Any]) -> Callable[[Context, asyncio.Event], None]:
    def plant(ctx: Context, release: asyncio.Event) -> None:
        ctx.task(functools.partial(body, release), name="the stubborn one")

    return plant


def _drain_step(ctx: Context, release: asyncio.Event) -> None:
    ctx.on_drain(functools.partial(ignores_being_cancelled, release))


def _stop_step(body: Callable[..., Any]) -> Callable[[Context, asyncio.Event], None]:
    def plant(ctx: Context, release: asyncio.Event) -> None:
        ctx.on_stopped(functools.partial(body, release))

    return plant


def _work(ctx: Context, release: asyncio.Event) -> None:
    async def work() -> None:
        async with ctx.busy():
            await ignores_being_cancelled(release)

    asyncio.get_running_loop().create_task(work(), name="the stubborn one")


STUBBORN = [
    pytest.param(_task(ignores_being_cancelled), "the stubborn one", id="an-owned-task-that-ignores-its-cancel"),
    pytest.param(_task(_cleans_up_for_ever), "the stubborn one", id="an-owned-task-whose-finally-never-ends"),
    pytest.param(_drain_step, "ignores_being_cancelled", id="a-drain-step-that-never-ends"),
    pytest.param(
        _stop_step(ignores_being_cancelled), "ignores_being_cancelled", id="a-stop-step-that-ignores-its-cancel"
    ),
    pytest.param(_stop_step(_cleans_up_for_ever), "_cleans_up_for_ever", id="a-stop-step-whose-finally-never-ends"),
    pytest.param(_work, "the stubborn one", id="running-work-that-ignores-its-cancel"),
]


@pytest.fixture(autouse=True)
def _small_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    global released
    released = None
    fixture.reset()
    monkeypatch.setattr(context, "FORCED_STEP_SECONDS", SMALL)


@pytest.mark.parametrize("how", ["forced", "stop-now"])
@pytest.mark.parametrize(("plant", "name"), STUBBORN)
def test_a_forced_stop_goes_on_without_what_will_not_end_and_says_what_it_left(
    plant: Any, name: str, how: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        ran: list[str] = []
        release = asyncio.Event()

        async def clean_up() -> None:
            ran.append("cleaned up")

        fork.ctx.on_stopped(clean_up)  # older than any step planted, so it runs after that one
        plant(fork.ctx, release)
        await turns()

        with caplog.at_level(logging.ERROR, logger="thomas.core.kernel.context"):
            stopping = asyncio.create_task(stop(fork, force=how == "forced"))
            if how == "stop-now":
                await asyncio.sleep(SMALL * 5)
                assert not stopping.done()
                await ends(asyncio.create_task(stop(fork, force=True)))
            await ends(stopping)

        assert fork.state == "disposed"
        assert ran == ["cleaned up"]
        assert any(name in str(error) for error in stopping.result().errors)
        assert name in caplog.text
        assert "partial" not in caplog.text  # a cleanup hook reaches a stop inside one, and that is no name to read
        release.set()
        await turns()

    asyncio.run(scenario())


@pytest.mark.parametrize(("plant", "name"), STUBBORN)
def test_a_plain_stop_has_no_limit_on_any_of_this(plant: Any, name: str) -> None:
    async def scenario() -> None:
        fork = Kernel().mount(quiet)
        release = asyncio.Event()
        plant(fork.ctx, release)
        await turns()

        stopping = asyncio.create_task(stop(fork))
        await asyncio.sleep(SMALL * 10)

        assert not stopping.done()
        assert fork.state == "unloading"

        release.set()
        await ends(stopping)
        await turns()

    asyncio.run(scenario())


async def _stubborn_work() -> None:
    await ignores_being_cancelled(released)


async def _stubborn_cleanup(_app: Any) -> None:
    await ignores_being_cancelled(released)


class _WillNotEnd:
    name = "will-not-end"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        view = ctx["web"].view(ctx)
        view.router.add_get("/will-not-end", ok)
        view.on_cleanup.append(_stubborn_cleanup)
        ctx.on_ready(lambda: ctx.task(_stubborn_work, name="stubborn work"))


will_not_end = _WillNotEnd()


def _up(tmp_path: Path) -> Any:
    global released
    released = asyncio.Event()
    runtime = runtime_with(tmp_path, [row_here(HERE, "will_not_end")])
    runtime.load()
    runtime.mark_ready()
    return runtime


def test_shutdown_ends_with_a_row_that_will_not(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _up(tmp_path)
        await turns()

        await ends(asyncio.create_task(runtime.stop_all()))

        assert state_of(runtime, "will_not_end") == "off"
        released.set()
        await turns()

    asyncio.run(scenario())


def test_stop_now_ends_a_row_that_will_not(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _up(tmp_path)
        await turns()
        turning_off = asyncio.create_task(runtime.turn_off("will_not_end"))
        await asyncio.sleep(SMALL * 5)
        assert state_of(runtime, "will_not_end") == "unloading"

        await ends(asyncio.create_task(runtime.turn_off("will_not_end", force=True)))
        await ends(turning_off)

        assert state_of(runtime, "will_not_end") == "off"
        released.set()
        await turns()

    asyncio.run(scenario())


async def _stubborn_handler(_request: web.Request) -> web.Response:
    await ignores_being_cancelled(released)
    return web.Response()


class _HoldsARequest:
    name = "holds-a-request"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get("/things/{id}", _stubborn_handler)


holds_a_request = _HoldsARequest()


def test_a_request_left_running_is_named_by_its_route(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """aiohttp's task for a request has no name of its own, so the log used to say ``Task-100``."""

    async def scenario() -> None:
        global released
        released = asyncio.Event()
        runtime = runtime_with(tmp_path, [row_here(HERE, "holds_a_request")])
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            request = asyncio.create_task(client.get("/things/7"))
            try:
                await until(lambda: runtime.report()["rows"][0]["waiting_for"] == 1)
                await ends(asyncio.create_task(runtime.stop_all()))
            finally:
                released.set()
            await request

    with caplog.at_level(logging.ERROR, logger="thomas.core.kernel.context"):
        asyncio.run(scenario())

    assert "left work GET /things/{id} running" in caplog.text


@pytest.mark.parametrize(
    ("raised", "answered"),
    [
        pytest.param(None, None, id="a-handler-that-ends"),
        pytest.param(OSError("it fell over"), OSError, id="a-handler-that-fails"),
        pytest.param(ContextDisposed("the row has gone"), web.HTTPNotFound, id="a-request-its-row-left-behind"),
    ],
)
def test_the_task_gets_its_own_name_back_when_the_handler_ends(raised: Any, answered: Any) -> None:
    """The name is only for the time the handler runs. Today each request has its own task, so this is care for later."""

    async def scenario() -> None:
        ctx = Kernel().mount(quiet).ctx
        named: list[str] = []

        async def handler(_request: web.Request) -> web.Response:
            named.append(asyncio.current_task().get_name())
            if raised is not None:
                raise raised
            return web.Response()

        asyncio.current_task().set_name("the connection")
        counted = live_routes._counted(ctx, "/things/{id}", handler)

        if answered is None:
            await counted(SimpleNamespace(method="POST"))
        else:
            with pytest.raises(answered):
                await counted(SimpleNamespace(method="POST"))

        assert named == ["POST /things/{id}"]
        assert asyncio.current_task().get_name() == "the connection"

    asyncio.run(scenario())
