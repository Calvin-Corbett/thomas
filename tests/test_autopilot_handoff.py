"""A post-run handoff retries refused launches without charging execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.test_autopilot_keeps_going import _bind_real_conversation, _finished_task, _partial_turn
from thomas.forge.anvil import forge_code_store
from thomas.server.routes import autopilot_handoff as handoff
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.autopilot_continuation_history import continuation_history
from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["busy", "exception"])
async def test_attached_handoff_retries_a_whole_refused_batch(tmp_path: Path, monkeypatch, failure: str) -> None:
    catalog, root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    conversation = forge_code_store.load_conversation(root, cid)
    request_id = "finished-run"
    conversation["turns"][0]["request_id"] = request_id
    forge_code_store.write_conversation(root, conversation)
    _save_action_receipt(catalog, "run", request_id, {"state": "completed"})
    accepted = asyncio.Event()
    completed = asyncio.Event()
    finish_handoff = handoff.finish_handoff

    async def finish(*args) -> None:
        await finish_handoff(*args)
        completed.set()

    monkeypatch.setattr(handoff, "finish_handoff", finish)
    calls = 0
    waits = 0

    async def no_delay(_seconds: float) -> None:
        await asyncio.sleep(0)

    async def between_batches(_seconds: float) -> None:
        nonlocal waits
        waits += 1
        assert _action_receipt(catalog, "run", request_id)["state"] == "after_run_pending"
        assert continuation_history(forge_code_store.load_conversation(root, cid))["count"] == 0
        await asyncio.sleep(0)

    async def start(body: dict, *, port: int) -> tuple[int, dict]:
        nonlocal calls
        calls += 1
        if failure == "exception" and calls == 1:
            raise OSError("launch plumbing not ready")
        if failure == "busy" and calls <= ap._START_RETRY_LIMIT:
            return 409, {"code": ap._BUSY_CODE}
        accepted.set()
        return 200, {"ok": True}

    monkeypatch.setattr(ap, "_sleep", no_delay)
    monkeypatch.setattr(handoff, "_sleep", between_batches)
    app = {ap.APP_PRAXIS_START_CODE_RUN: start, ap.APP_LOCAL_PORT: 8898}
    task = await _finished_task()
    ap.attach_after_run(app, task, root, catalog, cid)
    await asyncio.wait_for(accepted.wait(), timeout=10)
    await asyncio.wait_for(completed.wait(), timeout=10)
    assert calls == (ap._START_RETRY_LIMIT + 1 if failure == "busy" else 2)
    assert waits == 1
    assert _action_receipt(catalog, "run", request_id)["state"] == "finished"
    assert continuation_history(forge_code_store.load_conversation(root, cid))["count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["read", "decision"])
async def test_handoff_retries_a_transient_storage_failure(tmp_path: Path, monkeypatch, failure: str) -> None:
    catalog, root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    conversation = forge_code_store.load_conversation(root, cid)
    request_id = "finished-run"
    conversation["turns"][0]["request_id"] = request_id
    forge_code_store.write_conversation(root, conversation)
    _save_action_receipt(catalog, "run", request_id, {"state": "completed"})
    real_load = ap._load_joined_conversation
    loads = 0

    def load(*args):
        nonlocal loads
        loads += 1
        if failure == "read" and loads == 1:
            raise OSError("temporary read failure")
        return real_load(*args)

    decisions = []

    async def after(*args):
        decisions.append(True)
        if failure == "decision" and len(decisions) == 1:
            return None
        return ap.Decision("done", "checked")

    waits = []

    async def no_delay(_seconds):
        waits.append(True)

    monkeypatch.setattr(ap, "_load_joined_conversation", load)
    monkeypatch.setattr(ap, "after_run", after)
    monkeypatch.setattr(handoff, "_sleep", no_delay)
    await handoff.finish_handoff({}, root, catalog, cid)
    assert len(waits) == 1
    assert len(decisions) == (2 if failure == "decision" else 1)
    assert _action_receipt(catalog, "run", request_id)["state"] == "finished"
    assert continuation_history(forge_code_store.load_conversation(root, cid))["count"] == 0


@pytest.mark.parametrize("state", ["after_run_pending", "finished"])
def test_finished_run_receipts_remain_replayable(state: str) -> None:
    from thomas.server.routes.evolve_agent_run_status import _run_replay_available

    assert _run_replay_available({"state": state, "response": {"run_id": "ran-once"}}, None, False, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["pending", "finished"])
async def test_handoff_retries_a_receipt_store_failure(tmp_path: Path, monkeypatch, stage: str) -> None:
    from thomas.server.routes import evolve_agent_receipts as receipts

    catalog, root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    conversation = forge_code_store.load_conversation(root, cid)
    conversation["turns"][0]["request_id"] = "receipt-failure"
    forge_code_store.write_conversation(root, conversation)
    _save_action_receipt(catalog, "run", "receipt-failure", {"state": "completed"})
    real_save = receipts._save_action_receipt
    failed = False
    waits = []

    def save(root, kind, request_id, receipt):
        nonlocal failed
        target = "after_run_pending" if stage == "pending" else "finished"
        if receipt["state"] == target and not failed:
            failed = True
            raise RuntimeError("Code action receipts are temporarily unreadable")
        return real_save(root, kind, request_id, receipt)

    async def after(*args):
        return ap.Decision("done", "checked")

    async def no_delay(_seconds):
        waits.append(True)

    monkeypatch.setattr(receipts, "_save_action_receipt", save)
    monkeypatch.setattr(ap, "after_run", after)
    monkeypatch.setattr(handoff, "_sleep", no_delay)
    await handoff.finish_handoff({}, root, catalog, cid)
    assert failed and len(waits) == 1
    assert _action_receipt(catalog, "run", "receipt-failure")["state"] == "finished"


@pytest.mark.asyncio
async def test_refused_repair_keeps_a_live_handoff(tmp_path: Path, monkeypatch) -> None:
    catalog, root, cid = _bind_real_conversation(
        tmp_path,
        autonomy=ap.AUTOPILOT,
        agent_turn_kwargs_list=[_partial_turn()],
        thomas_project={"execution_id": "test-repair"},
    )
    monkeypatch.setattr(ap.thomas_project.green_handoff, "dev_tip", lambda _eid: "dev-tip")
    monkeypatch.setattr(ap.thomas_project.repair_ledger, "record", lambda *_args: None)
    calls = 0

    async def start(body: dict, *, port: int) -> tuple[int, dict]:
        nonlocal calls
        calls += 1
        return (503, {"error": "runner not ready"}) if calls == 1 else (202, {"run_id": "repair-started"})

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(handoff, "_sleep", no_wait)
    app = {ap.APP_PRAXIS_START_CODE_RUN: start, ap.APP_LOCAL_PORT: 8898}
    decision = await ap.start_repair(app, root, catalog, cid, why="check_failed", detail="Fix the failed test")
    assert decision is not None and decision.start_pending
    for _ in range(20):
        await asyncio.sleep(0)
        if calls == 2:
            break
    assert calls == 2
    assert continuation_history(forge_code_store.load_conversation(root, cid))["count"] == 0


@pytest.mark.asyncio
async def test_new_instruction_while_handoff_waits_prevents_stale_retry(tmp_path: Path, monkeypatch) -> None:
    catalog, root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    calls = 0

    async def start(body: dict, *, port: int) -> tuple[int, dict]:
        nonlocal calls
        calls += 1
        raise OSError("not ready")

    async def steer(_seconds: float) -> None:
        conversation = forge_code_store.load_conversation(root, cid)
        conversation["turns"].append({"role": "user", "text": "Stop and change the goal", "ts": "later"})
        forge_code_store.write_conversation(root, conversation)

    monkeypatch.setattr(handoff, "_sleep", steer)
    app = {ap.APP_PRAXIS_START_CODE_RUN: start, ap.APP_LOCAL_PORT: 8898}
    await handoff.finish_handoff(app, root, catalog, cid)
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelled_handoff_keeps_receipt_for_restart(tmp_path: Path, monkeypatch) -> None:
    catalog, root, cid = _bind_real_conversation(
        tmp_path, autonomy=ap.AUTOPILOT, agent_turn_kwargs_list=[_partial_turn()]
    )
    conversation = forge_code_store.load_conversation(root, cid)
    request_id = "finished-run"
    conversation["turns"][0]["request_id"] = request_id
    forge_code_store.write_conversation(root, conversation)
    _save_action_receipt(catalog, "run", request_id, {"state": "completed"})

    async def start(body: dict, *, port: int) -> tuple[int, dict]:
        raise OSError("not ready")

    async def cancelled(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(handoff, "_sleep", cancelled)
    app = {ap.APP_PRAXIS_START_CODE_RUN: start, ap.APP_LOCAL_PORT: 8898}
    with pytest.raises(asyncio.CancelledError):
        await handoff.finish_handoff(app, root, catalog, cid)
    assert _action_receipt(catalog, "run", request_id)["state"] == "after_run_pending"
    assert continuation_history(forge_code_store.load_conversation(root, cid))["count"] == 0


@pytest.mark.asyncio
async def test_handoff_rechecks_settings_changes_while_start_is_pending(tmp_path: Path, monkeypatch) -> None:
    conversation = {"turns": [{"role": "user", "text": "finish the game"}], "settings": {"autonomy": 5}}
    fresh = {**conversation, "settings": {"autonomy": 4}}
    snapshots = iter([conversation, fresh])
    monkeypatch.setattr(ap, "_load_joined_conversation", lambda *args: next(snapshots))
    decisions = iter([ap.Decision("continue", "busy", start_pending=True), ap.Decision("off", "disabled")])
    called = []

    async def after(*args):
        decision = next(decisions)
        called.append(decision.action)
        return decision

    async def no_delay(_seconds):
        pass

    monkeypatch.setattr(ap, "after_run", after)
    monkeypatch.setattr(handoff, "_sleep", no_delay)
    await handoff.finish_handoff({}, tmp_path, tmp_path, "conversation")
    assert called == ["continue", "off"]


@pytest.mark.asyncio
async def test_refused_held_steering_remains_a_pending_handoff(tmp_path: Path, monkeypatch) -> None:
    from thomas.server import thomas_project

    conversation = {"id": "steered", "turns": [{"role": "user", "text": "finish"}]}
    monkeypatch.setattr(ap, "_load_joined_conversation", lambda *args: conversation)
    monkeypatch.setattr(ap, "slot_running", lambda *args: False)
    monkeypatch.setattr(thomas_project, "held_steers", lambda cid: "also add sound")

    async def done(*args):
        return ap.Decision("done", "done check passed")

    async def refused(*args):
        return None

    monkeypatch.setattr(ap, "continue_after_turn", done)
    monkeypatch.setattr(ap, "_start_steered_round", refused)
    decision = await ap.after_run({}, tmp_path, tmp_path, "steered")
    assert decision.start_pending
