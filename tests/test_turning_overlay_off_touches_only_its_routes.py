"""The overlay row, off: its three routes answer 404, the pages stop carrying your saved changes, and nothing is lost.

The row is ``thomas.server.rows.overlay`` and the routes are in ``thomas.server.routes.ui_overlay_routes``. Its other half
is the injector, which the row installs with ``ctx.effect`` into ``thomas.server.app_middleware_helpers``: with the row off,
``inject_overlay`` hands a page back unchanged. ``thomas.server.routes.ui_redesign_runtime`` is not this row. It stays on,
and it reads the same saved changes without the routes (``tests/test_turning_overlay_off_keeps_your_saved_changes.py``).

The word overlay names this one thing: the file of saved interface changes that Redesign, a theme edit and a rename write.
The CLI in ``thomas/server/overlay/cli.py`` reads and writes the same file with no server, and this row does not reach it.

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
    "GET /api/ui/overlay": "GET /api/ui/overlay",
    "GET /api/ui/overlay/manifest": "GET /api/ui/overlay/manifest",
    "POST /api/ui/overlay/records": "POST /api/ui/overlay/records",
}
OWN_CODE = (
    "thomas.server.rows.overlay",
    "thomas.server.routes.ui_overlay_routes",
    "thomas.server.overlay.render",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/ui/overlay", "HEAD /api/ui/overlay/manifest"}

# Run inside the server, after it is up: does the helper every served page goes through splice anything into a page?
_READING = """\
def reading():
    from thomas.server.app_middleware_helpers import inject_overlay

    page = "<!doctype html><html><head><title>t</title></head><body>b</body></html>"
    return {"changed": inject_overlay(page, "stamp") != page}


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("overlay-off")
    started, found = start_with_one_row_off("overlay", list(ROUTES.values()), folder, reading=_READING)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("overlay-remote")
    started, found = ask_as_a_remote_caller("overlay", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "overlay"}
    assert seen["rows"]["overlay"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_three_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/ui/overlay"] == 200
    assert seen["on"]["GET /api/ui/overlay/manifest"] == 200
    # The handler's own answer to a body with neither records nor an action, which is not a 404 the row could be giving.
    assert seen["on"]["POST /api/ui/overlay/records"] == 400


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_pages_carry_the_overlay_only_while_the_row_is_on(seen: dict[str, Any]) -> None:
    """The injector is what the row installs with ``ctx.effect``, so a page is spliced only between on and off."""
    assert seen["read_off"] == {"changed": False}
    assert seen["read_on"] == {"changed": True}
    assert seen["read_off_again"] == {"changed": False}


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert 401 not in remote["with_token"].values(), remote["with_token"]


@pytest.mark.parametrize(
    ("changed", "proof"),
    [
        ("thomas/server/rows/overlay.py", "tests/test_overlay_routes.py"),
        ("thomas/server/routes/ui_overlay_routes.py", "tests/test_overlay_routes.py"),
        ("thomas/server/app_middleware_helpers.py", "tests/test_overlay_injection_contract.py"),
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str, proof: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_overlay_off_touches_only_its_routes.py" in chosen
    assert proof in chosen
