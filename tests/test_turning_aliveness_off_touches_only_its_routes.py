"""The aliveness row, off: its thread ends, its code does not load, and no route comes or goes with it.

This row has no route, so a 404 proves nothing here. The row can read off and the sweep go on, and only a test that names
the thread, and reads the loop itself, can see that. ``thomas.server.rows.aliveness`` is the row and
``thomas.core.aliveness`` is the loop it starts. ``thomas.core.engine_manager`` lists the sweep for the tools panel and
``thomas.server.aliveness_default`` is where the server starts its engines. No test imports a row, so each of those is
named here, and the other proof of this row names the same two.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.row_off_fixture import start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

OWN_CODE = (
    "thomas.server.rows.aliveness",
    "thomas.core.aliveness",
    "thomas.core.aliveness_drives",
    "thomas.core.aliveness_gate",
    "thomas.core.aliveness_log",
    "thomas.core.aliveness_permissions",
    "thomas.core.aliveness_world",
)
ROW = "aliveness"
THREAD = "thomas-aliveness"

# Read at each of the three presses. The loop itself, never a new one: asking for it would build it.
READING = """\
def reading():
    loop = getattr(sys.modules.get("thomas.core.aliveness"), "_loop", None)
    return {"built": loop is not None, "running": bool(loop and loop.running)}


"""


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("aliveness-off")
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


def test_with_the_row_off_none_of_its_code_has_loaded_and_no_loop_was_built(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []
    assert THREAD not in seen["threads_off"]
    assert seen["read_off"] == {"built": False, "running": False}


def test_turning_it_on_starts_the_sweep_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert THREAD in seen["threads_on"]
    assert seen["read_on"] == {"built": True, "running": True}


def test_turning_it_on_adds_no_route_and_turning_it_off_takes_none(seen: dict[str, Any]) -> None:
    assert seen["live_on"] == seen["live_off"]


def test_turned_off_on_a_running_server_the_thread_ends_the_loop_is_forgotten_and_the_code_stays_loaded(
    seen: dict[str, Any],
) -> None:
    """The thread is named, because the row reads off either way. The module cannot be unloaded, so the words may not say so."""
    assert seen["pressed_off"] == 200
    assert THREAD not in seen["threads_off_again"]
    assert seen["read_off_again"] == {"built": False, "running": False}
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/aliveness.py",
        "thomas/core/aliveness.py",
        "thomas/server/aliveness_default.py",
        "thomas/core/engine_manager.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_aliveness_off_touches_only_its_routes.py" in chosen
    assert "tests/test_the_aliveness_setting_decides_its_first_state.py" in chosen


def test_the_row_file_is_where_the_list_says(tmp_path: Path) -> None:
    from thomas.server.runtime_plugins import PROFILE_PATH, read_profile

    entry = next(row for row in read_profile(PROFILE_PATH).entries if row.id == ROW)
    assert entry.plugin == "thomas.server.rows.aliveness:plugin"
    assert entry.config["enabled"] is False  # it begins off, as the loop always did, unless the setting asks for it
