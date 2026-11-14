"""The upkeep jobs row, off: its one route answers 404, a server started that way never loads it, and the jobs stay put.

Four upkeep jobs sit behind this route: a check of Thomas's own code that can repair two small things, a review that
rewrites the list of upgrade goals, a check of its pages, and a save of new files to git. The route starts them on request
and owns none of them. Whether each also runs by itself is settled when the server starts, by settings the desktop app,
the tray and ``run-ui`` set to off unless you set them yourself, so off here cannot stop those runs and on cannot start
them. ``tests/test_what_the_upkeep_jobs_row_says_is_true.py`` holds what the row's words say about a job that is running.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from scripts import package_release

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "engine_actions"
# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {"POST /api/engine-actions": "POST /api/engine-actions"}
OWN_CODE = ("thomas.server.rows.engine_actions", "thomas.server.routes.engine_actions_aiohttp")
LISTED = set(ROUTES)
# The threads of the three jobs that are on unless a launcher turned them off. Saving to git is off unless you turn it on.
BY_THEMSELVES = {"thomas-code-issue", "thomas-self-upgrade", "thomas-ui-workflow"}
SAVING = "thomas-workspace-sync"
SWITCH_OF = {
    "thomas-code-issue": "THOMAS_CODE_ISSUE_ENGINE_ENABLED",
    "thomas-self-upgrade": "THOMAS_SELF_UPGRADE_ENGINE_ENABLED",
    "thomas-ui-workflow": "THOMAS_UI_WORKFLOW_ENGINE_ENABLED",
    SAVING: "THOMAS_WORKSPACE_SYNC_ENGINE_ENABLED",
}
# Asked in the server's own process at each press. A job told to stop keeps its thread, asleep with its name still listed
# for up to a minute, so only the job can say it has stopped.
WHAT_EACH_JOB_SAYS = """\
def reading():
    from thomas.core.code_issue_engine import get_code_issue_engine
    from thomas.core.self_upgrade_engine import get_self_upgrade_engine
    from thomas.core.ui_workflow_engine import get_ui_workflow_engine
    from thomas.core.workspace_sync_engine import get_workspace_sync_engine

    jobs = {
        "thomas-code-issue": get_code_issue_engine(),
        "thomas-self-upgrade": get_self_upgrade_engine(),
        "thomas-ui-workflow": get_ui_workflow_engine(),
        "thomas-workspace-sync": get_workspace_sync_engine(),
    }
    return {thread: job.status_snapshot()["running"] for thread, job in jobs.items()}


"""


def _a_start(folder: Path, running_by_themselves: set[str]) -> dict[str, Any]:
    """Each job's switch is written out, because a run from a launcher's shell would otherwise find its own settings."""
    with pytest.MonkeyPatch.context() as environment:
        for thread, switch in SWITCH_OF.items():
            environment.setenv(switch, "1" if thread in running_by_themselves else "0")
        started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder, reading=WHAT_EACH_JOB_SAYS)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    return _a_start(tmp_path_factory.mktemp("engine-actions-off"), BY_THEMSELVES)


@pytest.fixture(scope="module")
def seen_with_every_job_set_off(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """How a launcher starts a server unless you set otherwise, where a job a press started has nothing to hide behind."""
    return _a_start(tmp_path_factory.mktemp("engine-actions-jobs-off"), set())


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("engine-actions-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_the_route_without_a_restart(seen: dict[str, Any]) -> None:
    """Asked with an empty body, so no job starts. A 400 here is the handler saying which job, and a 404 is the row."""
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == {"POST /api/engine-actions": 400}


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def _each_job_at_each_press(seen: dict[str, Any]) -> list[tuple[dict[str, bool], set[str]]]:
    """What the jobs said and which of their threads were alive: off at the start, pressed on, pressed off."""
    return [
        (seen[f"read_{when}"], set(SWITCH_OF).intersection(seen[f"threads_{when}"]))
        for when in ("off", "on", "off_again")
    ]


def test_the_jobs_that_run_by_themselves_are_not_touched_either_way(seen: dict[str, Any]) -> None:
    """The row's words call this a separate setting. If a press ever stops one of them, or starts saving, they are wrong."""
    said = {**dict.fromkeys(BY_THEMSELVES, True), SAVING: False}

    assert _each_job_at_each_press(seen) == [(said, BY_THEMSELVES)] * 3


def test_a_job_set_not_to_run_by_itself_stays_that_way_either_way(seen_with_every_job_set_off: dict[str, Any]) -> None:
    """Those same words, from the other side. With every job set off, any job a press started is the only one running."""
    assert _each_job_at_each_press(seen_with_every_job_set_off) == [(dict.fromkeys(SWITCH_OF, False), set())] * 3


def test_a_remote_caller_with_no_token_is_refused_on_every_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == dict.fromkeys(ROUTES.values(), 401)
    assert remote["with_token"] == {"POST /api/engine-actions": 400}


def test_the_route_asks_the_guard_the_server_hands_the_row() -> None:
    """The test above cannot see this guard go, because the server refuses any POST under ``/api/`` before a row is reached.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the route.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    async def nothing(_request: web.Request) -> dict[str, Any]:
        return {}

    service = SimpleNamespace(view=lambda _ctx: app, require_api_access=refuse, read_json=nothing)
    importlib.import_module(OWN_CODE[0]).plugin.apply({"web": service}, {})

    async def asked() -> int:
        async with TestClient(TestServer(app)) as client:
            return (await client.post("/api/engine-actions", json={})).status

    assert asyncio.run(asked()) == 403


def test_nothing_of_ours_calls_this_route() -> None:
    """The row's words tell you nothing you normally use changes. If a page or a script starts calling it, they must change.

    The route's own file is in the answer, so a search that found nothing at all cannot pass.
    """
    places = ("thomas", "web", "extensions", "apps", "desktop", "scripts")
    found = subprocess.run(
        ["git", "grep", "-l", "api/engine-actions", "--", *places], cwd=ROOT, capture_output=True, text=True
    )

    assert found.stderr == ""
    assert found.stdout.split() == ["thomas/server/routes/engine_actions_aiohttp.py"]


def test_a_release_leaves_out_the_script_the_code_check_runs() -> None:
    """The row's words say the code check and the save do nothing in an installed release. A bundle holds no git folder, so
    the save has nothing to save to, and this holds the other half. If the script ever ships, those words must change.
    """
    assert (ROOT / "scripts" / "heartbeat.py").is_file()
    assert package_release._is_excluded("scripts/heartbeat.py") == "not-in-allow-list"


@pytest.mark.parametrize(
    "changed", ["thomas/server/rows/engine_actions.py", "thomas/server/routes/engine_actions_aiohttp.py"]
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """A check finds these three only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_engine_actions_off_touches_only_its_routes.py" in chosen
    assert "tests/test_what_the_upkeep_jobs_row_says_is_true.py" in chosen
    assert "tests/test_the_server_answers_while_git_runs.py" in chosen
