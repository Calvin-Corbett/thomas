"""The observability row, off: its six routes answer 404, a server started that way never loads them, and work carries on.

Five of the six answer once and ``/ws/events`` stays open, so an open connection must not hold the off switch. No page
in Thomas reads any of them, and only two carry real numbers: ``/api/agents/activity`` and ``/api/task-bots/executions``,
whose counts ``/api/metrics`` repeats. The event list and the live feed are empty, because nothing in Thomas calls
``record_event``, and the tool figures are a fixed empty answer. The System page shows the same tasks from the same
records through a route of its own, so turning this off does not reach it. The row's words say so, and these tests hold them to it.

The word observability also names ``thomas/observability`` and ``thomas/marketplace/observability``, which keep run
records and have nothing to do with these routes.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT, ROWS, choose
from thomas.core import agent_presence, task_bot_runtime
from thomas.server import app_core
from thomas.server.proof.selection import select

# Written out, because a list worked out from the row would agree with whatever the row did.
ROUTES = {
    "GET /api/events": "GET /api/events",
    "GET /api/metrics": "GET /api/metrics",
    "GET /api/agents/activity": "GET /api/agents/activity",
    "GET /api/task-bots/executions": "GET /api/task-bots/executions",
    "GET /api/tools/usage": "GET /api/tools/usage",
    "GET /ws/events": "GET /ws/events",
}
OWN_CODE = ("thomas.server.rows.observability", "thomas.server.routes.observability")
TASK_REPORT = "/api/task-bots/executions"
SWITCH = "/api/plugins/thomas/observability"
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(route.replace("GET", "HEAD") for route in ROUTES)}
# How anything in Thomas would reach ``record_event`` or ``update_metrics``, the only ways to fill what these routes hold.
_IMPORTS_THE_ROUTES = re.compile(
    r"^\s*(?:from|import)\s+(?:thomas\.server\.routes\.observability\b"
    r"|thomas\.server\.routes\s+import\s+[^\n]*\bobservability\b|\.observability\b)",
    re.MULTILINE,
)


def _text_of(path: Path) -> str:
    """A file that is not UTF-8 is read as far as it can be: a route's path is plain text in any of them."""
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("observability-off")
    started, found = start_with_one_row_off("observability", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("observability-remote")
    started, found = ask_as_a_remote_caller("observability", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def started_from(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the server reports on, so a record a test writes lands in no real folder."""
    folder = tmp_path / "started-from"
    folder.mkdir()
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(folder))
    return folder


async def _tasks_in_the_report(client: TestClient) -> list[str]:
    answer = await client.get(TASK_REPORT)
    assert answer.status == 200
    return [task["execution_id"] for task in (await answer.json())["task_bots"]["executions"]]


async def _on_mission_control(client: TestClient) -> dict[str, str]:
    """Each task the page is handed, with the summary it prints. ``fresh`` skips a copy up to 1.5 seconds old."""
    answer = await client.get("/api/mission/control?fresh=1")
    assert answer.status == 200
    tasks = [item for item in (await answer.json())["agents"] if item.get("execution_id")]
    return {item["execution_id"]: item["summary"] for item in tasks}


def _agent_and_task_at_work(name: str, folder: Path) -> str:
    """Write and then change what a background task and an agent keep as they work. Returns the task's id."""
    task = task_bot_runtime.create_execution(session_id="s1", summary=f"{name} task")["execution_id"]
    task_bot_runtime.update_execution(task, progress_summary=f"{name} task, later")
    agent_presence.register_session(repo_root=folder, session_id=name, agent_id="agent", task_summary=f"{name} agent")
    agent_presence.heartbeat_session(repo_root=folder, session_id=name, task_summary=f"{name} agent, later")
    return task


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "observability"}
    assert seen["rows"]["observability"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_with_the_row_off_thomas_goes_on_keeping_agent_and_task_records(
    tmp_path: Path, own_data_dir: Path, started_from: Path
) -> None:
    """The row's words say so, on a server started with it off and on one pressed off, and both have to hold.

    Asked by the row's own report once it is back on, so what is on disk is known to be the records the report reads.
    """
    choose(own_data_dir, on=[row.id for row in ROWS if row.id != "observability"])

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            seen: dict[str, Any] = {"started_off": (await client.get(TASK_REPORT)).status}
            seen["tasks"] = {"started-off": _agent_and_task_at_work("started-off", started_from)}
            await client.post(f"{SWITCH}/on")
            seen["back_on"] = await _tasks_in_the_report(client)
            await client.post(f"{SWITCH}/off")
            seen["pressed_off"] = (await client.get(TASK_REPORT)).status
            seen["tasks"]["pressed-off"] = _agent_and_task_at_work("pressed-off", started_from)
            return seen

    seen = asyncio.run(scenario())

    assert (seen["started_off"], seen["pressed_off"]) == (404, 404)
    assert seen["back_on"] == [seen["tasks"]["started-off"]]
    for name, task in seen["tasks"].items():
        assert (task_bot_runtime.get_execution(task) or {}).get("progress_summary") == f"{name} task, later"
        session = json.loads(agent_presence.session_file_path(name, started_from).read_text(encoding="utf-8"))
        assert session["task_summary"] == f"{name} agent, later"


def test_the_agents_page_shows_these_tasks_with_the_row_off_and_the_words_say_so(
    tmp_path: Path, own_data_dir: Path, started_from: Path
) -> None:
    """The row's words say the System page shows them its own way and is not affected. If that stops, they must change."""
    summary = "A task in the folder Thomas started from."
    task = task_bot_runtime.create_execution(session_id="s1", summary=summary)["execution_id"]

    async def scenario() -> dict[str, Any]:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            seen: dict[str, Any] = {"report": await _tasks_in_the_report(client)}
            seen["page_on"] = await _on_mission_control(client)
            await client.post(f"{SWITCH}/off")
            seen["report_off"] = (await client.get(TASK_REPORT)).status
            seen["page_off"] = await _on_mission_control(client)
            return seen

    seen = asyncio.run(scenario())

    assert seen["report"] == [task]
    assert seen["report_off"] == 404
    assert seen["page_on"] == seen["page_off"] == {task: summary}
    words = next(row for row in ROWS if row.id == "observability").config["words"]
    assert "The System page shows" in words["about"]
    assert "The System page shows" in words["off_means"]


def test_turning_it_on_brings_back_all_six_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    # A plain GET of the websocket is not a websocket, and the handler itself says so.
    assert seen["on"] == {**dict.fromkeys(ROUTES.values(), 200), "GET /ws/events": 400}


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


def test_an_open_websocket_does_not_hold_the_off_switch_and_is_dropped(tmp_path: Path, own_data_dir: Path) -> None:
    """The row's words say a program connected to the live feed is dropped. Without ``streams=`` this press never ends."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            opened = await client.ws_connect("/ws/events")
            assert (await opened.receive_json(timeout=30))["type"] == "connected"
            await opened.send_json({"type": "ping"})
            assert (await opened.receive_json(timeout=30))["type"] == "pong"

            pressed = await asyncio.wait_for(client.post("/api/plugins/thomas/observability/off"), timeout=60)

            assert pressed.status == 200
            assert (await pressed.json())["state"] == "off"
            assert (await opened.receive(timeout=30)).type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED)
            assert (await client.get("/ws/events")).status == 404

    asyncio.run(scenario())


def test_no_page_in_thomas_reads_these_routes() -> None:
    """The row's words tell you nothing you normally use changes. If a page starts reading one, those words must change.

    A landing runs this only for a change to this row or its routes. A caller added anywhere else is found by the full
    suite.
    """
    paths = [ask.split()[1] for ask in ROUTES.values()]
    pages = [
        path
        for folder in (ROOT / "thomas" / "server" / "web", ROOT / "extensions")
        for path in folder.rglob("*")
        if path.suffix in {".html", ".js", ".ts", ".tsx"} and "node_modules" not in path.parts
    ]
    assert ROOT / "thomas" / "server" / "web" / "js" / "browser_shell.js" in pages  # an empty read would pass below

    reading = [path.name for path in pages if any(route in _text_of(path) for route in paths)]

    assert reading == []


def test_nothing_in_thomas_fills_the_event_list_or_the_live_feed() -> None:
    """The row's words say these have nothing in them. If anything starts calling this module, those words must change."""
    importing = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if _IMPORTS_THE_ROUTES.search(_text_of(path))
    ]

    assert importing == ["thomas/server/rows/observability.py"]


def test_the_task_report_reads_only_the_folder_the_server_started_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row's words say so, because a task started in another project is left out of these reports."""
    elsewhere = tmp_path / "another-project"
    elsewhere.mkdir()
    task_bot_runtime.create_execution(session_id="s1", summary="A task in another project.", repo_root=elsewhere)
    started_from = tmp_path / "started-from"
    started_from.mkdir()
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(started_from))

    assert task_bot_runtime.read_summary(refresh=True)["execution_count"] == 0
    assert task_bot_runtime.read_summary(elsewhere, refresh=True)["execution_count"] == 1


@pytest.mark.parametrize("changed", ["thomas/server/rows/observability.py", "thomas/server/routes/observability.py"])
def test_a_change_to_the_row_runs_its_proofs(changed: str) -> None:
    """A check finds these two because each spells out the dotted names, and a change to the row must run them."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_observability_off_touches_only_its_routes.py" in chosen
    assert "tests/test_server_observability_routes.py" in chosen
