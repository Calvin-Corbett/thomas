"""Server boot and Chat-card integration for restart recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.restart_test_isolation import (
    immediate_restart_retries,
    isolate_restart_server,
    isolated_restart_runners,
)
from tests.test_a_restart_does_not_stop_a_thomas_project import GOAL, _app, _restart, _stopped_run
from thomas.core import task_bot_runtime
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.forge.anvil import forge_code_projects
from thomas.notifications import delegation_hooks
from thomas.server import (
    app_lifecycle,
    autopilot_park,
    autopilot_silence,
    chat_delegation,
    chat_delegation_canvas,
    chat_offers,  # noqa: F401 -- provides follow_after_restart, which the restart reaches by name
    chat_self_project,
    green_handoff,
    stale_execution_sweep,
    thomas_project,
)
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes import evolve_agent_routes


async def _nothing() -> None:
    return None


def test_a_restarted_server_carries_the_run_on_by_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _stopped_run(tmp_path)
    restart, starts = _restart(), []
    stub = _app(p.catalog, starts)[APP_PRAXIS_START_CODE_RUN]
    monkeypatch.setattr(evolve_agent_routes, "bind_internal_start", lambda app, *_, **__: app.__setitem__(APP_PRAXIS_START_CODE_RUN, stub))  # fmt: skip
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: p.catalog)
    monkeypatch.setattr(restart, "SETTLE_S", 0.01)
    monkeypatch.setattr(restart, "TICK_S", 0.01)
    isolate_restart_server(monkeypatch)
    monkeypatch.setattr(app_lifecycle, "_log_landing_heartbeat", _nothing)
    monkeypatch.setattr(chat_delegation_canvas, "start_canvas_keepalive", lambda: None)
    monkeypatch.setattr(stale_execution_sweep, "run_stale_execution_sweeper", _nothing)
    monkeypatch.setenv(autopilot_park.LOOP_ENV, "1")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    local = ModelConfig(name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="dummy")
    config = AppConfig(models={"local": local}, default_model="local", server=ServerConfig(access_mode="local"),
                       memory=MemoryConfig(root=str(tmp_path / "memory")))  # fmt: skip

    async def scenario() -> None:
        server = asyncio.ensure_future(app_lifecycle.serve_async(config, host="127.0.0.1", port=port))
        for _ in range(1500):
            if starts or server.done():
                break
            await asyncio.sleep(0.01)
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server

    asyncio.run(scenario())
    assert len(starts) == 1 and starts[0]["conversation_id"] == p.cid, "carried on with no message from you"
    assert starts[0]["message"].startswith(ap.RESTART_PREFIX) and restart.report()["resumed"] == [p.cid]
    life = autopilot_silence.previous_life(p.catalog, time.time() + 3600)
    assert life is not None and life.alive_at >= life.booted_at and not life.stopped, life


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue, greens, catalog, board = (tmp_path / name for name in ("blue", "green", "catalog", "board"))
    for folder in (blue, greens / "work", greens / "git", catalog, board):
        folder.mkdir(parents=True)
    (blue / "README.md").write_text("README.md\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=blue, check=True)
    monkeypatch.setenv("THOMAS_GREEN_ROOT", str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)
    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", lambda *a, **k: None)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    monkeypatch.setattr(chat_delegation, "_start_agent_worker_delegation", None)
    starts: list[dict[str, Any]] = []
    return SimpleNamespace(catalog=catalog, board=board, starts=starts, app=_app(catalog, starts), events=[])


async def _card_when(eid: str, board: Path, done: Any) -> dict[str, Any]:
    card: dict[str, Any] = {}
    for _ in range(500):
        if done(card := task_bot_runtime.get_execution(eid, board) or {}):
            return card
        await asyncio.sleep(0.01)
    raise AssertionError(f"card {eid}: {card.get('state')} -- {card.get('progress_summary')}")


async def _server_stops() -> None:
    """Cancel Chat's card followers as a process restart would."""
    following = [t for t in asyncio.all_tasks() if t.get_name().startswith("thomas-project-card:")]
    for task in following:
        task.cancel()
    await asyncio.gather(*following, return_exceptions=True)
    chat_self_project._FOLLOWED.clear()


def test_the_chat_card_follows_the_project_again_after_the_restart(world: SimpleNamespace) -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        async def emit(event: dict[str, Any]) -> None:
            world.events.append(event)

        first = await chat_self_project.start_background_delegation(
            world.app, session_id="chat-restart", prompt=GOAL, mode="auto", recent_messages=[], emit_event=emit,
            force=True, autonomy_level=5, file_access=2, workspace="project", specialist_id="coding",
        )  # fmt: skip
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        forge_code_projects.update_conversation_settings(world.catalog, cid, {"requested": {"autonomy_level": 5}})
        await _server_stops()
        booted = time.time()
        stale_execution_sweep.sweep_stale_executions(world.board, orphaned_before=datetime.now(timezone.utc))
        closed = task_bot_runtime.get_execution(first["execution_id"], world.board)

        report = await _restart().resume_interrupted(world.app, world.catalog, booted=booted)

        assert report["resumed"] == [cid] and len(world.starts) == 2
        rows = [r for r in chat_delegation.session_active_delegations("chat-restart", repo_root=world.board)
                if r["execution_id"] != first["execution_id"]]  # fmt: skip
        assert len(rows) == 1, rows
        again = await _card_when(rows[0]["execution_id"], world.board, lambda c: c.get("state") == "executing")
        steered = chat_self_project.steer(again["execution_id"], "keep the registry import", world.board)
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))
        await _server_stops()
        return closed, again, steered, {"root": root, "cid": cid}

    closed, again, steered, _ = asyncio.run(scenario())

    assert closed["state"] == "failed" and "interrupted by a restart" in closed["progress_summary"]
    assert again["progress_summary"].startswith(chat_self_project.RESTARTED_TEXT), again["progress_summary"]
    assert again["runtime_profile"]["build_conversation_id"] == world.starts[0]["conversation_id"]
    assert steered["ok"], "the chat can steer it again: something follows it"
    assert json.dumps(again).count("interrupted by a restart") == 0
