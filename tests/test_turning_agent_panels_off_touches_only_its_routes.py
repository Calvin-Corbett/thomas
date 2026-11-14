"""The agent panels row, off: its 14 routes answer 404, a server started that way never loads them, and on starts empty.

Three route files make this row, and they share one thing: each keeps what it was told in memory, on a module, and
nowhere else. ``/api/fleet/reply/*`` keeps sessions and the steers sent to them in ``FleetReplyService``,
``/api/run-telemetry*`` keeps turn and token counts in ``RunProjection``, and ``/api/worktree-progress/*`` keeps a task
graph in ``ProgressAggregator``. A module stays loaded after off, so the row clears those three when it stops, or on would
find the old ones.

Nothing in Thomas feeds any of them. Only a program calling these routes does. The word
fleet also names ``thomas/cli/fleet_tui.py`` and ``thomas/core/fleet_management.py``, and telemetry names
``thomas/core/usage_telemetry.py``, none of which touch these stores.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from tests import plugin_view_fixture as views
from tests.row_off_fixture import ask_as_a_remote_caller, start_with_one_row_off
from tests.row_proof_fixture import ROOT
from thomas.agent.fleet_reply import FleetReplyService
from thomas.server import app_core
from thomas.server.proof.selection import select
from thomas.server.routes import fleet_reply_routes, run_telemetry_routes, worktree_progress_routes
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

# Written out, because a list worked out from the row would agree with whatever the row did.
GUARDED = {
    "GET /api/fleet/reply/sessions": "GET /api/fleet/reply/sessions",
    "POST /api/fleet/reply/sessions": "POST /api/fleet/reply/sessions",
    "DELETE /api/fleet/reply/sessions/{session_id}": "DELETE /api/fleet/reply/sessions/s1",
    "POST /api/fleet/reply/sessions/{session_id}/reply": "POST /api/fleet/reply/sessions/s1/reply",
    "POST /api/fleet/reply/receipts/{receipt_id}/ack": "POST /api/fleet/reply/receipts/r1/ack",
    "GET /api/fleet/reply/receipts": "GET /api/fleet/reply/receipts",
    "GET /api/run-telemetry": "GET /api/run-telemetry",
    "GET /api/run-telemetry/snapshot": "GET /api/run-telemetry/snapshot",
    "POST /api/run-telemetry/events": "POST /api/run-telemetry/events",
    "POST /api/run-telemetry/target": "POST /api/run-telemetry/target",
    "POST /api/run-telemetry/reset": "POST /api/run-telemetry/reset",
    "POST /api/worktree-progress/events": "POST /api/worktree-progress/events",
    "POST /api/worktree-progress/reset": "POST /api/worktree-progress/reset",
}
# Not open on purpose. Its registrar takes no guard and its handler asks none, as it was in the shell, and the server only
# refuses POST and the like by itself. So a caller with no token can read what a program reported here.
UNGUARDED = {"GET /api/worktree-progress/snapshot": "GET /api/worktree-progress/snapshot"}
ROUTES = {**GUARDED, **UNGUARDED}
OWN_CODE = (
    "thomas.server.rows.agent_panels",
    "thomas.server.routes.fleet_reply_routes",
    "thomas.server.routes.run_telemetry_routes",
    "thomas.server.routes.worktree_progress_routes",
)
# aiohttp lists a HEAD beside each GET.
LISTED = {*ROUTES, *(f"HEAD {route.removeprefix('GET ')}" for route in ROUTES if route.startswith("GET "))}
# What each asks with an empty body. A 400 is the handler answering. These 404s are too, for an id it does not know, so the
# test reads them from what the row added.
ANSWERS_WITH_THE_ROW_ON = {
    "GET /api/fleet/reply/sessions": 200,
    "POST /api/fleet/reply/sessions": 400,
    "DELETE /api/fleet/reply/sessions/s1": 404,
    "POST /api/fleet/reply/sessions/s1/reply": 400,
    "POST /api/fleet/reply/receipts/r1/ack": 404,
    "GET /api/fleet/reply/receipts": 200,
    "GET /api/run-telemetry": 200,
    "GET /api/run-telemetry/snapshot": 200,
    "POST /api/run-telemetry/events": 400,
    "POST /api/run-telemetry/target": 400,
    "POST /api/run-telemetry/reset": 200,
    "GET /api/worktree-progress/snapshot": 200,
    "POST /api/worktree-progress/events": 400,
    "POST /api/worktree-progress/reset": 200,
}
SESSIONS = "/api/fleet/reply/sessions"
TELEMETRY = "/api/run-telemetry/snapshot"
PROGRESS = "/api/worktree-progress/snapshot"
_WHAT_FEEDS_THEM = re.compile(
    r"\b(FleetReplyService|RunProjection|ProgressAggregator|fleet_reply_routes|run_telemetry_routes"
    r"|worktree_progress_routes)\b|api/(fleet/reply|run-telemetry|worktree-progress)"
)


@pytest.fixture(scope="module")
def seen(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One start for all the tests below, which each read a different part of what it saw."""
    folder = tmp_path_factory.mktemp("agent-panels-off")
    started, found = start_with_one_row_off("agent_panels", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    assert found["home"] == str(folder / "home")
    return found


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    folder = tmp_path_factory.mktemp("agent-panels-remote")
    started, found = ask_as_a_remote_caller("agent_panels", list(ROUTES.values()), folder)
    assert found is not None, started.stderr[-1500:]
    assert started.returncode == 0, started.stderr[-1500:]
    return found


@pytest.fixture
def own_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Saved choices live in the data dir, so a test that turns something off must not share it."""
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def test_with_the_row_off_the_server_starts_and_every_other_row_is_up(seen: dict[str, Any]) -> None:
    others = {row: state for row, state in seen["rows"].items() if row != "agent_panels"}
    assert seen["rows"]["agent_panels"] == "off"
    assert others, "no other row loaded, so this proves nothing about them"
    assert set(others.values()) == {"active"}, others


def test_with_the_row_off_every_route_answers_404_and_none_is_listed(seen: dict[str, Any]) -> None:
    assert seen["off"] == dict.fromkeys(ROUTES.values(), 404)
    assert LISTED.isdisjoint(seen["listed_off"])


def test_with_the_row_off_none_of_its_code_has_loaded(seen: dict[str, Any]) -> None:
    assert [module for module in OWN_CODE if module in seen["loaded"]] == []


def test_turning_it_on_brings_back_all_14_routes_without_a_restart(seen: dict[str, Any]) -> None:
    assert seen["pressed"] == 200
    assert seen["row_on"]["state"] == "active", seen["row_on"]
    assert set(seen["live_on"]) >= LISTED
    assert seen["on"] == ANSWERS_WITH_THE_ROW_ON


def test_turned_off_on_a_running_server_the_routes_go_and_the_code_stays_loaded(seen: dict[str, Any]) -> None:
    """Python cannot unload a module, so a row's words may promise that its routes go and never that its code does."""
    assert seen["pressed_off"] == 200
    assert seen["off_again"] == dict.fromkeys(ROUTES.values(), 404)
    assert [module for module in OWN_CODE if module in seen["loaded_after_press"]] == list(OWN_CODE)


def test_a_remote_caller_with_no_token_is_refused_on_every_guarded_route(remote: dict[str, Any]) -> None:
    assert remote["row"]["state"] == "active", remote["row"]
    assert remote["no_token"] == {**dict.fromkeys(GUARDED.values(), 401), **dict.fromkeys(UNGUARDED.values(), 200)}
    assert remote["with_token"] == ANSWERS_WITH_THE_ROW_ON


def test_the_steer_routes_ask_the_guard_the_server_hands_the_row() -> None:
    """The test above cannot see this go on a POST, because the server refuses those under ``/api/`` before a row is reached.

    So the row is handed a guard that refuses everyone, on a bare app with nothing in front of the routes. The shell
    handed this registrar no guard at all, so the row is the first to ask it.
    """
    app = web.Application()

    def refuse(_request: web.Request) -> None:
        raise web.HTTPForbidden()

    context = MagicMock()  # a stop step is added too, so a plain mapping is not enough
    context.__getitem__.return_value = SimpleNamespace(view=lambda _ctx: app, require_api_access=refuse, config=None)
    importlib.import_module(OWN_CODE[0]).plugin.apply(context, {})

    async def asked() -> dict[str, int]:
        steering = [ask for ask in GUARDED.values() if "/fleet/" in ask]
        async with TestClient(TestServer(app)) as client:
            return {ask: (await client.request(*ask.split(), json={})).status for ask in steering}

    assert asyncio.run(asked()) == dict.fromkeys((ask for ask in GUARDED.values() if "/fleet/" in ask), 403)


def test_off_forgets_what_the_panels_held_and_on_starts_empty(tmp_path: Path, own_data_dir: Path) -> None:
    """All of it lives on a module, which stays loaded after off, so without a stop step on would find the old ones."""

    async def scenario() -> None:
        app = app_core.create_app(views.config_in(tmp_path))
        async with TestClient(TestServer(app)) as client:
            assert (await client.post(SESSIONS, json={"session_id": "s1"})).status == 200
            sent = await client.post(f"{SESSIONS}/s1/reply", json={"text": "Stop and read the test."})
            assert sent.status == 200, await sent.text()
            told = await client.post("/api/run-telemetry/events", json={"kind": "tokens", "tokens": 7})
            assert told.status == 201, await told.text()
            aimed = await client.post("/api/run-telemetry/target", json={"tokens": 100})
            assert aimed.status == 200, await aimed.text()
            began = {"event": "node_started", "worktree_id": "wt-1", "node_id": "n1"}
            assert (await client.post("/api/worktree-progress/events", json=began)).status == 200

            assert [row["reply_count"] for row in (await (await client.get(SESSIONS)).json())["sessions"]] == [1]
            snapshot = (await (await client.get(TELEMETRY)).json())["snapshot"]
            assert (snapshot["cumulative_tokens"], snapshot["target_tokens"]) == (7, 100)
            assert len((await (await client.get(PROGRESS)).json())["snapshot"]["worktrees"]) == 1

            off = await client.post("/api/plugins/thomas/agent_panels/off")
            assert off.status == 200, await off.text()
            assert fleet_reply_routes._SERVICE is None
            assert worktree_progress_routes._AGGREGATOR is None
            assert run_telemetry_routes.get_run_projection().snapshot().cumulative_tokens == 0

            assert (await client.post("/api/plugins/thomas/agent_panels/on")).status == 200
            runtime = app[APP_RUNTIME_PLUGINS]
            await views.until(lambda: views.state_of(runtime, "agent_panels") == "active")

            assert (await (await client.get(SESSIONS)).json())["sessions"] == []
            assert (await (await client.get("/api/fleet/reply/receipts")).json())["receipts"] == []
            snapshot = (await (await client.get(TELEMETRY)).json())["snapshot"]
            assert (snapshot["cumulative_tokens"], snapshot["target_tokens"]) == (0, None)
            assert (await (await client.get(PROGRESS)).json())["snapshot"]["worktrees"] == []

    asyncio.run(scenario())


def test_a_steer_is_kept_where_nothing_can_read_it() -> None:
    """The route drops the only handle to what it keeps, and the test below shows that nothing else reaches the service."""
    service = FleetReplyService()
    app = web.Application()
    fleet_reply_routes.register_fleet_reply_routes(app, None, service_resolver=lambda: service)

    async def scenario() -> None:
        async with TestClient(TestServer(app)) as client:
            assert (await client.post(SESSIONS, json={"session_id": "s1"})).status == 200
            sent = await client.post(f"{SESSIONS}/s1/reply", json={"text": "Stop and read the test."})
            assert (await sent.json())["receipt"]["state"] == "delivered"

    asyncio.run(scenario())

    assert service._sessions["s1"].pending() == 1


def test_the_routes_are_steering_run_telemetry_and_worktree_progress() -> None:
    """The row's first sentence names three sets of routes, and nothing else."""
    prefixes = ("/api/fleet/reply", "/api/run-telemetry", "/api/worktree-progress")
    paths = [ask.split()[1] for ask in ROUTES.values()]
    assert [path for path in paths if not path.startswith(prefixes)] == []
    for prefix in prefixes:
        assert any(path.startswith(prefix) for path in paths), prefix


def test_no_page_in_thomas_calls_these_routes() -> None:
    """The row's words say no page shows them any more. A page that starts calling one makes those words false.

    A landing runs this only for a change to this row or its routes. A caller added anywhere else is found by the full
    suite.
    """
    pages = [
        path
        for folder in (ROOT / "thomas" / "server" / "web", ROOT / "extensions", ROOT / "apps", ROOT / "desktop")
        if folder.is_dir()
        for path in folder.rglob("*")
        if path.suffix in {".html", ".js", ".mjs", ".ts", ".tsx"} and "node_modules" not in path.parts
    ]
    assert pages  # an empty read would pass below
    asked = ("/api/fleet/reply", "/api/run-telemetry", "/api/worktree-progress")
    calling = sorted(
        path.relative_to(ROOT).as_posix()
        for path in pages
        if any(word in path.read_text(encoding="utf-8", errors="replace") for word in asked)
    )

    assert calling == []
    for gone in (
        "frontier.html",
        "js/fleet_reply_panel.js",
        "js/run_telemetry_panel.js",
        "js/worktree_progress_panel.js",
    ):
        assert not (ROOT / "thomas" / "server" / "web" / gone).exists(), gone


def test_nothing_in_thomas_feeds_these_panels() -> None:
    """The row's words say they show only what another program reports. If anything starts feeding them, those must change."""
    feeding = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "thomas").rglob("*.py")
        if _WHAT_FEEDS_THEM.search(path.read_text(encoding="utf-8", errors="replace"))
    }

    assert feeding == {
        "thomas/agent/fleet_reply.py",
        "thomas/observability/run_projection.py",
        "thomas/observability/worktree_progress.py",
        "thomas/server/rows/agent_panels.py",
        "thomas/server/routes/fleet_reply_routes.py",
        "thomas/server/routes/run_telemetry_routes.py",
        "thomas/server/routes/worktree_progress_routes.py",
    }


@pytest.mark.parametrize(
    ("changed", "feature_test"),
    [
        ("thomas/server/rows/agent_panels.py", "tests/test_fleet_reply_routes.py"),
        ("thomas/server/rows/agent_panels.py", "tests/test_run_telemetry_routes.py"),
        ("thomas/server/rows/agent_panels.py", "tests/test_worktree_progress_routes.py"),
        ("thomas/server/routes/fleet_reply_routes.py", "tests/test_fleet_reply_routes.py"),
        ("thomas/server/routes/run_telemetry_routes.py", "tests/test_run_telemetry_routes.py"),
        ("thomas/server/routes/worktree_progress_routes.py", "tests/test_worktree_progress_routes.py"),
    ],
)
def test_a_change_to_the_row_runs_its_proofs(changed: str, feature_test: str) -> None:
    """No test imports a row, so a check finds these only because each spells out the dotted names."""
    chosen = select(ROOT, [changed]).files
    assert "tests/test_turning_agent_panels_off_touches_only_its_routes.py" in chosen
    assert feature_test in chosen
