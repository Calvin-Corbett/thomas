"""A row may not answer in the server's place. The live table is looked at first, so nothing else would stop it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from aiohttp.web_urldispatcher import UrlDispatcher

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import Adds, ok, row_here, rows_once_started, runtime_with, state_of
from thomas.server import app_core, live_routes, runtime_plugins
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

HERE = __name__
began: list[str] = []  # what the row that starts its work reached


async def _the_servers(_request: web.Request) -> web.Response:
    return web.Response(text="the server's")


class _StartsAndClaims:
    name = "starts-and-claims"
    inject = ("web",)

    def apply(self, ctx: Any, config: Any) -> None:
        ctx.on_ready(lambda: began.append("work began"))
        ctx["web"].view(ctx).router.add_get("/claimed", ok)


class _WritesAddGet:
    """A row that writes ``add_get``, which puts HEAD on its table unasked, ahead of GET."""

    inject = ("web",)

    def __init__(self, path: str) -> None:
        self.name = f"writes add_get {path}"
        self._path = path

    def apply(self, ctx: Any, config: Any) -> None:
        ctx["web"].view(ctx).router.add_get(self._path, ok)


wrote_add_get_claimed = _WritesAddGet("/claimed")
wrote_add_get_any_thing = _WritesAddGet("/api/things/{id}")
get_claimed = Adds("GET", "/claimed")
post_claimed = Adds("POST", "/claimed")
any_claimed = Adds("*", "/claimed")
get_thing_by_id = Adds("GET", "/things/{id}")
get_exact = Adds("GET", "/api/exact")
get_other = Adds("GET", "/other")
get_anything = Adds("GET", "/api/{anything}")
get_any_thing = Adds("GET", "/api/things/{id}")
post_any_thing = Adds("POST", "/api/things/{id}")
every_method_any_thing = Adds("*", "/api/things/{id}")
get_any_number = Adds("GET", r"/api/things/{id:\d+}")
get_more_of_a_thing = Adds("GET", "/api/things/{id}/more")
get_the_rest = Adds("GET", "/api/{rest:.*}")
get_anything_then_stats = Adds("GET", "/{family}/stats")
get_things_with_a_suffix = Adds("GET", "/api/things{suffix}")
starts_and_claims = _StartsAndClaims()


def _error(runtime: Any, row_id: str) -> str:
    return next(row["error"] for row in runtime.report()["rows"] if row["id"] == row_id)


@pytest.mark.parametrize(
    ("server", "row"),
    [
        pytest.param(("GET", "/claimed"), "get_claimed", id="the-same-route"),
        pytest.param(("GET", "/things/{name}"), "get_thing_by_id", id="the-same-path-by-another-name"),
        pytest.param(("*", "/claimed"), "get_claimed", id="the-server-answers-every-method"),
        pytest.param(("GET", "/claimed"), "any_claimed", id="the-row-answers-every-method"),
    ],
)
def test_a_row_cannot_shadow_what_the_server_already_answers(server: tuple[str, str], row: str, tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [row_here(HERE, row)])
    runtime.web.app.router.add_route(*server, _the_servers)

    runtime.load()

    assert state_of(runtime, row) == "failed"
    assert "the server already holds" in _error(runtime, row)
    assert list(runtime.web._router._live.routes()) == []


def test_a_row_refused_on_a_running_server_leaves_the_server_answering(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [row_here(HERE, "get_claimed", on=False)])
        runtime.web.app.router.add_get("/claimed", _the_servers)
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            report = await runtime.turn_on("get_claimed")

            assert report["state"] == "failed"
            assert "GET /claimed" in report["error"]
            assert await (await client.get("/claimed")).text() == "the server's"

    asyncio.run(scenario())


def test_a_row_may_add_a_method_the_server_does_not_answer_on_that_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [row_here(HERE, "post_claimed")])
        runtime.web.app.router.add_get("/claimed", _the_servers)
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert state_of(runtime, "post_claimed") == "active"
            assert await (await client.get("/claimed")).text() == "the server's"
            assert (await client.post("/claimed")).status == 200

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("server", "row", "claim"),
    [
        pytest.param(("GET", "/api/exact"), "get_anything", "GET /api/{anything}", id="the-widest-kind"),
        pytest.param(
            ("GET", "/api/things/stats"), "get_any_thing", "GET /api/things/{id}", id="a-family-moved-in-part"
        ),
        pytest.param(("GET", "/api/a/b/c"), "get_the_rest", "GET /api/{rest}", id="a-pattern-that-crosses-slashes"),
        pytest.param(("GET", "/api/stats"), "get_anything_then_stats", "GET /{family}/stats", id="wide-at-the-start"),
        pytest.param(
            ("GET", "/api/thingsX"), "get_things_with_a_suffix", "GET /api/things{suffix}", id="wide-mid-word"
        ),
        pytest.param(
            ("*", "/api/things/stats"), "get_any_thing", "GET /api/things/{id}", id="the-server-takes-every-method"
        ),
        pytest.param(
            ("GET", "/api/things/stats"),
            "every_method_any_thing",
            "* /api/things/{id}",
            id="the-row-takes-every-method",
        ),
    ],
)
def test_a_rows_wide_pattern_cannot_answer_in_place_of_an_exact_server_route(
    server: tuple[str, str], row: str, claim: str, tmp_path: Path
) -> None:
    """The live table is looked at first, so this would win with no error, and a real server would have said nothing."""
    runtime = runtime_with(tmp_path, [row_here(HERE, row)])
    runtime.web.app.router.add_route(*server, _the_servers)

    runtime.load()

    assert state_of(runtime, row) == "failed"
    assert claim in _error(runtime, row)
    assert server[1] in _error(runtime, row)
    assert "the server already holds" in _error(runtime, row)
    assert list(runtime.web._router._live.routes()) == []


def test_a_wide_pattern_refused_on_a_running_server_leaves_the_server_answering_and_the_other_rows_up(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        rows = [row_here(HERE, "get_other"), row_here(HERE, "get_any_thing", on=False)]
        runtime = runtime_with(tmp_path, rows)
        runtime.web.app.router.add_get("/api/things/stats", _the_servers)
        runtime.load()
        runtime.mark_ready()
        async with TestClient(TestServer(runtime.web.app)) as client:
            report = await runtime.turn_on("get_any_thing")

            assert report["state"] == "failed"
            assert "GET /api/things/stats" in report["error"]
            assert await (await client.get("/api/things/stats")).text() == "the server's"
            assert (await client.get("/api/things/7")).status == 404
            assert (await client.get("/other")).status == 200

    asyncio.run(scenario())


def test_a_wide_pattern_is_seen_when_the_server_adds_its_route_after_the_rows_loaded(tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [row_here(HERE, "get_any_thing")])
    runtime.load()
    assert state_of(runtime, "get_any_thing") == "active"
    runtime.web.app.router.add_get("/api/things/stats", _the_servers)

    runtime.mark_ready()

    assert state_of(runtime, "get_any_thing") == "failed"
    assert "GET /api/things/stats" in _error(runtime, "get_any_thing")


def test_a_wide_pattern_may_take_a_method_the_server_does_not_answer_on_that_path(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [row_here(HERE, "post_any_thing")])
        runtime.web.app.router.add_get("/api/things/stats", _the_servers)
        runtime.load()
        async with TestClient(TestServer(runtime.web.app)) as client:
            assert state_of(runtime, "post_any_thing") == "active"
            assert await (await client.get("/api/things/stats")).text() == "the server's"
            assert (await client.post("/api/things/stats")).status == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("row", ["get_any_number", "get_more_of_a_thing"])
def test_a_pattern_that_does_not_reach_the_servers_path_is_no_clash(row: str, tmp_path: Path) -> None:
    runtime = runtime_with(tmp_path, [row_here(HERE, row)])
    runtime.web.app.router.add_get("/api/things/stats", _the_servers)

    runtime.load()

    assert state_of(runtime, row) == "active"


def test_a_rows_pattern_over_a_wide_pattern_of_the_servers_is_not_compared(tmp_path: Path) -> None:
    """A limit the spec states: the check covers what the server claims exactly."""
    runtime = runtime_with(tmp_path, [row_here(HERE, "get_the_rest")])
    runtime.web.app.router.add_get("/api/things/{id}", _the_servers)

    runtime.load()

    assert state_of(runtime, "get_the_rest") == "active"


def test_a_reason_names_what_both_sides_wrote_when_each_used_add_get(tmp_path: Path) -> None:
    """The first clash on the table was HEAD, which neither wrote."""
    runtime = runtime_with(
        tmp_path, [row_here(HERE, "wrote_add_get_claimed"), row_here(HERE, "wrote_add_get_any_thing")]
    )
    runtime.web.app.router.add_get("/claimed", _the_servers)
    runtime.web.app.router.add_get("/api/things/stats", _the_servers)

    runtime.load()

    assert "claims GET /claimed, which the server already holds" in _error(runtime, "wrote_add_get_claimed")
    assert (
        "claims GET /api/things/{id}, which covers GET /api/things/stats, and the server already holds that"
        in _error(runtime, "wrote_add_get_any_thing")
    )


def test_a_reason_names_head_when_head_is_all_that_clashes(tmp_path: Path) -> None:
    """Naming GET here would send the author after a route the server does not hold."""
    runtime = runtime_with(tmp_path, [row_here(HERE, "wrote_add_get_any_thing")])
    runtime.web.app.router.add_route("HEAD", "/api/things/stats", _the_servers)

    runtime.load()

    assert "claims HEAD /api/things/{id}, which covers HEAD /api/things/stats" in _error(
        runtime, "wrote_add_get_any_thing"
    )


def test_a_row_answering_every_method_is_told_about_the_get_and_not_the_head_that_came_with_it() -> None:
    """In the order a set would hand them over, which changes from one run to the next."""
    assert live_routes._held_method("*", ["HEAD", "GET"]) == "GET"
    assert live_routes._held_method("*", ["HEAD"]) == "HEAD"


def test_a_pattern_is_tried_only_against_paths_sharing_its_literal_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish runs on the event loop with 712 server routes to look at, so most of them must not cost a regex."""
    app = web.Application()
    for path in ("/api/a", "/api/things", "/api/things/one", "/api/things/two", "/api/thingz", "/zzz"):
        app.router.add_get(path, _the_servers)

    exact = live_routes._ExactRoutes(app.router.routes())

    assert exact.starting("/api/things/") == ["/api/things/one", "/api/things/two"]
    assert exact.starting("/nothing/") == []

    asked: list[str] = []
    monkeypatch.setattr(exact, "starting", lambda literal: asked.append(literal) or [])
    table = UrlDispatcher()
    table.add_post("/api/things/{id}/more", _the_servers)
    exact.under(next(iter(table.routes())))

    assert asked == ["/api/things/"]


def test_a_row_under_a_wide_pattern_of_the_servers_is_no_clash(tmp_path: Path) -> None:
    """The check runs one way, which the spec states as a limit: the row's exact route answers, and is not refused."""
    runtime = runtime_with(tmp_path, [row_here(HERE, "get_exact")])
    runtime.web.app.router.add_get("/api/{anything}", _the_servers)

    runtime.load()

    assert state_of(runtime, "get_exact") == "active"


def test_a_route_the_server_adds_after_the_rows_loaded_is_seen_when_it_starts(tmp_path: Path) -> None:
    """Rows load while the app is built, and most route families register after them."""

    async def scenario() -> None:
        runtime = runtime_with(tmp_path, [row_here(HERE, "get_claimed"), row_here(HERE, "get_other")])
        runtime.load()
        assert state_of(runtime, "get_claimed") == "active"
        app = runtime.web.app
        app.router.add_get("/claimed", _the_servers)

        async def started(_app: web.Application) -> None:
            runtime.mark_ready()

        app.on_startup.append(started)
        async with TestClient(TestServer(app)) as client:
            assert state_of(runtime, "get_claimed") == "failed"
            assert state_of(runtime, "get_other") == "active"
            assert "the server already holds" in _error(runtime, "get_claimed")
            assert await (await client.get("/claimed")).text() == "the server's"
            assert (await client.get("/other")).status == 200

    asyncio.run(scenario())


def test_a_row_refused_as_the_server_starts_never_starts_its_work(tmp_path: Path) -> None:
    """Nothing it asked to start has started by then, and with no fork left no switch could reach it."""
    runtime = runtime_with(tmp_path, [row_here(HERE, "starts_and_claims")])
    runtime.load()
    runtime.web.app.router.add_get("/claimed", _the_servers)
    began.clear()

    runtime.mark_ready()

    assert began == []
    assert state_of(runtime, "starts_and_claims") == "failed"
    assert "the server already holds" in _error(runtime, "starts_and_claims")


def test_the_shipped_rows_load_and_stay_up_when_a_real_server_starts(tmp_path: Path, monkeypatch: Any) -> None:
    """Every route family has registered by then, so this is the first look at all of them."""

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)):
            rows = await rows_once_started(app[APP_RUNTIME_PLUGINS])
            assert rows  # an empty compare would pass
            assert {row["id"]: row["error"] for row in rows} == {row["id"]: "" for row in rows}
            # Every row the list ships on is up. One it ships off, such as aliveness, is off until you turn it on.
            # Read from the module, because a test that ships a list of its own swaps it there.
            shipped = {
                entry.id: entry.config["enabled"]
                for entry in runtime_plugins.read_profile(runtime_plugins.PROFILE_PATH).entries
            }
            assert {row["id"]: row["state"] for row in rows} == {
                row_id: "active" if on else "off" for row_id, on in shipped.items()
            }

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    asyncio.run(scenario())
