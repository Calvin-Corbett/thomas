"""Recover endings saved just before the server lost their pending handoff."""

from __future__ import annotations

import asyncio

import pytest

from tests.restart_test_isolation import (  # noqa: F401
    immediate_restart_retries,
    isolated_restart_runners,
    tmp_path_factory,
)
from tests.test_a_restart_does_not_stop_a_thomas_project import _app, _restart, _stopped_run
from thomas.forge.anvil import forge_code_store
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_continuation_history import continuation_history
from thomas.server.routes.evolve_agent_receipts import _action_receipt, _delete_action_receipt, _save_action_receipt


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("state", ["running", "completed"])
async def test_restart_recovers_completed_turn_before_pending_receipt(tmp_path, monkeypatch, state):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    p = _stopped_run(tmp_path, kind="repair", state=state)
    user = forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]
    forge_code_store.append_agent_turn(
        p.root,
        p.cid,
        model="test",
        transcript='{"fc":"tool","name":"check.run","input":{}}\n',
        changed_files=[],
        returncode=1,
        ok=False,
        noop=True,
        outcome="failed",
        reason="tool check failed before shutdown",
        run_id="run-before",
    )
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = user["ts"]
    forge_code_store.write_conversation(p.root, conversation)
    restart = _restart()
    found = restart.survey(p.catalog, p.booted)
    assert len(found) == 1
    assert found[0].after_run_pending
    expected = ap.decide(ap._load_joined_conversation(p.root, p.catalog, p.cid))
    app = _app(p.catalog, starts := [])
    await restart._attempt(app, p.catalog, found, {})
    assert len(starts) == 1
    assert starts[0]["message"] == expected.message
    assert not starts[0]["message"].startswith(ap.RESTART_PREFIX)
    assert _action_receipt(p.catalog, "run", user["request_id"])["state"] == "finished"
    history = continuation_history(forge_code_store.load_conversation(p.root, p.cid))
    assert history["count"] == 1
    assert history["runs"][0]["reason"] == "tool check failed before shutdown"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("with_receipt", [False, True])
async def test_second_restart_recovers_interrupted_ending_before_pending_receipt(tmp_path, monkeypatch, with_receipt):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    p = _stopped_run(tmp_path, kind="repair")
    restart = _restart()
    found = restart.survey(p.catalog, p.booted)
    if not with_receipt:
        _delete_action_receipt(p.catalog, "run", found[0].turn["request_id"])
    original = forge_code_store.append_agent_turn

    def save_then_power_cut(*args, **kwargs):
        original(*args, **kwargs)
        raise asyncio.CancelledError

    app = _app(p.catalog, starts := [])
    with monkeypatch.context() as patch:
        patch.setattr(forge_code_store, "append_agent_turn", save_then_power_cut)
        with pytest.raises(asyncio.CancelledError):
            await restart._carry_on(app, p.catalog, found[0])
    assert starts == []
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    conversation["turns"][-1]["ts"] = found[0].turn["ts"]
    forge_code_store.write_conversation(p.root, conversation)
    recovered = restart.survey(p.catalog, p.booted)
    assert len(recovered) == 1
    await restart._attempt(app, p.catalog, recovered, {})
    assert len(starts) == 1
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    assert len([turn for turn in conversation["turns"] if turn.get("outcome") == "interrupted"]) == 1
    assert continuation_history(conversation)["count"] == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_live_retry_recovers_interrupted_ending_before_pending_receipt(tmp_path, monkeypatch):
    from thomas.server.routes import evolve_agent_receipts

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    p = _stopped_run(tmp_path, kind="repair")
    restart = _restart()
    found = restart.survey(p.catalog, p.booted)
    app = _app(p.catalog, starts := [])
    attempts = {}
    failed = False

    def fail_pending_once(catalog, action, request_id, receipt):
        nonlocal failed
        if receipt.get("state") == "after_run_pending" and not failed:
            failed = True
            raise OSError("temporary receipt write failure")
        return _save_action_receipt(catalog, action, request_id, receipt)

    monkeypatch.setattr(evolve_agent_receipts, "_save_action_receipt", fail_pending_once)
    await restart._attempt(app, p.catalog, found, attempts)
    assert failed and not starts and len(found) == 1
    await restart._attempt(app, p.catalog, found, attempts)
    assert len(starts) == 1
    assert not found
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    assert len([turn for turn in conversation["turns"] if turn.get("outcome") == "interrupted"]) == 1
    assert continuation_history(conversation)["count"] == 0


@pytest.mark.asyncio(loop_scope="module")
async def test_restart_recovers_when_interrupted_turn_write_is_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    p = _stopped_run(tmp_path, kind="repair", thomas=False)
    restart = _restart()
    found = restart.survey(p.catalog, p.booted)
    app = _app(p.catalog, starts := [])

    def power_cut(*args, **kwargs):
        raise asyncio.CancelledError

    with monkeypatch.context() as patch:
        patch.setattr(forge_code_store, "append_agent_turn", power_cut)
        with pytest.raises(asyncio.CancelledError):
            await restart._carry_on(app, p.catalog, found[0])
    assert starts == []
    assert forge_code_store.load_conversation(p.root, p.cid)["turns"][-1]["role"] == "user"
    receipt = _action_receipt(p.catalog, "run", found[0].turn["request_id"])
    assert receipt["state"] == "running"
    recovered = restart.survey(p.catalog, p.booted)
    assert len(recovered) == 1
    await restart._attempt(app, p.catalog, recovered, {})
    assert len(starts) == 1
    conversation = forge_code_store.load_conversation(p.root, p.cid)
    assert len([turn for turn in conversation["turns"] if turn.get("outcome") == "interrupted"]) == 1


@pytest.mark.asyncio
async def test_recovery_keeps_retrying_unstarted_read_failures(tmp_path, monkeypatch):
    p = _stopped_run(tmp_path, kind="repair", thomas=False)
    restart = _restart()
    starts = []
    app = _app(p.catalog, starts)
    found = restart.survey(p.catalog, p.booted)
    original = restart._carry_on
    failures = 4
    attempts = 0

    async def unavailable(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts <= failures:
            raise OSError("storage temporarily unavailable")
        return await original(*args, **kwargs)

    monkeypatch.setattr(restart, "_carry_on", unavailable)
    tries = {}
    pre_start_failures = {}
    for _ in range(failures):
        await restart._attempt(app, p.catalog, found, tries, pre_start_failures)
        assert found and not starts
    await restart._attempt(app, p.catalog, found, tries, pre_start_failures)
    assert not found and len(starts) == 1
    assert continuation_history(forge_code_store.load_conversation(p.root, p.cid))["count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("reader", ["registry", "registry_read", "receipt", "conversation", "missing_read", "classify"])
async def test_startup_discovery_retries_a_transient_read_failure(tmp_path, monkeypatch, reader):
    p = _stopped_run(tmp_path, kind="repair", thomas=False)
    restart = _restart()
    starts = []
    app = _app(p.catalog, starts)
    from thomas.server.routes import evolve_agent_receipts

    target, name = {
        "registry": (restart.forge_code_conversations, "_load_registry"),
        "registry_read": (type(p.root), "read_text"),
        "receipt": (evolve_agent_receipts, "_read_receipts"),
        "conversation": (restart, "_unfinished"),
        "missing_read": (type(p.root), "read_text"),
        "classify": (restart, "_classify"),
    }[reader]
    original = getattr(target, name)
    reads = 0

    def fail_once(*args, **kwargs):
        nonlocal reads
        if reader == "missing_read" and args[0] != restart.thomas_project._live_file(p.root, p.cid):
            return original(*args, **kwargs)
        if reader == "registry_read" and args[0] != restart.forge_code_conversations._registry_path(p.catalog):
            return original(*args, **kwargs)
        reads += 1
        if reads == 1:
            error = FileNotFoundError if reader == "missing_read" else OSError
            raise error("temporarily unavailable")
        return original(*args, **kwargs)

    before = forge_code_store.load_conversation(p.root, p.cid)["turns"]
    monkeypatch.setattr(target, name, fail_once)
    monkeypatch.setattr(restart, "_cage_down", lambda: False)

    async def retry_now(_seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(restart, "_sleep", retry_now)
    task = asyncio.create_task(restart.restart_pass(app, catalog_root=p.catalog))
    try:
        for _ in range(500):
            if starts:
                break
            await asyncio.sleep(0.01)
        assert reads >= 2
        assert len(starts) == 1
        turns = forge_code_store.load_conversation(p.root, p.cid)["turns"]
        assert turns[: len(before)] == before
        assert len([turn for turn in turns if turn.get("outcome") == "interrupted"]) == 1
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
