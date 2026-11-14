"""The realtime row, off: its four routes answer 404, a server started that way never loads them, and nothing else moves.

Nothing in Thomas uses this. No page, sidebar or script links to ``/realtime``, so the only way in is its address. As it
ships a setting of its own keeps it switched off: the page opens, the socket says it is disabled and closes, and the page
tries again about twice a second until Connect is pressed again. An upload is refused. Change that setting and the socket stays up, but every message comes back as an error, because the bridge it
falls back on sends ``/api/chat`` a body that route answers with 400. The row exists so that this can be turned off. Its
words say all of that. ``tests/test_the_realtime_socket_through_off_and_on.py`` holds what a session does on a real
server, and ``tests/test_the_realtime_page_through_off_and_on.py`` opens the page in a real browser.

The row writes two keys on the app, so this is also where a row that writes to the app is held to giving them back.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.marketplace.realtime import keys
from thomas.server import app_core
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /realtime": "GET /realtime",
    "GET /static/realtime": "GET /static/realtime/realtime.js",
    "GET /api/realtime/ws": "GET /api/realtime/ws",
    "POST /api/realtime/upload": "POST /api/realtime/upload",
}
OWN_CODE = (
    "thomas.server.rows.realtime",
    "thomas.marketplace.realtime.routes",
    "thomas.marketplace.realtime.ws_handler",
)
SWITCH = "/api/plugins/thomas/realtime"
# aiohttp lists a HEAD beside each GET. A folder of files is listed by its prefix, not by a pattern.
LISTED = {*ROUTES, "HEAD /realtime", "HEAD /static/realtime", "HEAD /api/realtime/ws"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("realtime-off")
    started, found = start_with_one_row_off("realtime", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("realtime-remote")
    started, found = ask_as_a_remote_caller("realtime", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "realtime"}
    assert seen["rows"]["realtime"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    """``/static/realtime/...`` falls through to the server's own ``/static/`` route, which has no such folder."""
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_four_routes_without_a_restart(seen: dict[str, Any]) -> None:
    """The socket answers a plain GET with 400, because it wants an upgrade. An upload is the handler's own refusal
    while the feature's own setting is off, and it is never a 404. That setting lives on the checkout, so ``live_on``
    is what shows the route came back.
    """
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /realtime"] == 200
    assert seen["on"]["GET /static/realtime/realtime.js"] == 200
    assert seen["on"]["GET /api/realtime/ws"] == 400
    assert seen["on"]["POST /api/realtime/upload"] != 404


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so the words promise that the routes go and never that the code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    """The page and its scripts answer 200 to anyone, as they did in the shell: they are files that hold nothing of yours,
    like the rest of Thomas's pages, and what they call is guarded. Only the socket and the upload can show a lost guard.
    """
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {
        "GET /realtime": 200,
        "GET /static/realtime/realtime.js": 200,
        "GET /api/realtime/ws": 401,
        "POST /api/realtime/upload": 401,
    }
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_the_upload_asks_the_guard_the_server_hands_the_row() -> None:
    """The test above cannot see this guard go, because the server refuses any POST under ``/api/`` before a row is reached.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the route. The guard is
    read back from the app at each request and a missing one lets everyone in, which is why this is asked for by status.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden(text="refused by the guard")

    service = SimpleNamespace(view=lambda _ctx, streams=(): app, require_api_access=refuse)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> tuple[int, str]:
        async with TestClient(TestServer(app)) as client:
            answer = await client.post("/api/realtime/upload", json={})
            return answer.status, await answer.text()

    assert asyncio.run(asked()) == (403, "refused by the guard")


def test_what_the_row_writes_on_the_app_leaves_with_it(tmp_path: Path, own_data_dir: Path) -> None:
    """Its settings and its guard go at off, nothing is left in their place, and on reads the settings afresh."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            written = {keys.CONFIG, keys.REQUIRE_API_ACCESS}
            assert written <= set(app)
            first = app[keys.CONFIG]
            before = set(app)

            pressed = await client.post(f"{SWITCH}/off")
            assert (pressed.status, (await pressed.json())["state"]) == (200, "off")
            assert before - set(app) == written

            pressed = await client.post(f"{SWITCH}/on")
            assert (pressed.status, (await pressed.json())["state"]) == (200, "active")
            assert before <= set(app)
            assert app[keys.CONFIG] is not first

    asyncio.run(scenario())


def test_no_page_opens_this_one_and_nothing_reads_where_it_is_advertised() -> None:
    """The row's words say nothing links to it. If a page starts to, this fails and those words have to change.

    ``thomas/server/routes/chat_v2_voice.py`` names the socket in its status answer, with or without this row, and no
    page reads that answer's ``turn_taking``. A landing runs this only for a change to this row or its routes. A caller
    added anywhere else is found by the full suite.
    """
    wanted = ("/realtime", "api/realtime", "realtime_websocket", "turn_taking")
    kinds = (".js", ".mjs", ".ts", ".tsx", ".html", ".json")
    its_own = {ROOT / "web" / "static" / "realtime", ROOT / "web" / "tests"}
    # What git tracks, so a checkout's downloaded packages and built output are never read.
    tracked = subprocess.run(
        ["git", "ls-files", "--", "thomas/server/web", "web", "extensions", "apps", "desktop"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    walked = [
        ROOT / name
        for name in tracked
        if Path(name).suffix in kinds and (ROOT / name).is_file() and its_own.isdisjoint((ROOT / name).parents)
    ]
    calling = [
        path.relative_to(ROOT).as_posix()
        for path in walked
        if any(word in path.read_text(encoding="utf-8", errors="replace") for word in wanted)
    ]
    assert ROOT / "thomas" / "server" / "web" / "js" / "browser_shell.js" in walked  # an empty walk would pass
    assert calling == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/realtime.py", "thomas/marketplace/realtime/routes.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_realtime_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_realtime_socket_through_off_and_on.py" in chosen
    assert "tests/test_the_realtime_page_through_off_and_on.py" in chosen
    assert "tests/test_realtime_ws.py" in chosen
