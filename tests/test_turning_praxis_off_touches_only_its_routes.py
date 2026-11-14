"""The Praxis row, off: the Build run channel answers 404, a server started that way never loads it, and Build carries on.

The row serves the one route a Build run's helpers call back into, ``/api/praxis/run/{run_id}/{action}``, and keeps the
registry of runs that route reads. It has no page: ``thomas/forge/anvil/run_channel_client.py`` is its only caller, and it
runs inside the Build run. A run started with the row off gets no channel, and Build goes on without one. A run already
going is held by this row until it ends, which ``tests/test_turning_praxis_off_with_a_run_going.py`` holds.

This is the proof of ``thomas.server.rows.praxis``, ``thomas.server.routes.praxis_run_routes`` and
``thomas.server.praxis.startup``, for the routes and the code.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, ask_from_another_machine, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did. One route, eight actions.
ACTIONS = ("spawn", "admit_builder", "report_builder", "delete", "wait", "status", "stop_child", "heartbeat")
ROUTES = {f"POST /api/praxis/run/{{run_id}}/{action}": f"POST /api/praxis/run/r1/{action}" for action in ACTIONS}
ONE_ROUTE = "POST /api/praxis/run/{run_id}/{action}"
OWN_CODE = (
    "thomas.server.rows.praxis",
    "thomas.server.routes.praxis_run_routes",
    "thomas.server.praxis.startup",
)


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("praxis-off")
    started, found = start_with_one_row_off("praxis", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("praxis-remote")
    started, found = ask_as_a_remote_caller("praxis", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "praxis"}
    assert seen["rows"]["praxis"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_action_answers_404_and_the_route_is_not_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert ONE_ROUTE not in seen["listed_off"]
    assert ONE_ROUTE not in seen["live_off"]


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_the_route_without_a_restart(seen: dict[str, Any]) -> None:
    """A run that was never opened answers 404 from the handler too, so the live table is what shows the row is back."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert ONE_ROUTE in seen["live_on"]
    assert seen["on"] == dict.fromkeys(ROUTES.values(), 404)


def test_turned_off_on_a_running_server_the_route_goes_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_meets_the_servers_own_refusal_and_the_run_token_after_it(
    remote: dict[str, Any],
) -> None:
    """The route asks for a run's own token and a caller on this machine, not the server's access guard.

    A POST under ``/api/`` is refused by the server before a row is reached, so remote mode shows 401 with no token. With
    the server's token the request reaches the handler, which knows no run called ``r1`` and says 404.
    """
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == dict.fromkeys(ROUTES.values(), 404)


def test_a_caller_on_another_machine_is_refused_even_with_the_servers_token(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The route asks for a caller on this machine and a run's own token, so the registrar's check must survive the move."""
    folder = tmp_path_factory.mktemp("praxis-elsewhere")
    started, found = ask_from_another_machine("praxis", list(ROUTES.values()), folder)

    assert found is not None, started.stderr[-1500:]
    assert found["row"]["state"] == "active", found["row"]
    assert found["here"] == dict.fromkeys(ROUTES.values(), 404)  # no run called r1
    assert found["elsewhere"] == dict.fromkeys(ROUTES.values(), 403)


def test_no_page_of_ours_calls_this_route() -> None:
    """The row's words tell you no page changes. If a page or a script starts calling it, they must.

    The route's own file and the Build run's client are in the answer, so a search that found nothing cannot pass.
    """
    places = ("thomas", "web", "extensions", "apps", "desktop", "scripts")
    found = subprocess.run(
        ["git", "grep", "-l", "api/praxis/run", "--", *places], cwd=ROOT, capture_output=True, text=True
    )

    named = found.stdout.split()
    assert "thomas/server/routes/praxis_run_routes.py" in named
    assert "thomas/forge/anvil/run_channel_client.py" in named
    assert [name for name in named if name.startswith(("thomas/server/web/", "web/", "extensions/", "apps/"))] == []
    assert [name for name in named if name.startswith(("desktop/", "scripts/"))] == []


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/praxis.py",
        "thomas/server/routes/praxis_run_routes.py",
        "thomas/server/praxis/startup.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_praxis_off_touches_only_its_routes.py" in chosen
    assert "tests/test_turning_praxis_off_with_a_run_going.py" in chosen
    assert "tests/test_praxis_run_channel.py" in chosen
