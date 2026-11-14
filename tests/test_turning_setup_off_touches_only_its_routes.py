"""The setup row, off: its eight routes answer 404, a server started that way never loads them, and the rest stands.

Four of the eight have a page: Easy Setup reads ``/api/setup/bootstrap``, ``/api/local/recommendations`` and
``/api/local/sync``, and its buttons call ``/api/setup/repair``. The other four have none. What Easy Setup shows with the
row off is in ``tests/test_turning_setup_off_what_easy_setup_shows.py``, and what a stop does to work still running is in
``tests/test_turning_setup_off_with_work_running.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import logging
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
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/setup/bootstrap": "GET /api/setup/bootstrap",
    "POST /api/setup/repair": "POST /api/setup/repair",
    "GET /api/setup/diagnostics": "GET /api/setup/diagnostics",
    "GET /api/local/recommendations": "GET /api/local/recommendations",
    "POST /api/local/sync": "POST /api/local/sync",
    "GET /api/local/background": "GET /api/local/background",
    "POST /api/local/background": "POST /api/local/background",
    "POST /api/local/pull": "POST /api/local/pull",
}
OWN_CODE = (
    "thomas.server.rows.setup",
    "thomas.server.routes.setup_aiohttp",
    "thomas.server.routes.setup_local_sync",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {
    *ROUTES,
    "HEAD /api/setup/bootstrap",
    "HEAD /api/setup/diagnostics",
    "HEAD /api/local/recommendations",
    "HEAD /api/local/background",
}
# Goes ahead of each server below. An empty body is all ``POST /api/setup/repair`` needs to run the real script, which
# changes this computer, and asking every route with the row on is the point of these tests. So it is counted, never run.
NO_REAL_REPAIR = """\
import subprocess

repairs = []
_run = subprocess.run


def _count_a_repair(command, *args, **kwargs):
    if "repair.ps1" in str(command):
        repairs.append(str(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    return _run(command, *args, **kwargs)


subprocess.run = _count_a_repair


def reading():
    return len(repairs)


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("setup-off")
    started, found = start_with_one_row_off("setup", list(ROUTES.values()), folder, reading=NO_REAL_REPAIR)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("setup-remote")
    started, found = ask_as_a_remote_caller("setup", list(ROUTES.values()), folder, ahead=NO_REAL_REPAIR)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    return tmp_path / "data"


@pytest.fixture
def repairs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Any repair a test reaches is written down here and never run, so a guard that goes missing cannot run the script."""
    asked: list[str] = []
    real_run = subprocess.run

    def run(command: Any, *args: Any, **kwargs: Any) -> Any:
        if "repair.ps1" not in str(command):
            return real_run(command, *args, **kwargs)
        asked.append(str(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    return asked


def _row(app: web.Application) -> dict[str, Any]:
    return next(row for row in app[APP_RUNTIME_PLUGINS].report()["rows"] if row["id"] == "setup")


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "setup"}
    assert seen["rows"]["setup"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_eight_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {
        **dict.fromkeys(ROUTES.values(), 200),
        # The handlers refuse these two: the test server's one model has no address, and the pull names no model.
        "POST /api/local/sync": 400,
        "POST /api/local/pull": 400,
    }
    assert (seen["read_off"], seen["read_on"]) == (0, 1)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    Whatever a route file holds at the top level survives off and on the same way.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


@pytest.mark.parametrize("ask", ROUTES.values())
def test_every_route_asks_the_guards_the_server_hands_the_row(ask: str, repairs: list[str]) -> None:
    """The test above cannot see a POST's guard go, because the server refuses those before a row is reached.

    So the row is handed guards that refuse everyone, on a bare app with nothing in front of the routes.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    async def nothing(_request: web.Request) -> dict[str, Any]:
        return {}

    service = SimpleNamespace(
        view=lambda _ctx, **_options: app, require_api_access=refuse, require_loopback=refuse, read_json=nothing
    )
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})
    method, path = ask.split()

    async def asked() -> int:
        async with TestClient(TestServer(app)) as client:
            return (await client.request(method, path, json=None if method == "GET" else {})).status

    assert asyncio.run(asked()) == 403
    assert repairs == []


def test_a_repair_also_asks_that_the_caller_is_on_this_computer(repairs: list[str]) -> None:
    """It changes this computer, so the token is not enough, and the guard that says so is a second one."""
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    async def nothing(_request: web.Request) -> dict[str, Any]:
        return {}

    service = SimpleNamespace(
        view=lambda _ctx, **_options: app,
        require_api_access=lambda _request: None,
        require_loopback=refuse,
        read_json=nothing,
    )
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> int:
        async with TestClient(TestServer(app)) as client:
            return (await client.post("/api/setup/repair", json={})).status

    assert asyncio.run(asked()) == 403
    assert repairs == []


def test_a_registrar_that_fails_leaves_the_row_failed_with_its_family_log_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path, own_data_dir: Path
) -> None:
    """``tests/test_server_app_routes_init.py`` pins the line, and would pass with the raise after it gone."""

    def fails(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("a reason you can read")

    module = importlib.import_module("thomas.server.routes.setup_aiohttp")
    monkeypatch.setattr(module, "register_setup_routes", fails)
    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.setup"):
        app = app_core.create_app(views.config_in(tmp_path))

    assert _row(app)["state"] == "failed", _row(app)
    assert "a reason you can read" in _row(app)["error"]
    assert "Setup routes unavailable: a reason you can read" in caplog.text


@pytest.mark.parametrize("missing", ["require_api_access", "require_loopback", "read_json"])
def test_a_server_with_a_guard_missing_gets_no_setup_routes(missing: str, caplog: pytest.LogCaptureFixture) -> None:
    plugin = importlib.import_module(OWN_CODE[0]).plugin
    guards = {"require_api_access": print, "require_loopback": print, "read_json": print, missing: None}

    with caplog.at_level(logging.WARNING, logger="thomas.server.rows.setup"):
        with pytest.raises(RuntimeError, match="no access guard or body reader"):
            plugin.apply({"web": SimpleNamespace(**guards)}, {})

    assert "Setup route registration skipped: missing runtime dependencies" in caplog.text


@pytest.mark.parametrize("changed", ["thomas/server/rows/setup.py", "thomas/server/routes/setup_aiohttp.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_setup_off_touches_only_its_routes.py" in chosen
    assert "tests/test_turning_setup_off_what_easy_setup_shows.py" in chosen
    assert "tests/test_turning_setup_off_with_work_running.py" in chosen
    assert "tests/test_server_setup_routes.py" in chosen
