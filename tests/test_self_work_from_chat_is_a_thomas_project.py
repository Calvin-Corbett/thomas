"""A Chat request to change Thomas starts a Thomas project: Build's task manager and team, in a green.

You asked: "when thomas works on himself make sure their is a task manegrr just for thomas project like he
does with every new build." Before, Chat gave such a request to one chat worker; in self-fix round 5
(2026-09-24) all five used 12 of 12 attempts, submitted nothing, and lost the changes they had made.

Real here: the chat route handler, the conversation store and registry, the task records, git greens made
from a small stand-in for Thomas's source, the settle and the Autopilot decision. Stubbed: the model (a fake
brain that calls send_task), Build's start hook, and the chat worker's start (so the old path is visible).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import task_bot_runtime
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.notifications import delegation_hooks
from thomas.server import chat_delegation, chat_self_project, green_checkout, green_handoff, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.dial_elevation import _grants as dial_grants
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, local_port
from thomas.server.routes import chat_v2
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.chat_v2_session_routes import handle_steer_delegation
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS

ASK = "Make the Send button blue"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True)


def _slow_create(seconds: float):
    real = green_checkout.create_green

    def create(*, blue: Path, execution_id: str) -> green_checkout.Green:
        time.sleep(seconds)  # in create_green's own thread
        return real(blue=blue, execution_id=execution_id)

    return create


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    blue = tmp_path / "blue"  # stands in for Thomas's own source checkout
    blue.mkdir()
    for name in ("README.md", "AGENTS.md"):
        (blue / name).write_text(f"{name}\n", encoding="utf-8")
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "base")):
        _git(blue, *args)
    greens, catalog, board = tmp_path / "green", tmp_path / "catalog", tmp_path / "board"
    for folder in (greens / "work", greens / "git", catalog, board):  # a green root that exists gets no ACLs set
        folder.mkdir(parents=True)
    monkeypatch.setenv("THOMAS_GREEN_ROOT", str(greens))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(board))  # where the chat's task records live
    monkeypatch.setenv("THOMAS_DB_PATH", str(tmp_path / "preferences.db"))
    from thomas.core import persistence

    monkeypatch.setattr(
        persistence, "_engine", persistence.PersistenceEngine(state_file=tmp_path / "state.json", auto_save=False)
    )
    monkeypatch.setattr(forge_code_projects, "thomas_source_repo_root", lambda: blue)
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: catalog)
    monkeypatch.setattr(green_handoff, "inbox_dir", lambda: tmp_path / "inbox")
    monkeypatch.setattr(green_handoff, "_end_processes", lambda green: None)  # no cage runner in a test
    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", lambda *a, **k: None)  # no desktop toast
    workers: list[dict[str, Any]] = []

    async def worker_start(app: Any, **kwargs: Any) -> dict[str, Any]:  # the old path's worker, never run for real
        workers.append(kwargs)
        row = task_bot_runtime.create_execution(
            session_id=kwargs["session_id"], summary=kwargs["prompt"], backend_type="provider_native", repo_root=board
        )
        return {**row, "session_id": kwargs["session_id"]}

    monkeypatch.setattr(chat_delegation, "_start_agent_worker_delegation", worker_start)
    inbox = tmp_path / "inbox"
    return SimpleNamespace(
        blue=blue, greens=greens, catalog=catalog, board=board, inbox=inbox, workers=workers, starts=[]
    )


def _hook(world: SimpleNamespace, status: int = 200):
    async def start(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        world.starts.append({**body, "port": port})
        stored = forge_code_store.load_conversation(world.catalog, body["conversation_id"]) or {}
        if (stored.get("thomas_project") or {}).get("settled_at"):  # Build's own rule for a settled project
            return 409, {"ok": False, "code": "project_is_thomas_source", "error": "project_is_thomas_source"}
        if status != 200:
            return status, {"ok": False, "error": "another Code run is still active"}
        return 200, {"ok": True, "conversation_id": body["conversation_id"], "run_id": f"run-{len(world.starts)}"}

    return start


class _Brain:
    """The model: asks for one hand-off of work on Thomas himself, timing it on the server's own loop."""

    handoff: list[float] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def process_message(self, session_id, conversation, prompt, dispatcher, **kwargs):  # noqa: ANN001, ANN201
        began = time.perf_counter()
        await kwargs["send_task"](title=ASK, instructions=ASK, workspace="project", specialist="coding")
        _Brain.handoff[:] = [began, time.perf_counter()]
        updated = conversation.append_message("user", prompt).append_message("assistant", "On it.")
        await dispatcher.emit_text("On it.")
        await dispatcher.emit_done(
            session_id=session_id, conversation_version=updated.version, thinking_summary="", total_thinking_ms=0,
            iterations=1, tool_calls=1, tokens_used=0, specialists_used=["reasoning"],
        )  # fmt: skip
        return updated


def test_chat_project_fixture_uses_only_temporary_persistence(world: SimpleNamespace, tmp_path: Path) -> None:
    from thomas.core import persistence

    assert persistence._engine is not None
    assert persistence._engine.state_file == tmp_path / "state.json"
    assert persistence.get_persistence().open_goals() == []


def test_a_chat_request_to_change_thomas_starts_one_thomas_project_and_never_blocks_the_loop(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    projects: list[dict[str, Any]] = []
    real_project = thomas_project.start_thomas_project

    async def spy_project(app: Any, **kwargs: Any) -> dict[str, Any]:
        projects.append(kwargs)
        return await real_project(app, **kwargs)

    monkeypatch.setattr(thomas_project, "start_thomas_project", spy_project)
    monkeypatch.setattr(green_checkout, "create_green", _slow_create(1.0))
    monkeypatch.setattr("thomas.server.routes.chat_v2_support.OrchestratorBrain", _Brain)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)  # the card's follower is not under test here
    monkeypatch.setitem(dial_grants, "autonomy", 4)  # you approved Autopilot (L5)
    local = ModelConfig(name="local", provider="openai_compat", base_url="http://127.0.0.1:1/v1", model="dummy")
    config = AppConfig(
        models={"local": local}, default_model="local", memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )  # fmt: skip

    async def scenario() -> tuple[str, list[float]]:
        from thomas.server.app import create_app

        app = create_app(config)
        app[APP_PRAXIS_START_CODE_RUN] = _hook(world)
        ticks: list[float] = []

        async def ticker() -> None:
            while True:
                ticks.append(time.perf_counter())
                await asyncio.sleep(0.02)

        async with TestClient(TestServer(app)) as client:
            beat = asyncio.ensure_future(ticker())
            body = {"session_id": "chat-self", "profile": "local", "mode": "auto", "autonomy_level": 5}
            response = await client.post("/api/v2/chat", json={**body, "file_access": "project", "message": ASK})
            text = await response.text()
            beat.cancel()
        return text, ticks

    stream, ticks = asyncio.run(scenario())

    assert world.workers == [], "the single chat worker must not start"
    assert len(projects) == 1 and projects[0]["request"] == ASK and projects[0]["settings"]["autonomy_level"] == 5
    (body,) = world.starts
    assert (body["autonomy_level"], body["project_choice"]) == (5, "picked") and body["message"].startswith(ASK)
    assert "changelog.d" in body["message"] and "TITLE:" in body["message"], "the team is told how to record it"
    assert Path(body["project_root"]).parent == world.greens / "work"
    conversation = forge_code_store.load_conversation(Path(body["project_root"]), body["conversation_id"])
    assert conversation["thomas_project"]["chat_session_id"] == "chat-self"
    (row,) = [r for r in task_bot_runtime.list_executions(world.board) if r.get("conversation_id") == "chat-self"]
    card = task_bot_runtime.get_execution(row["execution_id"], world.board)
    assert card["backend_type"] == "thomas_project"
    assert card["runtime_profile"]["build_conversation_id"] == body["conversation_id"]
    assert '"delegation_started"' in stream and body["conversation_id"] in stream
    began, ended = _Brain.handoff
    assert ended - began >= 1.0, "the slow create_green ran inside the hand-off"
    window = [t for t in ticks if began - 0.05 <= t <= ended + 0.05]
    assert len(window) > 10 and max(b - a for a, b in zip(window, window[1:])) < 0.2, "the route held the loop"


def _chat_send(app: Any, sid: str, prompt: str, events: list[dict[str, Any]], level: int = 3):
    async def emit(event: dict[str, Any]) -> None:
        events.append(event)

    return chat_self_project.start_background_delegation(
        app, session_id=sid, prompt=prompt, mode="auto", recent_messages=[], emit_event=emit, force=True,
        autonomy_level=level, file_access=2, workspace="project", specialist_id="coding",
    )  # fmt: skip


@pytest.mark.parametrize("port,status,reason", [(None, 200, "port was not known"), (8898, 409, "still active")])
def test_the_fallback_worker_says_it_is_a_single_worker(
    world: SimpleNamespace, port: int | None, status: int, reason: str
) -> None:
    events: list[dict[str, Any]] = []
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world, status), **({APP_LOCAL_PORT: port} if port else {})}

    record = asyncio.run(_chat_send(app, "chat-fb", ASK, events))

    assert len(world.workers) == 1
    notes = [e["text"] for e in events if e.get("type") == "text"]
    assert len(notes) == 1 and "Started as a single worker because" in notes[0] and reason in notes[0]
    stored = task_bot_runtime.get_execution(record["execution_id"], world.board)
    assert reason in stored["runtime_profile"]["single_worker_because"]
    assert stored["progress_summary"].startswith("Started as a single worker because")
    assert list((world.greens / "work").iterdir()) == [], "a refused start leaves no green behind"


async def _card_state(eid: str, board: Path, want: str) -> dict[str, Any]:
    for _ in range(500):
        card = task_bot_runtime.get_execution(eid, board) or {}
        if card.get("state") == want:
            return card
        await asyncio.sleep(0.01)
    raise AssertionError(f"card {eid} never reached {want}: {card.get('state')} {card.get('progress_summary')}")


def _run_turn(root: Path, cid: str, *, ok: bool, files: list[str]) -> None:
    for name in files:
        (root / name).write_text("changed\n", encoding="utf-8")
    forge_code_store.append_user_turn(root, cid, ASK)
    outcome = "completed" if ok else "failed"
    forge_code_store.append_agent_turn(
        root, cid, model="gpt", transcript="", changed_files=files, returncode=0 if ok else 1, ok=ok, noop=False,
        reason=f"{len(files)} file(s) changed" if ok else "the run crashed before finishing", outcome=outcome,
    )  # fmt: skip


def test_a_follow_up_after_the_project_settles_starts_a_new_one_carrying_the_first(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    outbox = world.board / "outbox"
    outbox.mkdir()
    monkeypatch.setattr("thomas.server.self_change_status.outbox_dir", lambda: outbox)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}

    async def scenario() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        first = await _chat_send(app, "chat-f", ASK, [])
        body = world.starts[0]
        root, cid = Path(body["project_root"]), body["conversation_id"]
        _run_turn(root, cid, ok=True, files=["README.md"])
        await ap.after_run(app, root, world.catalog, cid)  # below Autopilot: the first completed pass settles
        submitted = await _card_state(first["execution_id"], world.board, "awaiting_proof")  # M8: not done yet
        late = chat_delegation.apply_task_update("chat-f", first["execution_id"], "one more thing")
        said["stop"] = chat_delegation.apply_task_update("chat-f", first["execution_id"], cancel=True)  # round 2, N4
        said["asked"] = task_bot_runtime.get_execution(first["execution_id"], world.board)["cancel_requested"]
        verdict = {"status": "landed", "detail": "on dev as abc1234"}  # the promoter, after you approved
        (outbox / f"self-{root.name}.verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
        card = await _card_state(first["execution_id"], world.board, "completed")
        events: list[dict[str, Any]] = []
        await _chat_send(app, "chat-f", "Also make it round", events)
        return submitted, late, card, events

    said: dict[str, Any] = {}
    submitted, late, card, events = asyncio.run(scenario())
    stop, asked_to_cancel = said["stop"], said["asked"]

    assert (
        "Submitted for your approval" in submitted["progress_summary"] and "README.md" in submitted["progress_summary"]
    )
    assert late["ok"] is False and "approval card" in late["error"], "a steer after the hand-off is refused, with why"
    assert stop["ok"] is False and "Windows sign-in" in stop["error"] and asked_to_cancel is False, stop
    assert card["progress_summary"].startswith("Landed") and "abc1234" in card["progress_summary"]
    assert len(world.starts) == 2 and world.starts[1]["conversation_id"] != world.starts[0]["conversation_id"]
    follow_up = world.starts[1]["message"]
    assert follow_up.startswith("Also make it round")
    assert f"Earlier request: {ASK}" in follow_up and "Its outcome: completed" in follow_up
    assert not [e for e in events if e.get("type") == "text"], "no fallback: it started as a Thomas project"
    assert len(list((Path(world.starts[0]["project_root"]).parent).iterdir())) == 1, "only the new green is left"


def test_a_project_that_stops_unfinished_keeps_its_changes_and_the_next_request_resumes_them(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}

    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        first = await _chat_send(app, "chat-k", ASK, [])
        body = world.starts[0]
        _run_turn(Path(body["project_root"]), body["conversation_id"], ok=False, files=["README.md"])
        card = await _card_state(first["execution_id"], world.board, "failed")
        return card, await _chat_send(app, "chat-k", "Carry on", [])

    card, second = asyncio.run(scenario())

    work = Path(world.starts[0]["project_root"])
    kept = card["runtime_profile"]["kept_green"]
    assert (kept["work"], kept["files"]) == (str(work), ["README.md"])
    assert str(work) in card["progress_summary"] and "crashed" in card["progress_summary"]
    assert world.starts[1]["project_root"] == str(work), "the follow-up resumes the kept green"
    assert "unfinished changes are already in this copy" in world.starts[1]["message"]
    # Ruling AD: the new card says plainly whose unfinished changes it carries, and which files.
    assert f'unfinished changes from the earlier request "{ASK}": README.md' in second["last_progress"]
    assert second["runtime_profile"]["resumed_from"]["files"] == ["README.md"]
    assert work.name not in green_checkout.sweep(now=time.time() + 2 * 24 * 3600), "kept past the 24h sweep"


def test_a_start_cancelled_while_create_green_runs_leaves_no_green(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(green_checkout, "create_green", _slow_create(0.5))

    async def scenario() -> None:
        app = {APP_PRAXIS_START_CODE_RUN: _hook(world)}
        start = asyncio.ensure_future(thomas_project.start_thomas_project(app, request=ASK, settings={}, port=1))
        await asyncio.sleep(0.1)
        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start

    asyncio.run(scenario())  # returns only after the executor's threads, create_green's included, have finished

    assert world.starts == []
    assert [p.name for p in (world.greens / "work").iterdir()] == []
    assert [p.name for p in (world.greens / "git").iterdir()] == []


# ── Fix round 1 (review of 299dbf10) ──

STEER_ROUTE = "/api/v2/chat/session/{session_id}/delegations/{execution_id}/steer"


async def _steer_by_route(sid: str, eid: str, text: str) -> dict[str, Any]:
    """The card's real steer route, which the chat page calls; it reaches apply_task_update like update_task does."""
    route = web.Application()
    route.router.add_post(STEER_ROUTE, handle_steer_delegation)
    async with TestClient(TestServer(route)) as client:
        response = await client.post(f"/api/v2/chat/session/{sid}/delegations/{eid}/steer", json={"message": text})
        return await response.json()


def _stopped_for_steering(root: Path, cid: str) -> None:
    """What Build's recorder writes for a run stopped for a steer (evolve_agent_runtime: outcome "stopped")."""
    forge_code_store.append_user_turn(root, cid, ASK)
    forge_code_store.append_agent_turn(
        root, cid, model="gpt", transcript="", changed_files=[], returncode=1, ok=False, noop=False,
        reason="stopped for your steering update", outcome="stopped",
    )  # fmt: skip


def test_i2_a_chat_steer_stops_the_live_build_run_and_the_next_run_starts_with_it(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """You said: "the is no steer mode." The chat said "sent" and nothing ever reached the Build run."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)
    runs: dict[str, Any] = {}
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: runs}
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # stands in for the run's process

    async def scenario() -> dict[str, Any]:
        card = await _chat_send(app, "chat-s", ASK, [])
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        runs[cid] = {"session": {"proc": live, "run_id": "run-1"}, "drain": None}
        reply = await _steer_by_route("chat-s", card["execution_id"], "use green, not blue")
        for _ in range(100):  # the kill runs in the executor
            if live.poll() is not None:
                break
            await asyncio.sleep(0.05)
        runs.pop(cid)  # the run's slot is released once its result is recorded
        _stopped_for_steering(root, cid)
        await ap.after_run(app, root, world.catalog, cid)
        return reply

    try:
        reply = asyncio.run(scenario())
    finally:
        live.kill()

    assert getattr(live, "thomas_stop_requested", "") == "steer" and live.poll() is not None, "the live run stopped"
    assert len(world.starts) == 2 and world.starts[1]["conversation_id"] == world.starts[0]["conversation_id"]
    head, steer_line, _ = world.starts[1]["message"].split("\n\n", 2)
    assert head == f"{ap.STEER_PREFIX} toward the goal: {ASK}" and steer_line == "Steering update: use green, not blue"
    assert reply["ok"] is True and reply["delivery"].startswith("Sent"), "said sent only once it was"


def test_i2_a_steer_between_autopilot_rounds_leads_the_next_rounds_message(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: {}}

    async def scenario() -> dict[str, Any]:
        card = await _chat_send(app, "chat-b", ASK, [], level=5)
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        forge_code_projects.update_conversation_settings(world.catalog, cid, {"requested": {"autonomy_level": 5}})
        _run_turn(root, cid, ok=False, files=[])  # a failed round on Autopilot: the next one is due
        reply = await _steer_by_route("chat-b", card["execution_id"], "keep the old colour")
        await ap.after_run(app, root, world.catalog, cid)
        return reply

    reply = asyncio.run(scenario())

    assert len(world.starts) == 2, "the next round started"
    message = world.starts[1]["message"]
    head, steer_line, _ = message.split("\n\n", 2)
    assert head.startswith(ap.CONTINUATION_PREFIX) and steer_line == "Steering update: keep the old colour"
    assert reply["ok"] is True and reply["delivery"].startswith("Queued"), "said queued only once it was"


def test_i1_starting_a_project_sweeps_an_expired_green_and_spares_fresh_and_kept_ones(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_self_project, "_last_sweep", None, raising=False)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)
    made = {name: green_checkout.create_green(blue=world.blue, execution_id=name) for name in ("old", "fresh", "kept")}
    for name, days in (("old", 2), ("kept", 3)):
        meta_file = made[name].git_dir / green_checkout.METADATA_NAME
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta_file.write_text(json.dumps({**meta, "created_at": meta["created_at"] - days * 86400}), encoding="utf-8")
    green_checkout.mark_kept(made["kept"], "stopped unfinished with changes")

    asyncio.run(_chat_send({APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}, "chat-w", ASK, []))

    left = {folder.name for folder in (world.greens / "work").iterdir()}
    assert "old" not in left and {"fresh", "kept"} <= left


@pytest.mark.parametrize("where", ["start hook", "look-back"])
def test_m1_any_failure_to_start_falls_back_and_says_so(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    async def broken_hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        raise AttributeError("'NoneType' object has no attribute 'pid'")

    def broken_look_back(sid: str, root: Path) -> Any:
        raise AttributeError("'NoneType' object has no attribute 'get'")

    if where == "look-back":
        monkeypatch.setattr(chat_self_project, "_look_back", broken_look_back)
    events: list[dict[str, Any]] = []
    hook = broken_hook if where == "start hook" else _hook(world)

    asyncio.run(_chat_send({APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8898}, "chat-e", ASK, events))

    assert len(world.workers) == 1
    notes = [e["text"] for e in events if e.get("type") == "text"]
    assert len(notes) == 1 and "Started as a single worker because AttributeError" in notes[0]


def test_m2_a_card_that_cannot_open_says_the_project_started(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_board(**kwargs: Any) -> dict[str, Any]:
        raise OSError("the task board could not be written")

    monkeypatch.setattr(task_bot_runtime, "create_execution", no_board)
    events: list[dict[str, Any]] = []

    asyncio.run(_chat_send({APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}, "chat-c", ASK, events))

    (body,) = world.starts
    (note,) = [e["text"] for e in events if e.get("type") == "text"]
    assert "The Thomas project started" in note and body["conversation_id"] in note and "could not open" in note
    assert world.workers == [], "no second attempt as a worker: the project is running"


def test_m3_the_port_is_the_sockets_never_the_host_header() -> None:
    spoofed = SimpleNamespace(transport=None, url=SimpleNamespace(port=4444), app={})
    assert local_port(spoofed) == 0, "no socket and nothing bound: unknown, never the client's Host header"
    assert local_port(SimpleNamespace(transport=None, url=SimpleNamespace(port=80), app={APP_LOCAL_PORT: 8898})) == 8898
    seen: list[int] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(local_port(request))
        return web.Response(text="ok")

    async def scenario() -> int:
        app = web.Application()
        app.router.add_get("/", handler)
        async with TestClient(TestServer(app)) as client:
            await client.get("/", headers={"Host": "127.0.0.1:4444"})
            return int(client.server.port or 0)

    assert seen == [asyncio.run(scenario())]


def test_m4_a_card_on_a_board_of_600_tasks_never_holds_the_loop(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = task_bot_runtime.create_execution(session_id="elsewhere", summary="old task", repo_root=world.board)
    record = json.loads(task_bot_runtime.execution_path(seed["execution_id"], world.board).read_text(encoding="utf-8"))
    for n in range(600):  # a live-sized board: every index rewrite reads all of these
        eid = f"exec-seed{n:06d}"
        task_bot_runtime.execution_path(eid, world.board).write_text(json.dumps({**record, "execution_id": eid}))
    task_bot_runtime.list_executions(world.board, refresh=True)
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.05)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}

    async def scenario() -> list[float]:
        ticks: list[float] = []

        async def ticker() -> None:
            while True:
                ticks.append(time.perf_counter())
                await asyncio.sleep(0.02)

        beat = asyncio.ensure_future(ticker())
        try:
            await asyncio.sleep(0.05)
            await _chat_send(app, "chat-big", ASK, [], level=5)
            root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
            await asyncio.to_thread(
                forge_code_projects.update_conversation_settings,
                world.catalog,
                cid,
                {"requested": {"autonomy_level": 5}},
            )
            await asyncio.to_thread(_run_turn, root, cid, ok=False, files=[])
            await asyncio.sleep(1.0)
        finally:
            beat.cancel()
        return ticks

    ticks = asyncio.run(scenario())

    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.2, "the card's writes held the event loop"


def test_m5_stop_between_autopilot_rounds_stops_autopilot(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: {}}

    async def scenario() -> dict[str, Any]:
        card = await _chat_send(app, "chat-x", ASK, [], level=5)
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        forge_code_projects.update_conversation_settings(world.catalog, cid, {"requested": {"autonomy_level": 5}})
        _run_turn(root, cid, ok=False, files=[])  # between rounds: Autopilot's next one is due
        assert chat_delegation.apply_task_update("chat-x", card["execution_id"], cancel=True)["ok"]
        stopped = await _card_state(card["execution_id"], world.board, "cancelled")
        await ap.after_run(app, root, world.catalog, cid)
        return stopped

    stopped = asyncio.run(scenario())

    assert len(world.starts) == 1, "no next Autopilot round after Stop"
    assert "you stopped it" in stopped["progress_summary"]


def test_m6_a_conversation_is_written_whole_and_a_half_written_one_is_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, catalog = tmp_path / "green", tmp_path / "catalog"
    cid = forge_code_store.new_conversation(root, title="t", thomas_project={"execution_id": "thomas-m6"})["id"]
    path = root / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"
    seen: list[str] = []
    real_replace = os.replace

    def replace(src: Any, dst: Any) -> None:  # at the swap, the file is still the whole previous version
        seen.append(json.loads(Path(dst).read_text(encoding="utf-8"))["title"])
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    forge_code_store.rename_conversation(root, cid, "renamed")
    assert seen == ["t"] and forge_code_store.load_conversation(root, cid)["title"] == "renamed"
    path.write_text('{"id": "' + cid + '", "turns": [', encoding="utf-8")  # caught mid-write
    assert thomas_project.project_phase(root, catalog, cid)[0] == "waiting", "read again next check, never the end"


def test_a_settled_record_never_says_settled_before_it_says_what_went_out(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found under load in fix round 1: the stamp was written first, so a card that checked between the two writes
    read "settled, nothing submitted" and told you no file had changed."""
    green = green_checkout.create_green(blue=world.blue, execution_id="thomas-race1")
    cid = forge_code_store.new_conversation(green.work, title="t", thomas_project={"execution_id": green.execution_id})[
        "id"
    ]
    _run_turn(green.work, cid, ok=True, files=["README.md"])
    seen: list[tuple[bool, bool]] = []
    real_write = forge_code_store._write_conversation

    def watched(root: Any, conversation: dict[str, Any]) -> dict[str, Any]:
        if Path(root) == world.catalog:  # every state of the record a card could read
            record = conversation.get("thomas_project") or {}
            seen.append((bool(record.get("settled_at")), bool(record.get("submission"))))
        return real_write(root, conversation)

    monkeypatch.setattr(forge_code_store, "_write_conversation", watched)

    assert thomas_project.settle_if_finished(green.work, world.catalog, cid) is not None
    assert (True, False) not in seen and seen[-1] == (True, True), seen


# ── Task 4 round 2 (parked items) ──


def _l5(world: SimpleNamespace, cid: str) -> None:
    forge_code_projects.update_conversation_settings(world.catalog, cid, {"requested": {"autonomy_level": 5}})


def test_n1_a_steer_that_lands_while_the_next_start_is_in_flight_rides_that_run(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1: the start's message was built before your steer, so it arrived one whole run late."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)
    runs: dict[str, Any] = {}
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # the run that is starting
    seen: dict[str, Any] = {}
    base = _hook(world)

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        answer = await base(body, port=port)
        if len(world.starts) == 2:  # Autopilot's next start is in flight: you steer, then Build registers the run
            seen["reply"] = chat_delegation.apply_task_update("chat-n1", seen["eid"], "use green, not blue")
            runs[body["conversation_id"]] = {"session": {"proc": live, "run_id": "run-2"}, "drain": None}
        return answer

    app = {APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: runs}

    async def scenario() -> None:
        seen["eid"] = (await _chat_send(app, "chat-n1", ASK, [], level=5))["execution_id"]
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        _l5(world, cid)
        _run_turn(root, cid, ok=False, files=[])  # Autopilot's next round is due
        await ap.after_run(app, root, world.catalog, cid)
        for _ in range(100):
            if live.poll() is not None:
                break
            await asyncio.sleep(0.05)
        runs.pop(cid)
        _stopped_for_steering(root, cid)
        await ap.after_run(app, root, world.catalog, cid)

    try:
        asyncio.run(scenario())
    finally:
        live.kill()

    assert seen["reply"]["ok"] is True and "use green" not in world.starts[1]["message"]
    assert getattr(live, "thomas_stop_requested", "") == "steer", "the run that just started was stopped for it"
    assert len(world.starts) == 3 and "\n\nSteering update: use green, not blue\n\n" in world.starts[2]["message"]


def test_n1_a_steer_held_for_a_continuation_that_is_refused_still_starts_a_run(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N1: the continuation carrying your steer was refused, and the steer was lost with it."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 3600.0)
    base = _hook(world)

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        answer = await base(body, port=port)
        return (500, {"ok": False, "error": "the engine did not start"}) if len(world.starts) == 2 else answer

    app = {APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: {}}

    async def scenario() -> dict[str, Any]:
        card = await _chat_send(app, "chat-n1b", ASK, [], level=5)
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        _l5(world, cid)
        _run_turn(root, cid, ok=False, files=[])
        reply = chat_delegation.apply_task_update("chat-n1b", card["execution_id"], "keep the old colour")
        await ap.after_run(app, root, world.catalog, cid)
        return reply

    reply = asyncio.run(scenario())

    assert reply["ok"] is True and "keep the old colour" in world.starts[1]["message"], "the refused start"
    assert len(world.starts) == 3 and "Steering update: keep the old colour" in world.starts[2]["message"]
    assert thomas_project.held_steers(world.starts[0]["conversation_id"]) == []


def test_n3_after_stop_a_run_you_start_yourself_can_still_settle(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3: the stop mark was permanent, so a run you started by hand in Build never reached your approval card."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: {}}

    async def scenario() -> None:
        card = await _chat_send(app, "chat-n3", ASK, [])
        root, cid = Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"]
        assert chat_delegation.apply_task_update("chat-n3", card["execution_id"], cancel=True)["ok"]
        await _card_state(card["execution_id"], world.board, "cancelled")
        _run_turn(root, cid, ok=True, files=["README.md"])  # your own message in Build, then its finished run
        await ap.after_run(app, root, world.catalog, cid)

    asyncio.run(scenario())

    assert (world.inbox / f"self-{Path(world.starts[0]['project_root']).name}").is_dir(), "it reached your card"


def test_a_card_leaves_the_followed_set_before_it_says_its_project_ended(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flaky kept-green test: the card left `_FOLLOWED` only after its last update, so a request sent the
    moment it said "failed" saw its green as in use and started a new one instead of resuming it."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    followed_at_failure: list[bool] = []
    real_fail = task_bot_runtime.fail_execution

    def watched(eid: str, **kwargs: Any) -> dict[str, Any]:
        followed_at_failure.append(eid in chat_self_project._FOLLOWED)
        return real_fail(eid, **kwargs)

    monkeypatch.setattr(task_bot_runtime, "fail_execution", watched)
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898}

    async def scenario() -> None:
        card = await _chat_send(app, "chat-race", ASK, [])
        _run_turn(Path(world.starts[0]["project_root"]), world.starts[0]["conversation_id"], ok=False, files=["a.md"])
        await _card_state(card["execution_id"], world.board, "failed")

    asyncio.run(scenario())

    assert followed_at_failure == [False]


def test_a_green_a_build_run_is_using_is_never_resumed_or_swept(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run you start on a kept green straight through Build's send route has no chat card; it still counts."""
    monkeypatch.setattr(chat_self_project, "_POLL_S", 0.01)
    runs: dict[str, Any] = {}
    app = {APP_PRAXIS_START_CODE_RUN: _hook(world), APP_LOCAL_PORT: 8898, APP_EVOLVE_AGENT_RUNS: runs}

    async def scenario() -> None:
        card = await _chat_send(app, "chat-busy", ASK, [])
        kept = Path(world.starts[0]["project_root"])
        _run_turn(kept, world.starts[0]["conversation_id"], ok=False, files=["README.md"])
        await _card_state(card["execution_id"], world.board, "failed")  # its green is kept
        runs["fc_yours"] = {"session": {"proc": SimpleNamespace(returncode=None), "project_root": str(kept)}}
        meta_file = world.greens / "git" / kept.name / green_checkout.METADATA_NAME
        meta = json.loads(meta_file.read_text(encoding="utf-8"))  # and past the 7 days a kept green is spared
        meta_file.write_text(json.dumps({**meta, "created_at": meta["created_at"] - 8 * 86400}), encoding="utf-8")
        monkeypatch.setattr(chat_self_project, "_last_sweep", None, raising=False)
        await _chat_send(app, "chat-busy", "Carry on", [])

    asyncio.run(scenario())

    kept = Path(world.starts[0]["project_root"])
    assert kept.is_dir(), "the hourly sweep spared the green a live run is using"
    assert world.starts[1]["project_root"] != str(kept), "the follow-up did not start a second project in it"
