"""A plugin's view of the app does what a registrar needs, on a server that is already running."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import (
    HERE,
    WRITTEN,
    hosted,
    mount_on,
    ok,
    until,
    waits_for,
)
from thomas.core.kernel import ContextDisposed, stop
from thomas.server import app_core
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ALREADY_THERE = web.AppKey("already_there", str)
ALSO_THERE = web.AppKey("also_there", str)


@pytest.fixture(autouse=True)
def _nothing_left_from_the_last_test() -> None:
    fixture.reset()


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


# -- writing to a started app -------------------------------------------------


@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_a_plugin_turned_on_later_writes_a_new_key_to_a_started_app(tmp_path: Path) -> None:
    """Three later waves stand on this: a frozen app takes a key it has never held, and gives it back on stop."""

    async def scenario() -> None:
        runtime = fixture.runtime_with(tmp_path, [("writes", f"{HERE}:writes_a_key", False)])
        runtime.load()
        app = runtime.web.app
        async with TestClient(TestServer(app)) as client:
            assert app.frozen
            assert WRITTEN not in app
            with pytest.raises(DeprecationWarning):  # the front door warns, so a write through it would fail this test
                app[web.AppKey("not_this_way", str)] = "refused"

            report = await runtime.turn_on("writes")
            assert report["state"] == "active", report

            assert app[WRITTEN] == "from the plugin"
            assert await (await client.get("/written")).text() == "from the plugin"

            await runtime.turn_off("writes")
            assert WRITTEN not in app
            assert (await client.get("/written")).status == 404

            await runtime.turn_on("writes")
            assert await (await client.get("/written")).text() == "from the plugin"

    asyncio.run(scenario())


def test_a_view_reads_and_writes_like_the_app() -> None:
    app, kernel = hosted()
    app[ALREADY_THERE] = "old"

    _, view = mount_on(kernel)

    assert isinstance(view, MutableMapping)
    assert view.setdefault(ALREADY_THERE, "ignored") == "old"
    assert view.setdefault(WRITTEN, "made") == "made"
    assert app[WRITTEN] == "made"
    assert dict(view.items()) == dict(app.items())
    assert list(view.values()) == list(app.values())
    assert len(view) == len(app)
    assert list(view) == list(app)
    assert view.get("nothing", "fallback") == "fallback"
    assert view.pop(WRITTEN) == "made"
    assert WRITTEN not in app
    assert {view: "registrars key their caches on the app"}[view]


def test_stopping_gives_back_what_a_plugin_changed() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        app[ALREADY_THERE] = "old"
        app[ALSO_THERE] = "kept"

        def build(view: Any) -> None:
            view[ALREADY_THERE] = "changed"
            del view[ALSO_THERE]
            view[WRITTEN] = "ours"

        fork, _ = mount_on(kernel, build)
        assert app[ALREADY_THERE] == "changed"
        assert ALSO_THERE not in app
        app._state[WRITTEN] = "someone else's, written on top"

        await stop(fork)

        assert app[ALREADY_THERE] == "old"
        assert app[ALSO_THERE] == "kept"
        assert app[WRITTEN] == "someone else's, written on top"  # an unwind must never clobber a live writer

    asyncio.run(scenario())


def test_writing_one_key_over_and_over_costs_one_undo() -> None:
    app, kernel = hosted()
    fork, view = mount_on(kernel)
    before = fork.ctx.pending_effects

    for value in range(50):
        view[WRITTEN] = str(value)

    assert fork.ctx.pending_effects == before + 1
    assert app[WRITTEN] == "49"


def test_a_plugin_that_has_gone_cannot_write() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        fork, view = mount_on(kernel)

        await stop(fork)

        with pytest.raises(ContextDisposed):
            view[WRITTEN] = "too late"
        assert WRITTEN not in app

    asyncio.run(scenario())


# -- routes -------------------------------------------------------------------


def test_add_routes_keeps_head_and_a_stop_waits_for_them() -> None:
    async def scenario() -> None:
        app, kernel = hosted()
        gate = asyncio.Event()
        table = web.RouteTableDef()

        @table.get("/decorated")
        async def decorated(_request: web.Request) -> web.Response:
            return web.Response(text="decorated")

        def build(view: Any) -> None:
            view.add_routes(
                [web.get("/plain", ok), web.get("/no-head", ok, allow_head=False), web.post("/slow", waits_for(gate))]
            )
            view.router.add_routes(table)

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build)
            assert (await client.head("/plain")).status == 200
            assert (await client.head("/no-head")).status == 405
            assert await (await client.get("/decorated")).text() == "decorated"

            running = asyncio.create_task(client.post("/slow"))
            await until(lambda: fork.ctx.working == 1)
            stopping = asyncio.create_task(stop(fork))
            await until(lambda: fork.stopping)
            assert not stopping.done()

            gate.set()
            assert await (await running).text() == "finished"
            await stopping
            assert (await client.get("/plain")).status == 404

    asyncio.run(scenario())


def test_a_bad_route_raises_in_the_registrar_as_it_does_on_a_real_app() -> None:
    app, kernel = hosted()
    bare = web.Application()

    def build(view: Any) -> None:
        for router in (view.router, bare.router):
            with pytest.raises(ValueError):
                router.add_get("no-leading-slash", ok)
            assert router.add_get("/fine", ok).resource.canonical == "/fine"  # a registrar may hold what it gets back
            with pytest.raises(RuntimeError):
                router.add_get("/fine", ok)

    mount_on(kernel, build)

    assert "/fine" in {resource.canonical for resource in app.router.resources()}


def test_a_static_folder_joins_and_leaves(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "hello.txt").write_text("from the folder", encoding="utf-8")
        app, kernel = hosted()

        def build(view: Any) -> None:
            view.router.add_static("/files/", str(tmp_path), show_index=False)

        async with TestClient(TestServer(app)) as client:
            fork, _ = mount_on(kernel, build)
            assert await (await client.get("/files/hello.txt")).text() == "from the folder"

            await stop(fork)

            assert (await client.get("/files/hello.txt")).status == 404

    asyncio.run(scenario())


def test_resources_lists_the_server_and_what_the_plugin_has_added_so_far() -> None:
    app, kernel = hosted()
    app.router.add_get("/frozen", ok)
    seen: set[str] = set()

    def build(view: Any) -> None:
        view.router.add_get("/mine", ok)
        seen.update(resource.canonical for resource in view.router.resources())

    mount_on(kernel, build)

    assert {"/frozen", "/mine"} <= seen


# -- what the service hands over ----------------------------------------------


def test_the_service_hands_over_the_loopback_guard_and_the_web_folder(tmp_path: Path, own_data_dir: Path) -> None:
    service = app_core.create_app(fixture.config_in(tmp_path))[APP_RUNTIME_PLUGINS].web

    assert callable(service.require_loopback)
    assert (service.web_dir / "static").is_dir()
