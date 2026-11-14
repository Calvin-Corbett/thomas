"""The run history row, off: its ten routes answer 404, a server started that way never loads them, and recording goes on.

The word run names several things in Thomas, and this row is one way into one of them. These routes read the run store in
``.thomas/runs.sqlite3``, the record of each chat turn. The store itself is the server's: it opens as the server starts,
and chat writes to it and Mission Control reads it without passing through a route here. So off cannot stop a recording,
and ``tests/test_the_run_store_carries_on_with_its_row_off.py`` holds the row's words to that.

Two names reach that one file of code. ``thomas.marketplace.observability.run_store`` is what the server opens, and
``thomas.observability.run_store`` is a second copy that only these routes load, with a database path of its own. That
copy is why the registrar opens the store again, and why a server started with the row off never holds it.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.proof.selection import select
from thomas.server.routes import runs

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/runs": "GET /api/runs",
    "GET /api/runs/{run_id}": "GET /api/runs/r1",
    "GET /api/runs/{run_id}/replay": "GET /api/runs/r1/replay",
    "GET /api/runs/{run_id}/events": "GET /api/runs/r1/events",
    "POST /api/runs/{run_id}/replay/seek": "POST /api/runs/r1/replay/seek",
    "POST /api/runs/{run_id}/replay/step": "POST /api/runs/r1/replay/step",
    "GET /api/runs/{run_id}/replay_stream": "GET /api/runs/r1/replay_stream",
    "GET /api/runs/{run_id}/export": "GET /api/runs/r1/export",
    "GET /api/runs/{run_id}/export.json": "GET /api/runs/r1/export.json",
    "POST /api/runs/{run_id}/cancel": "POST /api/runs/r1/cancel",
}
OWN_CODE = ("thomas.server.rows.runs", "thomas.server.routes.runs", "thomas.observability.run_store")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.partition(' ')[2]}" for route in ROUTES if route.startswith("GET "))}
TOKEN = "a-token-for-this-test"


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("runs-off")
    started, found = start_with_one_row_off("runs", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("runs-remote")
    started, found = ask_as_a_remote_caller("runs", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "runs"}
    assert seen["rows"]["runs"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_store_the_server_opens_is_still_loaded(seen: dict[str, Any]) -> None:
    assert "thomas.marketplace.observability.run_store" in seen["loaded"]


def test_turning_it_on_brings_back_all_ten_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    # r1 was never recorded, so the handlers answer 404 themselves. live_on above is what tells these from a row that added
    # no routes, and the file named in the docstring asks all ten about a run that was recorded.
    assert seen["on"] == {
        "GET /api/runs": 200,
        "GET /api/runs/r1": 404,
        "GET /api/runs/r1/replay": 404,
        "GET /api/runs/r1/events": 404,
        "POST /api/runs/r1/replay/seek": 404,
        "POST /api/runs/r1/replay/step": 404,
        "GET /api/runs/r1/replay_stream": 404,
        "GET /api/runs/r1/export": 404,
        "GET /api/runs/r1/export.json": 404,
        "POST /api/runs/r1/cancel": 200,  # it says cancelled for any id, and stops nothing: see that file
    }


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does.

    The copy of the store these routes loaded keeps its database path through off and on. Turning on sets it again, to the
    same place.
    """
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


def test_every_route_asks_its_own_guard_for_the_token(tmp_path: Path) -> None:
    """These routes bring their own guard, which reads the config the row hands the registrar.

    The server refuses a POST under ``/api/`` before a row is reached, so the test above cannot see one of the three here
    lose its guard. A bare app has no such refusal. If the row handed over its own empty ``config``, the guard would read
    local mode and let this machine in with no token, which is the failure this test is here to show.
    """
    config = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="remote", api_token=TOKEN),
    )

    async def scenario() -> dict[str, int]:
        app = web.Application()
        runs.register_runs_routes(app, config)
        found = {}
        async with TestClient(TestServer(app)) as client:
            for ask in ROUTES.values():
                method, path = ask.split()
                async with client.request(method, path) as answer:
                    found[ask] = answer.status
        return found

    assert asyncio.run(scenario()) == dict.fromkeys(ROUTES.values(), 401)


@pytest.mark.parametrize("changed", ["thomas/server/rows/runs.py", "thomas/server/routes/runs.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_runs_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_run_store_carries_on_with_its_row_off.py" in chosen
    assert "tests/test_the_run_history_row_says_what_a_window_shows.py" in chosen
    assert "tests/test_server_runs_routes.py" in chosen
