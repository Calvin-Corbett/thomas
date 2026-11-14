"""A Code-page steer survives the stopped run even when the page goes away."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from tests.evolve_agent_route_support import _drive, _new_repo
from thomas.forge.anvil import forge_code_conversations, forge_code_store
from thomas.server import thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot, evolve_agent_page_steer
from thomas.server.routes.evolve_agent_run_state import (
    APP_EVOLVE_AGENT_CONVO,
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_RUNS,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
)

STEER = "Please keep this entire steering instruction, including the last word: violet"


@pytest.mark.parametrize(
    "case",
    [
        "starts",
        "slow_read",
        "carried",
        "early_carried",
        "not_autopilot",
        "other_run",
        "finished_other_run",
        "timeout",
        "grace_crosses_deadline",
    ],
)
def test_code_page_steer_after_recording(tmp_path, monkeypatch, case):
    monkeypatch.setattr(evolve_agent_page_steer, "STEER_GRACE_S", 0)
    if case == "timeout":
        monkeypatch.setattr(evolve_agent_page_steer, "STEER_WAIT_S", 0.1)
    elif case == "grace_crosses_deadline":
        monkeypatch.setattr(evolve_agent_page_steer, "STEER_WAIT_S", 8)
        monkeypatch.setattr(evolve_agent_page_steer, "STEER_GRACE_S", 9)
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    cid = conversation["id"]
    forge_code_store.append_user_turn(repo, cid, "Build a useful thing")
    forge_code_conversations.bind_conversation(
        repo,
        cid,
        repo,
        settings={"requested": {"autonomy_level": 5 if case != "not_autopilot" else 2}},
    )
    thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))
    proc = SimpleNamespace(returncode=None)
    run_id = "run-being-stopped"
    newer_message = f"Follow up: {STEER}" if case in ("carried", "early_carried") else "A new run without the steer"
    starts = []
    started = asyncio.Event()
    response = {}
    release_read = threading.Event()
    original_read = evolve_agent_page_steer._read_conversation
    if case == "slow_read":

        def delayed_read(*args):
            # A delayed off-thread read must not make the restart assertion race.
            import time

            time.sleep(0.5)
            return original_read(*args)

        monkeypatch.setattr(evolve_agent_page_steer, "_read_conversation", delayed_read)
    if case == "early_carried":

        def delayed_read(*args):
            if not release_read.wait(timeout=5):
                raise AssertionError("watcher did not reach its first conversation read")
            return original_read(*args)

        monkeypatch.setattr(evolve_agent_page_steer, "_read_conversation", delayed_read)

    async def body(client):
        result = await client.post("/api/evolve/agent/steer", json={"run_id": run_id, "message": STEER})
        response.update(await result.json())
        assert result.status == 202
        assert response == {
            "ok": True,
            "stop_requested": True,
            "restart_required": True,
            "message": STEER,
        }
        # The handler must not start until the recorder has finished the stopped turn.
        assert starts == []
        proc.returncode = -15
        if case in ("carried", "other_run", "finished_other_run", "early_carried"):
            # Replace the stopped slot with a new Code-page follow-up before recording finishes.
            client.server.app[APP_EVOLVE_AGENT_RUNS][cid] = {
                "session": {
                    "run_id": "new-run",
                    "conversation_id": cid,
                    "message": newer_message,
                    "proc": SimpleNamespace(returncode=0 if case == "finished_other_run" else None),
                },
                "drain": None,
            }
        if case == "timeout":
            await asyncio.sleep(0.35)
            assert starts == []
            assert thomas_project.held_steers(cid) == [STEER]
            return
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=[],
            returncode=-15,
            ok=False,
            noop=False,
            reason="steering",
            outcome="stopped",
        )
        client.server.app[APP_EVOLVE_AGENT_DRAIN].set_result({"persistence_confirmed": True})
        if case == "early_carried":
            forge_code_store.append_user_turn(repo, cid, newer_message)
            # The page-started run already finished and vacated its registry slot.
            client.server.app[APP_EVOLVE_AGENT_RUNS].pop(cid)
            client.server.app[APP_EVOLVE_AGENT_SESSION]["message"] = ""
            # Let the watcher take its first read only after both turns are saved.
            monkeypatch.setattr(evolve_agent_page_steer, "_read_conversation", original_read)
            release_read.set()
        # The watcher has its own recording deadline; wait for its handoff rather
        # than timing out before a busy worker can start and consume the steer.
        watchers = tuple(evolve_agent_page_steer._watchers)
        assert watchers
        await asyncio.gather(*watchers)
        if case in ("starts", "slow_read", "finished_other_run", "grace_crosses_deadline"):
            assert started.is_set()
            assert len(starts) == 1
            assert starts[0]["message"].startswith(evolve_agent_autopilot.STEER_PREFIX)
            assert STEER in starts[0]["message"]
            assert thomas_project.held_steers(cid) == []
        elif case == "other_run":
            assert starts == []
            assert thomas_project.held_steers(cid) == [STEER]
        else:
            assert starts == []
            assert thomas_project.held_steers(cid) == []

    def configure(app):
        drain = asyncio.get_running_loop().create_future()
        slot = {
            "session": {
                "run_id": run_id,
                "conversation_id": cid,
                "project_root": str(repo),
                "proc": proc,
                "message": "Build a useful thing",
            },
            "drain": drain,
        }
        app[APP_EVOLVE_AGENT_RUNS] = {cid: slot}
        app[APP_EVOLVE_AGENT_SESSION] = slot["session"]
        app[APP_EVOLVE_AGENT_DRAIN] = drain
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_CONVO] = cid
        app[APP_LOCAL_PORT] = 12345

        async def start(payload, *, port):
            starts.append(payload)
            started.set()
            return 202, {"ok": True}

        app[APP_PRAXIS_START_CODE_RUN] = start
        # Stand-in termination: recorder remains unfinished until body() records the turn.
        monkeypatch.setattr("thomas.server.routes.evolve_agent_control_routes._mark_steer_requested", lambda *_: None)

    monkeypatch.setattr("thomas.server.routes.evolve_agent_routes._kill_tree", lambda *_: None)
    try:
        _drive(repo, body, configure=configure)
    finally:
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))


def test_waiting_for_recorder_reads_conversation_at_most_once_a_second(tmp_path, monkeypatch):
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    cid = conversation["id"]
    forge_code_conversations.bind_conversation(repo, cid, repo, settings={"requested": {"autonomy_level": 5}})
    reads = []
    load = evolve_agent_autopilot._load_joined_conversation
    event_loop_thread = threading.get_ident()

    def counted_load(*args):
        assert threading.get_ident() != event_loop_thread
        reads.append(1)
        return load(*args)

    monkeypatch.setattr(evolve_agent_autopilot, "_load_joined_conversation", counted_load)
    monkeypatch.setattr(evolve_agent_page_steer, "STEER_WAIT_S", 10)
    monkeypatch.setattr(evolve_agent_page_steer, "STEER_GRACE_S", 0)
    proc = SimpleNamespace(returncode=None)

    async def body(client):
        result = await client.post("/api/evolve/agent/steer", json={"run_id": "stopped", "message": STEER})
        assert result.status == 202
        await asyncio.sleep(10.3)
        assert 1 <= len(reads) <= 11

    def configure(app):
        drain = asyncio.get_running_loop().create_future()
        slot = {
            "session": {"run_id": "stopped", "conversation_id": cid, "project_root": str(repo), "proc": proc},
            "drain": drain,
        }
        app[APP_EVOLVE_AGENT_RUNS] = {cid: slot}
        app[APP_EVOLVE_AGENT_SESSION] = slot["session"]
        app[APP_EVOLVE_AGENT_DRAIN] = drain
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_CONVO] = cid
        monkeypatch.setattr("thomas.server.routes.evolve_agent_control_routes._mark_steer_requested", lambda *_: None)

    monkeypatch.setattr("thomas.server.routes.evolve_agent_routes._kill_tree", lambda *_: None)
    try:
        _drive(repo, body, configure=configure)
    finally:
        thomas_project.drop_steers(cid, len(thomas_project.held_steers(cid)))


def test_route_still_answers_when_conversation_cannot_be_read(tmp_path, monkeypatch):
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    cid = conversation["id"]
    proc = SimpleNamespace(returncode=None)

    def unreadable(*args):
        raise OSError("conversation unavailable")

    monkeypatch.setattr(evolve_agent_autopilot, "_load_joined_conversation", unreadable)

    async def body(client):
        result = await client.post("/api/evolve/agent/steer", json={"run_id": "stopped", "message": STEER})
        assert result.status == 202
        assert await result.json() == {
            "ok": True,
            "stop_requested": True,
            "restart_required": True,
            "message": STEER,
        }
        await asyncio.sleep(0.05)

    def configure(app):
        slot = {
            "session": {"run_id": "stopped", "conversation_id": cid, "project_root": str(repo), "proc": proc},
            "drain": asyncio.get_running_loop().create_future(),
        }
        app[APP_EVOLVE_AGENT_RUNS] = {cid: slot}
        app[APP_EVOLVE_AGENT_SESSION] = slot["session"]
        app[APP_EVOLVE_AGENT_DRAIN] = slot["drain"]
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_CONVO] = cid
        monkeypatch.setattr("thomas.server.routes.evolve_agent_control_routes._mark_steer_requested", lambda *_: None)

    monkeypatch.setattr("thomas.server.routes.evolve_agent_routes._kill_tree", lambda *_: None)
    _drive(repo, body, configure=configure)
