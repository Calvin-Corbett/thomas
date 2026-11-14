"""The system-map row, off: its three routes answer 404, a server started that way never loads them, and Thomas goes on.

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
    "GET /system-map": "GET /system-map",
    "GET /system-map/": "GET /system-map/",
    "GET /api/system-map": "GET /api/system-map",
}
# The old address only redirects to Agents, whatever the caller, and the reading it never carried is what holds the
# guard. The test client follows the redirect, so a 200 here is the System page answering. Where the redirect points is
# in tests/test_the_system_map_with_its_row_off.py.
OPEN = {"GET /system-map", "GET /system-map/"}
GUARDED = {route: ask for route, ask in ROUTES.items() if route not in OPEN}
OWN_CODE = ("thomas.server.rows.system_map", "thomas.server.system_map_routes")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.partition(' ')[2]}" for route in ROUTES)}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("system-map-off")
    started, found = start_with_one_row_off("system_map", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("system-map-remote")
    started, found = ask_as_a_remote_caller("system_map", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "system_map"}
    assert seen["rows"]["system_map"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_reading_has_not_loaded_either(seen: dict[str, Any]) -> None:
    """The reading is imported only when the route is asked, so a server that never serves it never loads it."""
    assert "thomas.core.system_map" not in seen["loaded"]


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
    assert remote["no_token"] == {**dict.fromkeys(GUARDED.values(), 401), **dict.fromkeys(OPEN, 200)}
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 200)


@pytest.mark.parametrize(
    "changed",
    ["thomas/server/rows/system_map.py", "thomas/server/system_map_routes.py"],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_system_map_off_touches_only_its_routes.py" in chosen
    assert "tests/test_web_size_split.py" in chosen
    assert "tests/test_the_server_answers_while_git_runs.py" in chosen
