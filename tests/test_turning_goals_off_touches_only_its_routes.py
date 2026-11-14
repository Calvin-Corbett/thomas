"""The goals row, off: its six routes answer 404, a server started that way never loads them, and the goals carry on.

The word goals names five things in Thomas, and this row serves one. The routes read and change the list saved with
Thomas's state, which the self-upgrade engine writes. The chat tools write a second list, one for each project, kept in
``.thomas/goals.json``. Life Manager keeps a third in ``.thomas/plugins/life-manager/state.json``,
``/api/evolve/loop/plan`` works out a fourth as ``backlog.goals`` and keeps it nowhere, and Autopilot's goal is what you
asked for, read back out of one conversation. So off cannot stop goals in chat, and these tests hold the row's words to
that.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.core import goal_book
from thomas.core.persistence import PersistenceEngine
from thomas.server.proof.selection import select
from thomas.tools.goals import GoalAddTool

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/goals": "GET /api/goals",
    "GET /api/goals/stats": "GET /api/goals/stats",
    "POST /api/goals": "POST /api/goals",
    "PATCH /api/goals/{goal_id}": "PATCH /api/goals/g1",
    "DELETE /api/goals/{goal_id}": "DELETE /api/goals/g1",
    "POST /api/goals/{goal_id}/run": "POST /api/goals/g1/run",
}
OWN_CODE = ("thomas.server.rows.goals", "thomas.server.routes.goals")
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, "HEAD /api/goals", "HEAD /api/goals/stats"}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("goals-off")
    started, found = start_with_one_row_off("goals", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("goals-remote")
    started, found = ask_as_a_remote_caller("goals", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "goals"}
    assert seen["rows"]["goals"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_the_chat_tools_for_goals_are_still_loaded(seen: dict[str, Any]) -> None:
    assert "thomas.tools.goals" in seen["loaded"]


def test_turning_it_on_brings_back_all_six_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"]["GET /api/goals"] == 200
    assert seen["on"]["GET /api/goals/stats"] == 200


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


def test_no_page_in_the_sidebar_reads_this_list() -> None:
    """The row's words tell you nothing you normally use changes. One script fetches these routes, for two older views.

    If that script gets a new caller, or the sidebar gets a way to those views, this fails and those words have to change.
    A landing runs this only for a change to that script, the sidebar, this row or its routes. A caller added anywhere else
    is found by the full suite.
    """
    web = ROOT / "thomas" / "server" / "web"
    scripts = {path: path.read_text(encoding="utf-8") for path in web.rglob("*.js")}
    pages = [path for path in web.rglob("*.html") if "/api/goals" in path.read_text(encoding="utf-8")]
    fetching = [path.name for path, text in scripts.items() if "/api/goals" in text]
    asking = [line for text in scripts.values() for line in text.splitlines() if "goalsRefresh(" in line]
    sidebar = scripts[web / "js" / "browser_shell.js"].partition("const BUILTIN_WS")[2].partition("};")[0]

    assert (pages, fetching) == ([], ["024_mission_control_02.js"])
    assert len(asking) == 2  # where it is written, and the one line that calls it
    assert any("'operations'" in line and "'dashboard'" in line for line in asking), asking
    assert "Library" in sidebar  # an empty read would pass the two below
    assert 'mode: "dashboard"' not in sidebar
    assert 'mode: "operations"' not in sidebar


def test_the_goals_set_in_chat_are_a_different_list_from_the_one_this_row_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words tell you so. If the two lists are ever joined, this fails and those words have to change."""
    engine = PersistenceEngine(state_file=tmp_path / "state.json", report_dir=tmp_path / "reports", auto_save=False)
    monkeypatch.setattr("thomas.core.persistence._engine", engine)

    added = asyncio.run(GoalAddTool(tmp_path).execute({"text": "Every page loads under a second."}))

    assert added.ok, added.error
    assert [goal["text"] for goal in goal_book.open_goals(tmp_path)] == ["Every page loads under a second."]
    assert engine.goals == []


@pytest.mark.parametrize("changed", ["thomas/server/rows/goals.py", "thomas/server/routes/goals.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """No test imports a row, so a check finds these two only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_goals_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_goals_routes.py" in chosen
