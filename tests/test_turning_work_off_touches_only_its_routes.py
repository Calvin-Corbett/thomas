"""The work row, off: its 76 routes answer 404, a server started that way loads none of their modules, and a guard holds.

The row serves the jobs the System page lists (jobs, approvals, autopilot objectives, benchmarks, the content hub and the live stream)
and Work (apps, jobs, workflows, automations, accounts, connectors and lane proposals). It is ``thomas.server.rows.work``,
its routes are in ``thomas.server.routes.mission`` and ``thomas.server.routes.work``, and they reach
``thomas.server.routes.mission_autonomy_runtime``, ``thomas.server.routes.mission_benchmark_routes`` and
``thomas.server.routes.mission_control_routes``. The page at ``/mission`` is the server's own and is not one of the 76.
What the row does to the engine it starts is in ``tests/test_turning_work_off_closes_the_engine_it_started.py``.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.server.proof.selection import select

ROW = "work"
# Written out, because a list worked out from the row would agree with whatever the row did.
CANONICAL = (
    "DELETE /api/work/apps/{app_id}",
    "DELETE /api/work/apps/{app_id}/jobs/{job_id}",
    "DELETE /api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}",
    "DELETE /api/work/apps/{app_id}/jobs/{job_id}/bindings/{binding_id}",
    "GET /api/mission/autopilot/objectives",
    "GET /api/mission/benchmarks/jobs",
    "GET /api/mission/benchmarks/packs",
    "GET /api/mission/benchmarks/runs",
    "GET /api/mission/benchmarks/runs/{run_id}/artifact/{artifact}",
    "GET /api/mission/content-hub",
    "GET /api/mission/control",
    "GET /api/mission/jobs",
    "GET /api/mission/stream",
    "GET /api/work/accounts",
    "GET /api/work/apps",
    "GET /api/work/apps/{app_id}",
    "GET /api/work/apps/{app_id}/dashboard",
    "GET /api/work/apps/{app_id}/jobs",
    "GET /api/work/apps/{app_id}/jobs/{job_id}",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/activity",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/automations",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/bindings",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/dashboard",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/history",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/memory",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/skills",
    "GET /api/work/apps/{app_id}/jobs/{job_id}/workflows",
    "GET /api/work/apps/{app_id}/onboarding",
    "GET /api/work/connectors",
    "GET /api/work/lane-proposals",
    "GET /api/work/skills",
    "PATCH /api/work/accounts/{account_id}",
    "PATCH /api/work/apps/{app_id}",
    "PATCH /api/work/apps/{app_id}/dashboard",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/dashboard",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/history",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/memory",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}",
    "PATCH /api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}",
    "PATCH /api/work/apps/{app_id}/onboarding",
    "POST /api/mission/alerts/notify",
    "POST /api/mission/approvals/autonomy/{approval_id}/decision",
    "POST /api/mission/approvals/guardrails/resolve",
    "POST /api/mission/autopilot/bootstrap",
    "POST /api/mission/autopilot/objectives",
    "POST /api/mission/autopilot/objectives/{objective_id}/stop",
    "POST /api/mission/benchmarks/jobs/{job_id}/cancel",
    "POST /api/mission/benchmarks/run",
    "POST /api/mission/jobs",
    "POST /api/mission/jobs/{job_id}/cancel",
    "POST /api/mission/jobs/{job_id}/requeue",
    "POST /api/mission/jobs/{job_id}/run_now",
    "POST /api/work/accounts",
    "POST /api/work/accounts/{account_id}/connect",
    "POST /api/work/apps",
    "POST /api/work/apps/{app_id}/artifacts",
    "POST /api/work/apps/{app_id}/jobs",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/artifacts",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/automations",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/automations/{automation_id}/deploy",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/bindings",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/dashboard/actions/{action_id}/run",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/dashboard/design",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/skills",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}/promotion/approve",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}/promotion/request",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/workflows",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}/run-once",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/workflows/{workflow_id}/select",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/{action}",
    "POST /api/work/apps/{app_id}/onboarding/messages",
    "POST /api/work/events/{event_name}",
    "POST /api/work/lane-proposals/{proposal_id}/approve",
    "POST /api/work/lane-proposals/{proposal_id}/reject",
)
# An id that does not exist stands in for each name in braces, so nothing real is asked for or started.
ROUTES = {route: re.sub(r"\{\w+\}", "nope", route) for route in CANONICAL}
OWN_CODE = (
    "thomas.server.rows.work",
    "thomas.server.routes.mission",
    "thomas.server.routes.mission_autonomy_runtime",
    "thomas.server.routes.mission_benchmark_routes",
    "thomas.server.routes.mission_control_routes",
    "thomas.server.routes.work",
)
# aiohttp lists a HEAD beside each GET the mission routes add. The work routes are added with ``add_route`` and have none.
LISTED = {*CANONICAL, *(route.replace("GET", "HEAD") for route in CANONICAL if route.startswith("GET /api/mission/"))}
# A benchmark would start a program of its own, so the process asked below cannot start one.
NO_PROGRAMS = """\
import asyncio


async def _refuse(*args, **kwargs):
    raise OSError("no program may start in this test")


asyncio.create_subprocess_exec = _refuse

"""
READS_NOTHING = "def reading():\n    return None\n\n\n"
# With an empty body on a fresh data folder, so each of these is the handler asking for something and not the row.
ASKS_FOR_SOMETHING = {
    "POST /api/mission/approvals/guardrails/resolve",
    "POST /api/mission/autopilot/objectives",
    "POST /api/mission/jobs",
    "POST /api/work/accounts",
    "POST /api/work/accounts/{account_id}/connect",
    "POST /api/work/apps",
    "POST /api/work/apps/{app_id}/artifacts",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/artifacts",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/automations",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/bindings",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/skills",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/skills/{skill_id}/promotion/approve",
    "POST /api/work/apps/{app_id}/jobs/{job_id}/workflows",
    "POST /api/work/apps/{app_id}/onboarding/messages",
    "POST /api/work/events/{event_name}",
}
# An id that is not there gets the handler's own 404. ``seen["live_on"]`` is what shows the row really added the route.
NOT_THERE = {route for route in CANONICAL if "{" in route and route not in ASKS_FOR_SOMETHING}
ON = {ROUTES[route]: 400 if route in ASKS_FOR_SOMETHING else 404 if route in NOT_THERE else 200 for route in CANONICAL}
# Nothing in this handler asks for the token, so a caller on another machine with none is answered. It was so before the
# row, and whether it should be is for you.
OPEN_WITH_NO_TOKEN = {"GET /api/mission/content-hub": 200}


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("work-off")
    started, found = start_with_one_row_off(ROW, list(ROUTES.values()), folder, reading=NO_PROGRAMS + READS_NOTHING)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("work-remote")
    started, found = ask_as_a_remote_caller(ROW, list(ROUTES.values()), folder, ahead=NO_PROGRAMS)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != ROW}
    assert seen["rows"][ROW] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert len(ROUTES) == 76
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_76_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ON


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_route_but_one(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    guarded = [route for route in CANONICAL if route not in OPEN_WITH_NO_TOKEN]
    assert {route: remote["no_token"][ROUTES[route]] for route in guarded} == dict.fromkeys(guarded, 401)
    assert {route: remote["no_token"][ROUTES[route]] for route in OPEN_WITH_NO_TOKEN} == OPEN_WITH_NO_TOKEN
    assert 401 not in remote["with_token"].values(), remote["with_token"]


@pytest.mark.parametrize(
    "changed",
    [
        "thomas/server/rows/work.py",
        "thomas/server/routes/mission.py",
        "thomas/server/routes/mission_autonomy_runtime.py",
        "thomas/server/routes/work.py",
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_work_off_touches_only_its_routes.py" in chosen
    if "mission" in changed or changed.endswith("rows/work.py"):
        assert "tests/test_turning_work_off_closes_the_engine_it_started.py" in chosen
