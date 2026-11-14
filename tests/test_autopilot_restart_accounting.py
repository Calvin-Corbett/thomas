"""Restart accounting keeps executed work, but not refused starts, in the fuse."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.restart_test_isolation import (  # noqa: F401
    immediate_restart_retries,
    isolated_restart_runners,
    tmp_path_factory,
)
from tests.test_a_restart_does_not_stop_a_thomas_project import (  # noqa: F401
    FAILED,
    _app,
    _iso,
    _restart,
    _stopped_run,
    isolated,
)
from thomas.forge.anvil import forge_code_store
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_continuation_history import continuation_history
from thomas.server.routes.evolve_agent_runtime import _transcript_path


@pytest.mark.asyncio(loop_scope="module")
async def test_restart_keeps_a_spent_repair_budget(tmp_path: Path) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["thomas_project"]["repairs_spent"] = {"turns": len(conversation["turns"]), "why": "repairs exhausted"}
    forge_code_store.write_conversation(p.root, conversation)
    app = _app(p.catalog, starts := [])
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert starts == []
    assert report["not_resumed"][p.cid] == "repairs exhausted"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("executed", [False, True])
async def test_restart_preserves_execution_and_ending(tmp_path: Path, executed: bool) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    transcript = _transcript_path(p.catalog, "run-before")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(
        '{"fc":"tool","name":"check.run","input":{}}\n' if executed else "startup failed\n",
        encoding="utf-8",
    )
    os.utime(transcript, (p.booted - 20, p.booted - 20))
    app = _app(p.catalog, starts := [])
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert starts, report
    saved = forge_code_store.load_conversation(p.root, p.cid)
    history = continuation_history(saved)
    assert history["count"] == int(executed), saved["turns"]
    if executed:
        assert history["runs"][0]["run_id"] == "run-before"
        assert history["runs"][0]["outcome"] == "interrupted"
        assert "server stopped" in history["runs"][0]["reason"]
    forge_code_store.append_agent_turn(
        p.root,
        p.cid,
        model="test",
        transcript='{"fc":"say","source":"model","text":"Resumed work"}\n',
        changed_files=[],
        returncode=0,
        ok=True,
        noop=True,
        outcome="conversation",
        reason="resumed work finished",
        run_id="run-after",
    )
    history = continuation_history(forge_code_store.load_conversation(p.root, p.cid))
    assert history["count"] == 1 + int(executed)
    assert history["runs"][-1]["reason"] == "resumed work finished"
    assert len(starts) == 1


@pytest.mark.asyncio(loop_scope="module")
async def test_restart_retries_busy_start_without_spending_a_run(tmp_path: Path, monkeypatch) -> None:
    p = _stopped_run(tmp_path, kind="repair")
    app = _app(p.catalog, starts := [])
    real_start = app[APP_PRAXIS_START_CODE_RUN]
    attempts = []

    async def start(payload, *, port):
        attempts.append(payload)
        if len(attempts) == 1:
            return 409, {"ok": False, "code": "agent_already_running"}
        return await real_start(payload, port=port)

    async def sleep(_seconds):
        pass

    app[APP_PRAXIS_START_CODE_RUN] = start
    monkeypatch.setattr(ap, "_sleep", sleep)
    report = await _restart().resume_interrupted(app, p.catalog, booted=p.booted)
    assert report["resumed"] == [p.cid], report
    assert len(attempts) == 2 and len(starts) == 1
    assert continuation_history(forge_code_store.load_conversation(p.root, p.cid))["count"] == 0


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("executed", [False, True])
@pytest.mark.parametrize("with_receipt", [False, True])
async def test_interrupted_run_retries_after_an_entire_busy_batch(
    tmp_path: Path, monkeypatch, executed: bool, with_receipt: bool
) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    restart = _restart()
    monkeypatch.setattr(restart, "_pass", restart._Pass())
    monkeypatch.setattr(restart, "_runners_of", lambda _cid: ([], []))
    p = _stopped_run(tmp_path, kind="repair")
    transcript = _transcript_path(p.catalog, "run-before")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text('{"fc":"tool","name":"check.run","input":{}}\n' if executed else "startup failed\n")
    os.utime(transcript, (p.booted - 20, p.booted - 20))
    app = _app(p.catalog, starts := [])
    start = app[APP_PRAXIS_START_CODE_RUN]
    attempts = 0
    refused_batches = 4

    async def busy_then_accept(body, *, port):
        nonlocal attempts
        attempts += 1
        if attempts <= ap._START_RETRY_LIMIT * refused_batches:
            return 409, {"ok": False, "code": "agent_already_running"}
        return await start(body, port=port)

    async def no_delay(_seconds):
        pass

    monkeypatch.setattr(ap, "_sleep", no_delay)
    app[APP_PRAXIS_START_CODE_RUN] = busy_then_accept
    found = restart.survey(p.catalog, p.booted)
    if not with_receipt:
        from thomas.server.routes.evolve_agent_receipts import _delete_action_receipt

        _delete_action_receipt(p.catalog, "run", found[0].turn["request_id"])
    tries = {}
    for _ in range(refused_batches):
        await restart._attempt(app, p.catalog, found, tries)
        assert restart.report()["pending"] == [p.cid], restart.report()
    await restart._attempt(app, p.catalog, found, tries)
    assert restart.report()["resumed"] == [p.cid], restart.report()
    assert attempts == ap._START_RETRY_LIMIT * refused_batches + 1 and len(starts) == 1
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    assert len([t for t in conversation["turns"] if t.get("run_id") == "run-before"]) == 1
    assert continuation_history(conversation)["count"] == int(executed)


@pytest.mark.asyncio(loop_scope="module")
async def test_pending_handoff_waits_out_busy_starts_without_spending_a_run(tmp_path: Path, monkeypatch) -> None:
    from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(_restart(), "_pass", _restart()._Pass())
    p = _stopped_run(tmp_path, kind="repair", state="completed")
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(p.root, p.cid, **FAILED)
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = _iso(p.booted - 10)
    forge_code_store.write_conversation(p.root, conversation)
    receipt = _action_receipt(p.catalog, "run", user["request_id"])
    _save_action_receipt(p.catalog, "run", user["request_id"], {**receipt, "state": "after_run_pending"})
    app = _app(p.catalog, starts := [])
    start = app[APP_PRAXIS_START_CODE_RUN]
    attempts = 0

    async def busy_until_next_attempt(body, *, port):
        nonlocal attempts
        attempts += 1
        if attempts <= ap._START_RETRY_LIMIT:
            assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
            return 409, {"ok": False, "error": "busy", "code": "agent_already_running"}
        assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
        return await start(body, port=port)

    async def no_delay(*args):
        pass

    monkeypatch.setattr(ap, "_sleep", no_delay)
    monkeypatch.setattr(_restart(), "_runners_of", lambda _cid: ([], []))
    app[APP_PRAXIS_START_CODE_RUN] = busy_until_next_attempt
    restart = _restart()
    found = restart.survey(p.catalog, p.booted)
    tries = {}
    refused_batches = 4
    for _ in range(refused_batches):
        attempts = 0
        await restart._attempt(app, p.catalog, found, tries)
        assert restart.report()["pending"] == [p.cid]
        assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "after_run_pending"
    assert tries[p.cid] == refused_batches
    await restart._attempt(app, p.catalog, found, tries)
    assert restart.report()["resumed"] == [p.cid]
    assert attempts == ap._START_RETRY_LIMIT + 1 and len(starts) == 1
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"
    history = continuation_history(forge_code_store.load_conversation(p.root, p.cid))
    assert history["count"] == 1
    assert history["runs"][0]["reason"] == FAILED["reason"]
