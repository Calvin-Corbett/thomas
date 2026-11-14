"""What the words of the schedules row promise, and a row that fails leaving nothing running.

``tests/test_turning_schedules_off_touches_only_its_routes.py`` holds the row's routes and thread. This file holds the
rest of what ``thomas.server.rows.schedules`` says or leans on: what happens to a task through off and on, and that a
row refused for any reason has started nothing. That dotted name, here, is how a check of the row finds this file.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as fixture
from tests.plugin_view_fixture import state_of
from tests.row_off_fixture import _START_OF_A_SERVER, _in_a_process_of_its_own
from tests.row_proof_fixture import choose
from thomas.core import schedule_executor
from thomas.core.scheduler import TaskScheduler
from thomas.server import app_core
from thomas.server.routes import schedule_routes
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

ROW = "schedules"
TURN_ON = f"/api/plugins/thomas/{ROW}/on"
TURN_OFF = f"/api/plugins/thomas/{ROW}/off"
WORKING_REGISTRAR = schedule_routes.setup_schedule_routes
OVERDUE = "Came due while this was off"

# What both scenes below share. In a process of its own, so a thread is this row's or nobody's, on the real scheduler and
# its real file. Only the step that would start a chat is replaced.
_A_SERVER_AND_A_STAND_IN = (
    _START_OF_A_SERVER
    + """\

from datetime import datetime, timedelta

from thomas.core import schedule_executor
from thomas.core.scheduler import TaskScheduler

turn_on, turn_off = f"/api/plugins/thomas/{row_id}/on", f"/api/plugins/thomas/{row_id}/off"
saved = schedule_executor.schedule_file(Path(memory))
ran = []


async def until(check):
    while not check():
        await asyncio.sleep(0.01)


async def seen_within_a_while(check):
    for _ in range(3000):
        if check():
            return True
        await asyncio.sleep(0.01)
    return False


# Its last worker records the run, then ends. Never read the file to find out: on Windows a read that is open as the save
# replaces the file makes the save fail, and that run's history is lost.
def the_pool_is_done():
    return not any(name.startswith("TaskExec") for name in threads())


def a_new_server():
    return app_core.create_app(AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory)))
"""
)

# A list with one overdue task, a server started with the row off, then what a person would do with the switch.
_THE_LIST_THROUGH_OFF_AND_ON = (
    _A_SERVER_AND_A_STAND_IN
    + """\

running, let_go, ended = threading.Event(), threading.Event(), threading.Event()


def a_stand_in_for_a_chat(goal, channel):
    ran.append(goal)
    if goal == "slow":
        running.set()
        let_go.wait(120)
        ended.set()


schedule_executor.make_subprocess_executor = lambda **_: a_stand_in_for_a_chat


# What `thomas cron` does, in a process of its own: a scheduler of its own, on the same file.
def a_terminal(**options):
    return TaskScheduler(execute_fn=lambda _goal, _channel: None, schedule_path=saved, auto_start=False, **options)


def task_ids_saved():
    return sorted(task["id"] for task in json.loads(saved.read_text(encoding="utf-8"))["tasks"])


async def tasks_on_the_page(client):
    return await (await client.get("/api/schedules")).json()


async def run_the_server():
    app = a_new_server()
    seen = {}
    async with TestClient(TestServer(app)) as client:
        seen["threads_while_off"] = threads()
        a_terminal().add_task("from-a-terminal", "0 0 1 1 *", "Added from a terminal")
        seen["ran_while_off"] = list(ran)

        await client.post(turn_on)
        await until(lambda: ran)
        seen["back_on"] = await tasks_on_the_page(client)

        await client.post("/api/schedules", json={"id": "slow", "cron": "0 0 1 1 *", "task": "slow"})
        await client.post("/api/schedules/slow/run", json={})
        await until(running.is_set)
        off = await client.post(turn_off)
        seen["the_run_had_ended_when_off_answered"] = ended.is_set()
        seen["off_during_a_run"] = (await off.json())["state"]
        seen["threads_during_the_run"] = threads()
        terminal = a_terminal()
        terminal.add_task("added-during-the-run", "0 0 1 1 *", "Added while a run went on")
        terminal.remove_task("from-a-terminal")
        let_go.set()
        await until(the_pool_is_done)
        seen["saved_after_the_run"] = task_ids_saved()
        await client.post(turn_on)
        seen["after_the_run"] = await tasks_on_the_page(client)

        await client.post(turn_off)
        long_ago = datetime.now().astimezone() - timedelta(days=400)
        a_terminal(now_fn=lambda: long_ago).add_task("came-due", "0 0 1 1 *", "Came due during a press")
        await client.post(turn_on)
        seen["came_due_during_a_press_ran"] = await seen_within_a_while(lambda: "Came due during a press" in ran)
        await client.post("/api/schedules", json={"id": "pressed", "cron": "0 0 1 1 *", "task": "Run now"})
        seen["run_now_after_a_press"] = (await client.post("/api/schedules/pressed/run", json={})).status
        seen["run_now_ran"] = await seen_within_a_while(lambda: "Run now" in ran)
    seen["threads_once_closed"] = threads()
    seen["ran"] = ran
    return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)

# Six tasks asked for at once, and four workers. Back on is what makes this easy to reach: all that is overdue comes due
# together. The pool empties only once all it was given has run, so nothing here waits on a clock.
_MORE_TASKS_THAN_WORKERS = (
    _A_SERVER_AND_A_STAND_IN
    + """\

let_go = threading.Event()


def a_stand_in_for_a_chat(goal, channel):
    ran.append(goal)
    let_go.wait(120)


schedule_executor.make_subprocess_executor = lambda **_: a_stand_in_for_a_chat


async def run_the_server():
    app = a_new_server()
    seen = {}
    async with TestClient(TestServer(app)) as client:
        await client.post(turn_on)
        for number in range(1, 7):
            task = {"id": f"slow{number}", "cron": "0 0 1 1 *", "task": f"slow{number}"}
            await client.post("/api/schedules", json=task)
        for number in range(1, 7):
            await client.post(f"/api/schedules/slow{number}/run", json={})
        await until(lambda: len(ran) == 4)
        seen["started_before_off"] = list(ran)
        off = await client.post(turn_off)
        seen["off"] = (await off.json())["state"]
        seen["threads_after_off"] = threads()
        let_go.set()
        await until(the_pool_is_done)
        seen["started_after_off"] = ran[4:]
    return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)


def _scheduler_threads() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if thread.name == "TaskScheduler"}


def _a_list_with_one_overdue_task(path: Path, cron: str, overdue_since: datetime) -> None:
    task = {"id": "overdue", "cron_expr": cron, "goal_text": OVERDUE, "next_run_at": overdue_since.isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 4, "tasks": [task]}), encoding="utf-8")


def _by_id(listed: dict[str, Any]) -> dict[str, Any]:
    return {task["id"]: task for task in listed["tasks"]}


@pytest.fixture(scope="module")
def lived(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("schedules-lived")
    three_years_ago = datetime.now().astimezone() - timedelta(days=3 * 365)
    _a_list_with_one_overdue_task(schedule_executor.schedule_file(folder / "memory"), "0 0 1 1 *", three_years_ago)
    started, found = _in_a_process_of_its_own(_THE_LIST_THROUGH_OFF_AND_ON, ROW, [], folder, on=())
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture(scope="module")
def crowded(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("schedules-crowded")
    started, found = _in_a_process_of_its_own(_MORE_TASKS_THAN_WORKERS, ROW, [], folder, on=())
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What ran, in place of a chat: a real run is a process of its own, with your real home."""
    ran: list[str] = []
    monkeypatch.setattr(
        schedule_executor, "make_subprocess_executor", lambda **_: lambda goal, _channel: ran.append(goal)
    )
    return ran


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_no_task_starts_at_its_time_while_the_row_is_off(lived: dict[str, Any]) -> None:
    assert "TaskScheduler" not in lived["threads_while_off"]
    assert lived["ran_while_off"] == []


def test_a_task_that_came_due_while_off_runs_as_soon_as_the_row_is_back(lived: dict[str, Any]) -> None:
    """Missed three times, and one run: each pass of the list moves a task past up to 51 of its missed times."""
    next_run = datetime.fromisoformat(_by_id(lived["back_on"])["overdue"]["next_run"])

    assert lived["ran"].count(OVERDUE) == 1
    assert next_run > datetime.now().astimezone()


def test_a_task_missed_more_than_fifty_times_runs_more_than_once(tmp_path: Path) -> None:
    """The row's words warn of this. A task due every minute, off for three hours, ran four times, one on each pass."""
    path = tmp_path / "schedules.json"
    now = datetime(2026, 11, 1, 12, 0).astimezone()
    _a_list_with_one_overdue_task(path, "* * * * *", now - timedelta(hours=3))
    ran: list[str] = []
    scheduler = TaskScheduler(
        execute_fn=lambda goal, _channel: ran.append(goal), schedule_path=path, now_fn=lambda: now, auto_start=False
    )

    for _ in range(6):
        scheduler._poll_once()
    scheduler.stop()
    scheduler._executor.shutdown(wait=True)

    assert ran == [OVERDUE] * 4


def test_the_list_stays_and_takes_in_what_a_terminal_added_while_it_was_off(lived: dict[str, Any]) -> None:
    assert set(_by_id(lived["back_on"])) == {"overdue", "from-a-terminal"}
    assert lived["back_on"]["health"]["running"] is True


def test_off_neither_waits_for_nor_ends_a_task_already_running(lived: dict[str, Any]) -> None:
    assert lived["off_during_a_run"] == "off"
    assert "TaskScheduler" not in lived["threads_during_the_run"]
    assert lived["the_run_had_ended_when_off_answered"] is False
    assert [run["ok"] for run in _by_id(lived["after_the_run"])["slow"]["run_history"]] == [True]


def test_what_a_terminal_changed_while_a_run_went_on_stays_when_that_run_ends(lived: dict[str, Any]) -> None:
    """The row says you can still change the list while it is off, and a run from before off must not undo that."""
    kept = {"overdue", "slow", "added-during-the-run"}

    assert set(lived["saved_after_the_run"]) == kept
    assert kept <= set(_by_id(lived["after_the_run"]))
    assert "from-a-terminal" not in _by_id(lived["after_the_run"])


def test_off_and_on_with_a_press_still_runs_a_task(lived: dict[str, Any]) -> None:
    """A row can read active with its thread alive and answer every GET, on a scheduler that can run nothing."""
    assert lived["came_due_during_a_press_ran"] is True
    assert lived["run_now_after_a_press"] == 200
    assert lived["run_now_ran"] is True


def test_a_task_already_waiting_to_start_still_starts_after_off(crowded: dict[str, Any]) -> None:
    """The row's words say so. Four run at once and the rest wait in the pool, which a stop leaves as it is."""
    assert crowded["off"] == "off"
    assert "TaskScheduler" not in crowded["threads_after_off"]
    assert sorted(crowded["started_before_off"]) == ["slow1", "slow2", "slow3", "slow4"]
    assert sorted(crowded["started_after_off"]) == ["slow5", "slow6"]


def test_its_thread_goes_when_the_server_closes(lived: dict[str, Any]) -> None:
    assert "TaskScheduler" not in lived["threads_once_closed"]


def _fails(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("the registrar failed")


def _claims(path: str) -> Callable[..., None]:
    """A registrar that works and also claims a route the server holds, so the row is refused after ``apply`` returned."""

    async def _answer(_request: web.Request) -> web.Response:
        return web.Response()

    def registrar(view: Any, **kwargs: Any) -> None:
        WORKING_REGISTRAR(view, **kwargs)
        view.router.add_get(path, _answer)

    return registrar


# `/api/health` is on the table before rows load, so the row is refused as it loads. The switches join after, so one of
# their routes is found only when the server starts. Either way ``apply`` has returned, and a thread begun inside it has
# no stop coming: the row reads failed, pressing off makes it read off, and the thread outlives the server.
BREAKS = {
    "the registrar raises": _fails,
    "a route held before rows load": _claims("/api/health"),
    "a route held after rows load": _claims("/api/plugins/thomas"),
}


async def _off_and_on_still_work(
    client: TestClient, runtime: Any, before: set[threading.Thread], chats: list[str]
) -> None:
    assert (await client.post(TURN_ON)).status == 200
    assert state_of(runtime, ROW) == "active"
    assert len(_scheduler_threads() - before) == 1
    assert (await client.get("/api/schedules")).status == 200
    assert (await client.post(TURN_OFF)).status == 200
    assert _scheduler_threads() - before == set()
    assert (await client.post(TURN_ON)).status == 200
    assert len(_scheduler_threads() - before) == 1

    task = {"id": "after-off-and-on", "cron": "0 0 1 1 *", "task": "after off and on"}
    assert (await client.post("/api/schedules", json=task)).status == 200
    assert (await client.post("/api/schedules/after-off-and-on/run", json={})).status == 200
    await asyncio.wait_for(fixture.until(lambda: chats), 30)
    assert chats == ["after off and on"]


@pytest.mark.parametrize("broken", BREAKS.values(), ids=BREAKS.keys())
def test_a_row_refused_at_startup_leaves_no_thread_and_can_be_turned_off_and_on(
    broken: Callable[..., None], tmp_path: Path, own_data_dir: Path, chats: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    choose(own_data_dir, on={ROW})
    monkeypatch.setattr(schedule_routes, "setup_schedule_routes", broken)
    before = _scheduler_threads()

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            assert state_of(runtime, ROW) == "failed"
            assert _scheduler_threads() - before == set()

            monkeypatch.setattr(schedule_routes, "setup_schedule_routes", WORKING_REGISTRAR)
            assert (await client.post(TURN_OFF)).status == 200
            assert state_of(runtime, ROW) == "off"
            await _off_and_on_still_work(client, runtime, before, chats)
        assert _scheduler_threads() - before == set()

    asyncio.run(scenario())


@pytest.mark.parametrize("broken", BREAKS.values(), ids=BREAKS.keys())
def test_a_press_that_fails_leaves_no_thread_and_the_next_press_works(
    broken: Callable[..., None], tmp_path: Path, own_data_dir: Path, chats: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    choose(own_data_dir, on=())
    before = _scheduler_threads()

    async def scenario() -> None:
        app = app_core.create_app(fixture.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            runtime = app[APP_RUNTIME_PLUGINS]
            monkeypatch.setattr(schedule_routes, "setup_schedule_routes", broken)
            assert (await client.post(TURN_ON)).status == 200
            assert state_of(runtime, ROW) == "failed"
            assert _scheduler_threads() - before == set()

            monkeypatch.setattr(schedule_routes, "setup_schedule_routes", WORKING_REGISTRAR)
            await _off_and_on_still_work(client, runtime, before, chats)
        assert _scheduler_threads() - before == set()

    asyncio.run(scenario())
