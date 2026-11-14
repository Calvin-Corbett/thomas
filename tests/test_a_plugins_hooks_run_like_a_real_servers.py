"""Startup and cleanup hooks run when a plugin starts and stops, in the order a real server runs them."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import (
    WRITTEN,
    events,
    hosted,
    mount_on,
    records,
    until,
    waits_for,
)
from thomas.core.kernel import stop


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    fixture.reset()


def _register_every_kind_of_hook(app: Any, seen: list[str]) -> None:
    def step(name: str) -> Any:
        async def hook(_app: Any) -> None:
            seen.append(name)

        return hook

    def around(name: str) -> Any:
        async def hook(_app: Any) -> Any:
            seen.append(f"{name} in")
            yield
            seen.append(f"{name} out")

        return hook

    app.on_startup.append(step("startup one"))
    app.on_startup.append(step("startup two"))
    app.on_cleanup.append(step("cleanup one"))
    app.on_cleanup.append(step("cleanup two"))
    app.cleanup_ctx.append(around("context one"))
    app.cleanup_ctx.append(around("context two"))


@pytest.mark.parametrize("turned_on_later", [True, False])
def test_hooks_run_in_the_order_a_real_server_runs_them(turned_on_later: bool) -> None:
    async def scenario() -> None:
        real_order: list[str] = []
        bare = web.Application()
        _register_every_kind_of_hook(bare, real_order)
        async with TestClient(TestServer(bare)):
            pass
        assert len(real_order) == 8  # an empty compare would pass

        _, kernel = hosted()
        order: list[str] = []
        if turned_on_later:
            kernel.mark_ready()

        fork, _ = mount_on(kernel, lambda view: _register_every_kind_of_hook(view, order))
        if not turned_on_later:
            await asyncio.sleep(0)
            assert order == []  # nothing runs before the server is up
            kernel.mark_ready()
        await until(lambda: "startup two" in order)

        await stop(fork)

        assert order == real_order

    asyncio.run(scenario())


def test_every_hook_is_handed_the_view_so_what_it_writes_goes_with_the_plugin() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        kernel.mark_ready()
        given: list[Any] = []

        async def starting(view: Any) -> None:
            given.append(view)
            view[WRITTEN] = "written by a hook"

        async def around(view: Any) -> Any:
            given.append(view)
            yield

        async def cleaning(view: Any) -> None:
            given.append(view)

        def build(view: Any) -> None:
            view.on_startup.append(starting)
            view.cleanup_ctx.append(around)
            view.on_cleanup.append(cleaning)

        async with TestClient(TestServer(app)):
            fork, view = mount_on(kernel, build)
            await until(lambda: WRITTEN in app)

            await stop(fork)

            assert WRITTEN not in app
            assert len(given) == 3
            assert all(seen is view for seen in given)

    asyncio.run(scenario())


def test_startup_hooks_run_one_at_a_time_as_on_a_real_server() -> None:
    """A later hook may lean on what an earlier one set up, so it must not begin until that one has finished."""

    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()
        gate = asyncio.Event()

        async def slow(_app: Any) -> None:
            events.append("first began")
            await gate.wait()
            events.append("first finished")

        def build(view: Any) -> None:
            view.on_startup.append(slow)
            view.on_startup.append(records("second began"))

        mount_on(kernel, build)
        await until(lambda: "first began" in events)

        gate.set()
        await until(lambda: "second began" in events)

        assert events == ["first began", "first finished", "second began"]

    asyncio.run(scenario())


def test_a_registrar_that_skips_hooks_on_a_frozen_app_still_adds_them() -> None:
    """models_aiohttp.py asks, and a plugin turned on later would otherwise never start."""

    async def scenario() -> None:
        app, kernel = hosted()
        kernel.mark_ready()

        def build(view: Any) -> None:
            assert app.on_startup.frozen
            if not view.on_startup.frozen:
                view.on_startup.append(records("started"))

        async with TestClient(TestServer(app)):
            mount_on(kernel, build)
            await until(lambda: events == ["started"])

    asyncio.run(scenario())


def test_a_cleanup_runs_after_running_requests_end() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        gate = asyncio.Event()

        def build(view: Any) -> None:
            view.on_cleanup.append(records("cleaned up"))
            view.router.add_get("/slow", waits_for(gate))

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build)
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: fork.ctx.working == 1)
            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)

            assert events == []

            gate.set()
            await stopping
            await running
            assert events == ["request finished", "cleaned up"]

    asyncio.run(scenario())


def test_a_cleanup_added_on_first_use_still_runs() -> None:
    """mission_autonomy_runtime.py adds one the first time a request needs the engine, long after startup."""

    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()
        fork, view = mount_on(kernel)

        view.on_cleanup.append(records("cleaned up"))

        await stop(fork)

        assert events == ["cleaned up"]

    asyncio.run(scenario())


def test_one_bad_cleanup_costs_only_itself() -> None:
    async def scenario() -> None:
        _, kernel = hosted()

        async def bad(_app: Any) -> None:
            raise OSError("the first one fell over")

        def build(view: Any) -> None:
            view.on_cleanup.append(bad)
            view.on_cleanup.append(records("cleaned up"))

        fork, _ = mount_on(kernel, build)

        held = await stop(fork)

        assert events == ["cleaned up"]
        assert [str(error) for error in held.errors] == ["the first one fell over"]

    asyncio.run(scenario())


def test_force_ends_one_stuck_cleanup_and_the_next_still_runs() -> None:
    async def scenario() -> None:
        _, kernel = hosted()

        async def stuck(_app: Any) -> None:
            events.append("stuck")
            await asyncio.Event().wait()

        def build(view: Any) -> None:
            view.on_cleanup.append(stuck)
            view.on_cleanup.append(records("cleaned up"))

        fork, _ = mount_on(kernel, build)
        stopping = asyncio.create_task(stop(fork))
        await until(lambda: events == ["stuck"])

        fork.ctx.cancel_work()
        await stopping

        assert events == ["stuck", "cleaned up"]

    asyncio.run(scenario())


def test_a_startup_hook_that_fails_reads_failed_and_off_still_cleans_up() -> None:
    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()

        async def bad(_app: Any) -> None:
            raise OSError("no such port")

        def build(view: Any) -> None:
            view.on_startup.append(bad)
            view.on_startup.append(records("ran after a failure"))
            view.on_cleanup.append(records("cleaned up"))

        fork, _ = mount_on(kernel, build)
        await until(lambda: fork.error is not None)

        assert fork.state == "failed"
        assert "no such port" in str(fork.error)

        await stop(fork)

        assert events == ["cleaned up"]

    asyncio.run(scenario())


def test_a_hook_added_after_its_kind_has_run_is_refused_rather_than_lost() -> None:
    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()
        fork, view = mount_on(kernel, lambda view: view.on_startup.append(records("started")))
        await until(lambda: view.on_startup.frozen)

        with pytest.raises(RuntimeError):
            view.on_startup.append(records("too late to start"))

        await stop(fork)

        with pytest.raises(RuntimeError):
            view.on_cleanup.append(records("too late to clean up"))
        assert events == ["started"]

    asyncio.run(scenario())


def test_no_handler_runs_before_the_startup_hooks_end_as_on_a_real_server() -> None:
    """A real server finishes on_startup before it takes a connection, so a handler can lean on what a hook set up."""

    def build(app: Any, gate: asyncio.Event, order: list[str]) -> None:
        async def starting(view: Any) -> None:
            await gate.wait()
            view[WRITTEN] = "written by a hook"
            order.append("hook finished")

        async def reads(request: web.Request) -> web.Response:
            order.append("handler ran")
            return web.Response(text=request.app[WRITTEN])

        app.on_startup.append(starting)
        app.router.add_get("/reads", reads)

    async def scenario() -> None:
        real_order: list[str] = []
        ready = asyncio.Event()
        ready.set()
        bare = web.Application()
        build(bare, ready, real_order)
        async with TestClient(TestServer(bare)) as client:
            real = await (await client.get("/reads")).text()

        order: list[str] = []
        gate = asyncio.Event()
        app, kernel = hosted()
        kernel.mark_ready()
        async with TestClient(TestServer(app)) as client:
            mount_on(kernel, lambda view: build(view, gate, order))
            early = await client.get("/reads")
            gate.set()
            await until(lambda: "hook finished" in order)
            await asyncio.sleep(0)
            answer = await (await client.get("/reads")).text()

        assert early.status == 404
        assert answer == real
        assert order == real_order == ["hook finished", "handler ran"]

    asyncio.run(scenario())


def test_a_cleanup_context_may_be_a_context_manager_a_function_returns() -> None:
    """A ``cleanup_ctx`` entry need not be a generator. Treated as one, this reads failed the moment it starts."""

    class Around:
        async def __aenter__(self) -> None:
            events.append("in")

        async def __aexit__(self, *_exc: Any) -> None:
            events.append("out")

    async def scenario() -> None:
        _, kernel = hosted()
        kernel.mark_ready()
        fork, _ = mount_on(kernel, lambda view: view.cleanup_ctx.append(lambda _app: Around()))
        await until(lambda: events == ["in"])

        assert fork.error is None

        await stop(fork)

        assert events == ["in", "out"]

    asyncio.run(scenario())
