"""The catalog row, off: its 19 routes answer 404, a server started that way never loads them, and your apps stay put.

Three route files make this row, and they are not one store. ``/api/marketplace/*`` is the Marketplace page, and it
reads and changes the record of what you installed. ``/plugins/{plugin_id}/...`` hands out the pages of those installed
apps, and ``/app/{plugin_id}`` is the door a desktop shortcut opens. ``/api/v1/plugins/*`` is a separate thing: the
plugin store this Thomas can host for other computers, with a folder and keys of its own. Thomas itself gets its plugins
from a store on the web, not this one. So off takes pages away and leaves what you installed.

What you see in the window with the row off is shown in a real browser by
``tests/test_the_marketplace_page_when_its_row_is_off.py``, and each sentence of the row's words is listed in
``tests/test_the_plugins_page_speaks_plainly.py`` with the tests that show it. The page's code is
``036_workbench_editors_08.js``, ``025_module_system_command_center_01.js`` and ``marketplace_kernel.js``, and those names
are how a check finds those files when one of them changes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT
from tests.web_fixtures.thomas_chat_fixture import browser_ok
from thomas.server import app_core
from thomas.server.desktop_plugins import is_plugin_enabled, list_installed_plugins
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
GUARDED = {
    "GET /api/marketplace/plugins": "GET /api/marketplace/plugins",
    "GET /api/marketplace/sync": "GET /api/marketplace/sync",
    "GET /api/marketplace/plugins/{plugin_id}/download": "GET /api/marketplace/plugins/p1/download",
    "GET /api/marketplace/installed": "GET /api/marketplace/installed",
    "POST /api/marketplace/plugins/{plugin_id}/install": "POST /api/marketplace/plugins/p1/install",
    "POST /api/marketplace/install-from-deep-link": "POST /api/marketplace/install-from-deep-link",
    "POST /api/marketplace/plugins/{plugin_id}/uninstall": "POST /api/marketplace/plugins/p1/uninstall",
    "POST /api/marketplace/plugins/{plugin_id}/enable": "POST /api/marketplace/plugins/p1/enable",
    "POST /api/marketplace/plugins/{plugin_id}/disable": "POST /api/marketplace/plugins/p1/disable",
    "POST /api/marketplace/import": "POST /api/marketplace/import",
    "GET /plugins/{plugin_id}/{asset_path}": "GET /plugins/p1/index.html",
    "GET /app/{plugin_id}": "GET /app/p1",
    "POST /api/v1/plugins/verify": "POST /api/v1/plugins/verify",
}
# The plugin store, open on purpose to anyone who can reach it: register_plugin_hosting_routes takes no access guard.
PUBLIC = {
    "GET /api/v1/plugins/catalog": "GET /api/v1/plugins/catalog",
    "GET /api/v1/plugins/{id}": "GET /api/v1/plugins/p1",
    "GET /api/v1/plugins/{id}/manual-download": "GET /api/v1/plugins/p1/manual-download",
    "GET /api/v1/plugins/download/{token}": "GET /api/v1/plugins/download/not-a-token",
    "POST /api/v1/plugins/download-token": "POST /api/v1/plugins/download-token",
    "POST /api/v1/plugins/report": "POST /api/v1/plugins/report",
}
ROUTES = {**GUARDED, **PUBLIC}
OWN_CODE = (
    "thomas.server.rows.catalog",
    "thomas.server.routes.marketplace_catalog_aiohttp",
    "thomas.server.routes.plugin_hosting",
    "thomas.server.routes.standalone_app_aiohttp",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.removeprefix('GET ')}" for route in ROUTES if route.startswith("GET "))}
# So the sync route's calls to the store on the web fail at once and it falls back to the local catalog, and the answer
# does not depend on the network. Nothing listens on this port.
NO_WAY_OUT = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("catalog-off")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("HTTPS_PROXY", NO_WAY_OUT)
        started, found = start_with_one_row_off("catalog", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("catalog-remote")
    with pytest.MonkeyPatch.context() as env:
        env.setenv("HTTPS_PROXY", NO_WAY_OUT)
        started, found = ask_as_a_remote_caller("catalog", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "catalog"}
    assert seen["rows"]["catalog"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_19_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        "GET /api/marketplace/plugins": 200,
        "GET /api/marketplace/sync": 200,
        "GET /api/marketplace/installed": 200,
        "GET /api/v1/plugins/catalog": 200,
        # Each is told an id or a body it cannot use, and says so. Nothing is installed, and no store is reached.
        "POST /api/marketplace/plugins/p1/install": 400,
        "POST /api/marketplace/install-from-deep-link": 400,
        "POST /api/marketplace/import": 400,
        "POST /api/v1/plugins/verify": 400,
        "POST /api/v1/plugins/download-token": 401,  # it wants the store's own key
        "POST /api/v1/plugins/report": 401,
        "GET /api/v1/plugins/download/not-a-token": 403,
        # 404 from the handlers for an id they do not know, which live_on above tells apart from a route that is gone.
        "GET /api/marketplace/plugins/p1/download": 404,
        "POST /api/marketplace/plugins/p1/uninstall": 404,
        "POST /api/marketplace/plugins/p1/enable": 404,
        "POST /api/marketplace/plugins/p1/disable": 404,
        "GET /plugins/p1/index.html": 404,
        "GET /app/p1": 404,
        "GET /api/v1/plugins/p1": 404,
        "GET /api/v1/plugins/p1/manual-download": 404,
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    Whatever a route file holds at the top level survives off and on the same way, here the store's rate limit and keys.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {
        **dict.fromkeys(GUARDED.values(), 401),
        # The plugin store answers to no token. The catalog is open, an id it does not know answers 404 and a bad
        # download token 403. The last two want the store's own key, which your token is not.
        "GET /api/v1/plugins/catalog": 200,
        "GET /api/v1/plugins/p1": 404,
        "GET /api/v1/plugins/p1/manual-download": 404,
        "GET /api/v1/plugins/download/not-a-token": 403,
        "POST /api/v1/plugins/download-token": 401,
        "POST /api/v1/plugins/report": 401,
    }
    assert {ask: remote["with_token"][ask] for ask in GUARDED.values() if remote["with_token"][ask] == 401} == {}
    assert remote["with_token"]["POST /api/v1/plugins/download-token"] == 401
    assert remote["with_token"]["POST /api/v1/plugins/report"] == 401


def test_an_installed_app_loses_only_its_pages_through_off_and_on(tmp_path: Path, own_data_dir: Path) -> None:
    """The row's words tell you an app stays installed, keeps what it saved, and comes back as it was."""

    async def scenario() -> None:
        config = views.config_in(tmp_path)
        app = app_core.create_app(config)
        async with TestClient(TestServer(app)) as client:
            installed = await client.post("/api/marketplace/plugins/inkwell/install")
            assert installed.status == 200, await installed.text()
            page = (await installed.json())["plugin"]["surface_url"]
            assert (await client.get(page)).status == 200
            note = await client.post("/api/plugins/inkwell/notes", json={"title": "Kept through off and on."})
            assert note.status in {200, 201}, await note.text()

            assert (await client.post("/api/plugins/thomas/catalog/off")).status == 200

            assert (await client.get(page)).status == 404
            assert (await client.get("/app/inkwell")).status == 404
            assert (await client.get("/api/marketplace/installed")).status == 404
            assert [row["plugin_id"] for row in list_installed_plugins(config)] == ["inkwell"]
            assert is_plugin_enabled(config, "inkwell")
            kept = await client.get("/api/plugins/inkwell/bootstrap")  # the companion row serves what an app saved
            assert kept.status == 200
            assert "Kept through off and on." in await kept.text()

            assert (await client.post("/api/plugins/thomas/catalog/on")).status == 200
            runtime = app[APP_RUNTIME_PLUGINS]
            await views.until(lambda: views.state_of(runtime, "catalog") == "active")

            assert (await client.get(page)).status == 200
            assert (await client.get("/app/inkwell", allow_redirects=False)).status == 302

    asyncio.run(scenario())


def test_the_pages_the_words_name_are_the_ones_that_call_these_routes() -> None:
    """The row's words say what each of these pages does, as a real browser showed it, so a new caller has to be read.

    A landing runs this only for a change to this row or its routes. A caller added anywhere else is found by the full
    suite.
    """
    web = ROOT / "thomas" / "server" / "web"
    pages = (*web.rglob("*.js"), *web.rglob("*.html"))
    calling = sorted(path.name for path in pages if "/api/marketplace" in path.read_text(encoding="utf-8"))

    assert calling == [
        "025_module_system_command_center_01.js",  # the Marketplace page
        "browser_shell.js",  # the sidebar and the tabs
        "chat_workspace_navigation.js",  # the sidebar
        "my_stuff.script01.js",  # Library
        "workspace_shell.js",  # a comment about the two above
    ]


def test_a_registrar_that_fails_leaves_the_row_failed_with_its_family_log_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Logged and raised, so the row reads failed. A row that only logged would read active with no routes."""

    def fails(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("no store")

    plugin = importlib.import_module("thomas.server.rows.catalog").plugin
    hosting = importlib.import_module("thomas.server.routes.plugin_hosting")
    monkeypatch.setattr(hosting, "register_plugin_hosting_routes", fails)
    view = MagicMock()
    context = {"web": SimpleNamespace(require_api_access=lambda request: None, view=lambda ctx: view)}

    with caplog.at_level(logging.WARNING), pytest.raises(RuntimeError, match="no store"):
        plugin.apply(context, {})

    assert "Marketplace routes unavailable: no store" in caplog.text


# What holds the row's words about the routes and about the page. A change to rows/default.toml selects the file that
# lists them, tests/test_the_plugins_page_speaks_plainly.py, which has its own test of that.
HOLDERS = (
    "tests/test_turning_catalog_off_touches_only_its_routes.py",
    "tests/test_the_marketplace_page_when_its_row_is_off.py",
)


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/catalog.py",
        "thomas/server/routes/marketplace_catalog_aiohttp.py",
        "thomas/server/routes/plugin_hosting.py",
        "thomas/server/routes/standalone_app_aiohttp.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert set(HOLDERS) <= set(chosen)
    assert "tests/test_server_marketplace_routes.py" in chosen


@pytest.mark.parametrize(
    "script", ["036_workbench_editors_08.js", "025_module_system_command_center_01.js", "marketplace_kernel.js"]
)
def test_a_change_to_the_page_runs_what_holds_its_words(script: str) -> None:
    """A check finds these files by those names in their text, so losing one would leave the page free to drift."""
    chosen = select(ROOT, [f"thomas/server/web/js/runtime/{script}"]).files
    assert set(HOLDERS) <= set(chosen)
