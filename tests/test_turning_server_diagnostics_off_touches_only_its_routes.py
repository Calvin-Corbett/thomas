"""The server-diagnostics row, off: its three routes answer 404, a server started that way never loads them, and Thomas goes on.

The routes only read: the list of engines the server's engine manager holds, the list of tools in the registry chat
uses, and the landing heartbeat. Turning the row off takes the three routes away and leaves the manager and the registry
alone. The Tools panel on the older full page and the command line's check of a running Thomas read them.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/engines": "GET /api/engines",
    "GET /api/tools": "GET /api/tools",
    "GET /api/landing-health": "GET /api/landing-health",
}
OWN_CODE = ("thomas.server.rows.server_diagnostics", "thomas.server.server_diagnostics_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.partition(' ')[2]}" for route in ROUTES)}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("server-diagnostics-off")
    started, found = start_with_one_row_off("server_diagnostics", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("server-diagnostics-remote")
    started, found = ask_as_a_remote_caller("server_diagnostics", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "server_diagnostics"}
    assert seen["rows"]["server_diagnostics"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_handlers_the_server_keeps_are_still_loaded(seen: dict[str, Any]) -> None:
    """The builder stays in the shell for the security snapshot, so only the registrar can be left unloaded."""
    assert "thomas.server.app_routes_task_ledger" in seen["loaded"]


def test_turning_it_on_brings_back_all_three_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 200)


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


@pytest.mark.parametrize(
    "changed",
    ["thomas/server/rows/server_diagnostics.py", "thomas/server/server_diagnostics_routes.py"],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_server_diagnostics_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_tools_api.py" in chosen
