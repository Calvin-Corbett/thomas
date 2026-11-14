"""The browser row, in a server of its own: off at the start loads none of its code, on brings it, and no route comes or goes.

This row has no route, so a 404 proves nothing here. ``thomas.server.rows.browser`` is the row, ``thomas.tools.browser``
is the Playwright code it lends and closes, and ``thomas.tools.browser_parity`` adds the page-console and network tools. A
change to ``thomas.server.app_helpers`` or ``thomas.server.worker_runtime``, where a run is given what the row lent, runs
this file too, and ``tests/test_turning_browser_off_stops_the_browser.py`` holds what the row does with a session.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.row_off_fixture import start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

OWN_CODE = ("thomas.server.rows.browser", "thomas.tools.browser", "thomas.tools.browser_parity")
ROW = "browser"

# Read at each press. Whether the module is there is asked first, because asking for its state would import it.
READING = """\
def reading():
    module = sys.modules.get("thomas.tools.browser")
    state = getattr(module, "_STATE", None)
    return {"imported": module is not None, "stopped": bool(getattr(state, "stopped", False))}


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("browser-off")
    started, found = start_with_one_row_off(ROW, [], folder, reading=READING)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []
    assert seen["read_off"] == {"imported": False, "stopped": False}


def test_turning_it_on_loads_it_and_leaves_the_browser_free_to_start_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert seen["read_on"] == {"imported": True, "stopped": False}


def test_it_adds_no_route_and_takes_none(seen: dict[str, Any]) -> None:
    assert seen["live_on"] == seen["live_off"]


def test_turned_off_on_a_running_server_the_browser_is_shut_to_new_calls_and_the_code_stays_loaded(
    seen: dict[str, Any],
) -> None:
    """The module cannot be unloaded, so the words may not say so."""
    assert seen["pressed_off"] == 200
    assert seen["read_off_again"] == {"imported": True, "stopped": True}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/browser.py",
        "thomas/tools/browser.py",
        "thomas/tools/browser_parity.py",
        "thomas/server/app_helpers.py",
        "thomas/server/worker_runtime.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_browser_off_touches_only_its_tools.py" in chosen
    assert "tests/test_turning_browser_off_stops_the_browser.py" in chosen


def test_the_row_file_is_where_the_list_says() -> None:
    from thomas.server.runtime_plugins import PROFILE_PATH, read_profile

    entry = next(row for row in read_profile(PROFILE_PATH).entries if row.id == ROW)
    assert entry.plugin == "thomas.server.rows.browser:plugin"
    assert entry.config["enabled"] is True
    assert (ROOT / "thomas" / "server" / "rows" / "browser.py").is_file()
