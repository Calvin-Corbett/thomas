"""The Jobs and Work words, a sentence at a time, each with the test that shows it.

The words are what the Plugins page tells you, so none of them lands on the strength of having been true once. The
pages in them were read off a real browser on a scratch server with the row on and then off, and
``tests/test_the_work_pages_when_the_row_is_off.py`` holds those. What a browser cannot see is here: what the bridge
from Work hands to the job queue, that queued jobs and Work jobs stay saved through off and on, that a benchmark is
ended, and what Stop now cuts.

Proofs of ``thomas.server.rows.work``. The routes are in ``tests/test_turning_work_off_touches_only_its_routes.py`` and
the engine in ``tests/test_turning_work_off_closes_the_engine_it_started.py``.
"""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient

from tests import plugin_view_fixture as views
from tests.row_proof_fixture import ROOT, ROWS
from tests.work_row_fixture import BOOTSTRAP, OFF, ON, own_folder, row_of, server_with_the_row_on
from thomas.marketplace.autonomy.engine import AutonomyEngine

HERE = "tests/test_the_work_words_are_held.py"
PAGES = "tests/test_the_work_pages_when_the_row_is_off.py"
ROUTES = "tests/test_turning_work_off_touches_only_its_routes.py"
ENGINE = "tests/test_turning_work_off_closes_the_engine_it_started.py"
MISSION = "tests/test_server_mission_control.py"
MISSION_JOBS = "tests/test_server_mission_control_jobs_and_approvals.py"
SYSTEM = "tests/test_the_system_page_is_plain_and_has_its_pages.py"
WORDS = {
    "Runs the job queue and Work.": (ROUTES, "test_turning_it_on_brings_back_all_76_routes_without_a_restart"),
    "The System page, in the sidebar, lists Thomas's tasks and says when approvals are waiting for you, and lets "
    "you stop, retry or run now a job.": (
        (SYSTEM, "test_some_things_can_be_changed_where_you_read_them"),
        (SYSTEM, "test_the_overview_counts_what_needs_you_and_points_to_where"),
        (MISSION, "test_mission_control_includes_topology_and_approvals"),
        (MISSION_JOBS, "test_mission_job_routes_require_token_and_support_mutations"),
    ),
    "Work, next to Chat and Build, keeps your Work jobs with their workflows, accounts, skills and automations, and "
    "hands each automation to the job queue to run.": (
        HERE,
        "test_work_hands_an_automation_to_mission_control_to_run",
    ),
    "The first time a job is made, Thomas starts the engine that runs queued jobs.": (
        MISSION,
        "test_mission_job_create_auto_bootstraps_autonomy_runtime",
    ),
    "Other programs can use the same routes.": (
        ROUTES,
        "test_turning_it_on_brings_back_all_76_routes_without_a_restart",
    ),
    "While this is off, System still opens, but its Tasks page lists no tasks and says the task list could not be "
    "read.": (
        PAGES,
        "test_system_opens_and_its_tasks_page_says_the_list_could_not_be_read",
    ),
    "It asks Thomas again every five seconds, and the page stays usable.": (
        PAGES,
        "test_system_asks_again_every_five_seconds_and_stays_usable",
    ),
    "Work still opens, with no jobs and a red message reading Work returned an unreadable response (404).": (
        PAGES,
        "test_work_opens_with_no_jobs_and_says_it_got_an_unreadable_response",
    ),
    "Virtual Office keeps its rooms and agents and gets no live updates from the job queue.": (
        PAGES,
        "test_virtual_office_keeps_its_rooms_and_gets_no_live_updates",
    ),
    "Jobs already queued do not run while this is off, because the engine that runs them is stopped.": (
        ENGINE,
        "test_off_stops_the_engine_it_started_closes_the_store_and_takes_the_keys_away",
    ),
    "If the engine is running a job when you turn this off, Thomas lets that job finish first, so turning this off "
    "takes as long as the job does.": (HERE, "test_off_waits_for_a_job_the_engine_is_running"),
    "Queued jobs stay saved, and the job list shows them again after this is back on and something has started the "
    "engine.": (HERE, "test_a_queued_job_stays_saved_through_off_and_on"),
    "Turning this back on does not start the engine again: Thomas starts it the next time a job is made or "
    "the autopilot is set up, and until then queued jobs and automations do not run.": (
        HERE,
        "test_turning_it_on_does_not_start_the_engine_again",
    ),
    "Your Work jobs and their workflows stay saved, and Work shows them again when this is back on.": (
        HERE,
        "test_a_work_job_and_its_workflow_stay_saved_through_off_and_on",
    ),
    "A benchmark that is running is ended when this is turned off.": (
        HERE,
        "test_a_benchmark_that_is_running_is_ended_when_the_row_is_turned_off",
    ),
    "Other programs that call these routes get 404.": (
        ROUTES,
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "A request that is still running, such as a Work dashboard being designed, is cut off and may need sending "
    "again.": (HERE, "test_stop_now_cuts_off_a_dashboard_being_designed"),
    "A job the engine is running is cut off too, and may need running again.": (
        HERE,
        "test_stop_now_cuts_off_a_job_the_engine_is_running",
    ),
}


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return own_folder(tmp_path, monkeypatch)


@pytest.fixture
def nothing_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine takes a job off the queue as soon as it starts, and these tests are about what is kept."""

    async def start(self: Any) -> None:
        return None

    monkeypatch.setattr(AutonomyEngine, "start", start)


def _sentences() -> list[str]:
    row = next(row for row in ROWS if row.id == "work").config["words"]
    return [part for key in ("about", "off_means", "stop_now") for part in re.split(r"(?<=\.)\s+", row[key])]


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """A new, changed or dropped sentence fails here until the list has it with a test."""
    assert _sentences() == list(WORDS)
    for sentence, shown in WORDS.items():
        pairs = (shown,) if isinstance(shown[0], str) else shown
        for path, name in pairs:
            assert f"def {name}(" in (ROOT / path).read_text(encoding="utf-8"), (sentence, name)


async def _press(client: TestClient, path: str) -> None:
    assert (await asyncio.wait_for(client.post(path), timeout=60)).status == 200


async def _work_job(client: TestClient) -> None:
    await client.post("/api/work/apps", json={"id": "dispatch", "name": "Dispatch", "goal": "Keep freight moving"})
    job = await client.post(
        "/api/work/apps/dispatch/jobs", json={"id": "coordinator", "name": "Coordinator", "goal": "Plan the day"}
    )
    assert job.status == 201, await job.text()
    path = "/api/work/apps/dispatch/jobs/coordinator"
    made = await client.post(
        f"{path}/workflows", json={"id": "morning", "name": "Morning", "purpose": "Plan the morning", "type": "manual"}
    )
    assert made.status == 201, await made.text()


def test_work_hands_an_automation_to_mission_control_to_run(folder: Path, nothing_runs: None) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            await _work_job(client)
            path = "/api/work/apps/dispatch/jobs/coordinator"
            await client.post(f"{path}/automations", json={"id": "run", "name": "Run", "trigger": {"type": "manual"}})
            await client.patch(f"{path}/workflows/morning", json={"automation_id": "run"})
            await client.patch(f"{path}/workflows/morning", json={"status": "active"})
            run = await client.post(f"{path}/workflows/morning/run-once")
            assert run.status == 202, await run.text()
            mission = (await run.json())["mission"]
            assert mission["delegated"] is True
            store = client.app["autonomy_store"]
            assert store.get_job(mission["job_id"]).payload["work_workflow_id"] == "morning"
            listed = await (await client.get("/api/mission/jobs")).json()
            assert mission["job_id"] in [job["id"] for job in listed["jobs"]]

        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_queued_job_stays_saved_through_off_and_on(folder: Path, nothing_runs: None) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            made = await client.post(
                "/api/mission/jobs",
                json={"kind": "workflow_task", "name": "Keep me", "goal": "Summarize", "requires_approval": True},
            )
            assert made.status == 200, await made.text()
            job_id = (await made.json())["job"]["id"]
            await _press(client, OFF)
            assert (await client.get("/api/mission/jobs")).status == 404
            await _press(client, ON)
            await views.until(lambda: row_of(client.app)["state"] == "active")
            assert (await client.post(BOOTSTRAP)).status == 200
            listed = await (await client.get("/api/mission/jobs")).json()
            assert [job["name"] for job in listed["jobs"] if job["id"] == job_id] == ["Keep me"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_work_job_and_its_workflow_stay_saved_through_off_and_on(folder: Path) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            await _work_job(client)
            await _press(client, OFF)
            assert (await client.get("/api/work/apps/dispatch/jobs/coordinator/workflows")).status == 404
            await _press(client, ON)
            await views.until(lambda: row_of(client.app)["state"] == "active")
            listed = await client.get("/api/work/apps/dispatch/jobs/coordinator/workflows")
            assert [flow["id"] for flow in (await listed.json())["workflows"]] == ["morning"]
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_benchmark_that_is_running_is_ended_when_the_row_is_turned_off(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[Any] = []
    real = asyncio.create_subprocess_exec

    async def a_program_that_waits(*_args: Any, **options: Any) -> Any:
        program = await real(sys.executable, "-c", "import time; time.sleep(300)", **options)
        started.append(program)
        return program

    monkeypatch.setattr(asyncio, "create_subprocess_exec", a_program_that_waits)

    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            assert (await client.post("/api/mission/benchmarks/run", json={})).status == 200
            await views.until(lambda: bool(started))
            assert started[0].returncode is None
            await _press(client, OFF)
            await asyncio.wait_for(started[0].wait(), timeout=30)
            assert started[0].returncode is not None
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stop_now_cuts_off_a_dashboard_being_designed(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def never_designed(*_args: Any) -> Any:
        started.set()
        await asyncio.Event().wait()

    started: Any = None

    async def scenario() -> None:
        nonlocal started
        started = asyncio.Event()
        monkeypatch.setattr("thomas.server.routes.work_dashboard_runtime.design_job_dashboard", never_designed)
        client = await server_with_the_row_on(folder)
        try:
            await _work_job(client)
            design = asyncio.create_task(client.post("/api/work/apps/dispatch/jobs/coordinator/dashboard/design"))
            await asyncio.wait_for(started.wait(), timeout=30)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.wait_for(views.until(lambda: row_of(client.app)["state"] == "unloading"), timeout=30)
            assert not design.done()
            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=60)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)
            assert row_of(client.app)["state"] == "off"
            answer = await asyncio.wait_for(asyncio.gather(design, return_exceptions=True), timeout=30)
            assert isinstance(answer[0], Exception) or answer[0].status >= 500
        finally:
            await client.close()

    asyncio.run(scenario())


async def _engine_with_a_slow_job(client: TestClient, seconds: float) -> list[int]:
    """A started engine with one job whose handler runs for ``seconds``; the list gains an item if the job finishes."""
    assert (await client.post(BOOTSTRAP)).status == 200
    engine, store = client.app["autonomy_engine"], client.app["autonomy_store"]
    started: asyncio.Event = asyncio.Event()
    finished: list[int] = []

    async def slow(_job: Any) -> dict[str, bool]:
        started.set()
        await asyncio.sleep(seconds)
        finished.append(1)
        return {"ok": True}

    engine.register_handler("reminder", slow)
    store.create_job(name="Slow", kind="reminder", payload={}, schedule=None, next_run_at=datetime.now(timezone.utc))
    engine.wake_up()
    await asyncio.wait_for(started.wait(), timeout=10)
    return finished


def test_off_waits_for_a_job_the_engine_is_running(folder: Path) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            finished = await _engine_with_a_slow_job(client, 1.5)
            turning_off = asyncio.create_task(client.post(OFF))
            await asyncio.sleep(0.4)
            assert not turning_off.done()
            assert finished == []
            assert (await asyncio.wait_for(turning_off, timeout=30)).status == 200
            assert finished == [1]  # the job ran to its end before the row read off
            assert row_of(client.app)["state"] == "off"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_stop_now_cuts_off_a_job_the_engine_is_running(folder: Path) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            finished = await _engine_with_a_slow_job(client, 30)
            turning_off = asyncio.create_task(client.post(OFF))
            await views.until(lambda: row_of(client.app)["state"] == "unloading")
            assert (await asyncio.wait_for(client.post(f"{OFF}?force=1"), timeout=30)).status == 200
            await asyncio.wait_for(turning_off, timeout=30)
            assert row_of(client.app)["state"] == "off"
            assert finished == []
        finally:
            await client.close()

    asyncio.run(scenario())


def test_turning_it_on_does_not_start_the_engine_again(folder: Path) -> None:
    async def scenario() -> None:
        client = await server_with_the_row_on(folder)
        try:
            assert (await client.post(BOOTSTRAP)).status == 200
            await _press(client, OFF)
            await _press(client, ON)
            await views.until(lambda: row_of(client.app)["state"] == "active")
            assert "autonomy_engine" not in client.app  # nothing has started it yet
            assert (await client.post(BOOTSTRAP)).status == 200  # the next use starts it
            assert client.app["autonomy_engine"].is_running
        finally:
            await client.close()

    asyncio.run(scenario())
