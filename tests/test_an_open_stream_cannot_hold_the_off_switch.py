"""Streams end when a stop begins, and a plugin whose work calls back in can keep its routes for the wait."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import (
    HERE,
    event_stream,
    events,
    hosted,
    mount_on,
    ok,
    runtime_with,
    socket_stream,
    state_of,
    until,
    waits_for,
)
from thomas.core.kernel import stop


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    fixture.reset()


@pytest.mark.parametrize(
    ("path", "handler"), [("/events", event_stream), ("/socket", socket_stream)], ids=["event-stream", "websocket"]
)
def test_an_open_stream_does_not_hold_the_off_switch(path: str, handler: Any) -> None:
    async def scenario() -> None:
        app, kernel = hosted()

        def build(view: Any) -> None:
            view.router.add_get(path, handler)

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build, streams=(path,))
            if handler is event_stream:
                opened = await client.get(path)
                await opened.content.readline()
            else:
                opened = await client.ws_connect(path)
                assert await opened.receive_str() == "open"
            assert fork.ctx.working == 1

            await stop(fork)

            assert events == ["stream closed"]
            assert (await client.get(path)).status == 404

    asyncio.run(scenario())


def test_a_stream_that_resolved_before_the_stop_is_refused_rather_than_left_running() -> None:
    """Refused by the stream, not by the kernel: a stop still waiting on other work has yet to refuse new work."""

    async def scenario() -> None:
        hold = asyncio.Event()
        slow_gate = asyncio.Event()
        reached_middleware = asyncio.Event()

        @web.middleware
        async def held(request: web.Request, handler: Any) -> web.StreamResponse:
            if request.path == "/events":
                reached_middleware.set()
                await hold.wait()
            return await handler(request)

        app, kernel = hosted(held)

        def build(view: Any) -> None:
            view.router.add_get("/events", event_stream)
            view.router.add_get("/slow", waits_for(slow_gate))

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build, streams=("/events",))
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: fork.ctx.working == 1)
            late = asyncio.create_task(client.get("/events"))
            await reached_middleware.wait()
            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)

            hold.set()
            assert (await late).status == 404

            slow_gate.set()
            await running
            await stopping

    asyncio.run(scenario())


def test_a_stream_name_that_matches_no_route_fails_the_row_and_says_which(tmp_path: Path) -> None:
    """Left alone, the mistake shows up the first time an open page holds the off switch for ever."""
    runtime = runtime_with(tmp_path, [("typo", f"{HERE}:names_a_stream_it_never_registers", True)])

    runtime.load()

    assert state_of(runtime, "typo") == "failed"
    assert "/typo/in/the/name" in runtime.report()["rows"][0]["error"]


def test_a_stream_nobody_named_waits_for_force() -> None:
    async def scenario() -> None:
        app, kernel = hosted()

        def build(view: Any) -> None:
            view.router.add_get("/events", event_stream)

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build)
            opened = await client.get("/events")
            await opened.content.readline()

            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)
            assert not stopping.done()

            fork.ctx.cancel_work()
            await stopping
            with pytest.raises(aiohttp.ClientError):
                await opened.content.read()

    asyncio.run(scenario())


def test_routes_leave_when_the_stop_begins_unless_told_to_stay() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        gate = asyncio.Event()

        def build(view: Any) -> None:
            view.router.add_get("/ping", ok)
            view.router.add_get("/slow", waits_for(gate))

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build)
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: fork.ctx.working == 1)
            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)

            assert (await client.get("/ping")).status == 404

            gate.set()
            await running
            await stopping

    asyncio.run(scenario())


def test_kept_routes_answer_while_the_stop_waits_and_leave_once_the_work_has_ended() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        gate = asyncio.Event()

        def build(view: Any) -> None:
            view.router.add_get("/ping", ok)
            view.router.add_get("/slow", waits_for(gate))

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build, keep_routes=True)
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: fork.ctx.working == 1)
            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)

            assert (await client.get("/ping")).status == 200

            gate.set()
            await running
            await stopping
            assert (await client.get("/ping")).status == 404

    asyncio.run(scenario())


def test_a_kept_route_can_still_be_a_stream_that_ends_when_the_stop_begins() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        gate = asyncio.Event()

        def build(view: Any) -> None:
            view.router.add_get("/events", event_stream)
            view.router.add_get("/slow", waits_for(gate))

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build, keep_routes=True, streams=("/events",))
            opened = await client.get("/events")
            await opened.content.readline()
            running = asyncio.create_task(client.get("/slow"))
            await until(lambda: fork.ctx.working == 2)
            stopping = asyncio.create_task(stop(fork))

            await until(lambda: "stream closed" in events)
            assert (await client.get("/events")).status == 404

            gate.set()
            await running
            await stopping

    asyncio.run(scenario())


def test_a_row_that_left_leaves_nothing_on_the_streams_list() -> None:
    """That list is read on every publish, so what stayed on it would be read for ever, and grow with every press."""

    async def scenario() -> None:
        app, kernel = hosted()
        service = kernel.root["web"]
        fork, _ = mount_on(kernel, lambda view: view.router.add_get("/events", event_stream), streams=("/events",))
        assert len(service._streams) == 1

        await stop(fork)

        assert service._streams == {}

    asyncio.run(scenario())
