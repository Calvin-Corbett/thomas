"""A drain cancelled on the same server carries its yielded Builds on, once."""

import asyncio

import pytest
from aiohttp import web

from tests.drain_recovery_fixture import FIRST_RUN, begin, clear
from tests.drain_recovery_fixture import drain as drain
from thomas.forge.anvil import forge_code_store
from thomas.server import landed_code_reload as reload
from thomas.server import landed_code_resume as resume
from thomas.server import thomas_project
from thomas.server.app_keys import APP_SHUTDOWN_EVENT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, attach_cleanup, bind_internal_start
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_LOCK, APP_EVOLVE_AGENT_RUNS


@pytest.mark.asyncio
async def test_resumed_build_keeps_its_normal_autopilot_followup(drain):
    from thomas.server.routes import evolve_agent_autopilot as ap

    case, task = drain.add(autonomy=5)
    await begin(drain)
    drain.yield_run(case, task)
    finish, followed_up = asyncio.Event(), asyncio.Event()
    recorders = []

    async def start(body, _message, *, local_port):
        number = len(drain.started) + 1
        drain.started.append(body)
        forge_code_store.append_user_turn(case.root, case.cid, body["message"], request_id=f"round-{number}")

        async def record():
            await finish.wait()
            forge_code_store.append_agent_turn(
                case.root, case.cid, **{**FIRST_RUN, "run_id": f"round-{number}", "outcome": "failed"}
            )

        recorder = asyncio.create_task(record() if number == 1 else asyncio.sleep(60))
        recorders.append(recorder)
        session = {"project_root": str(case.root), "conversation_id": case.cid, "run_id": f"round-{number}"}
        drain.app[APP_EVOLVE_AGENT_RUNS][case.cid] = {"drain": recorder, "session": session}
        attach_cleanup(drain.app, recorder, f"round-{number}", None, session=session)
        if number == 1:
            ap.attach_after_run(drain.app, recorder, case.root, drain.root, case.cid)
        else:
            followed_up.set()
        return web.json_response({"run_id": f"round-{number}"}, status=202)

    bind_internal_start(drain.app, start, drain.app[APP_EVOLVE_AGENT_LOCK])
    try:
        await clear(drain)
        assert len(drain.started) == 1
        finish.set()
        await asyncio.wait_for(followed_up.wait(), timeout=15)
        assert len(drain.started) == 2
        assert "without a reload" in drain.started[0]["message"]
        assert "without a reload" not in drain.started[1]["message"]
    finally:
        for recorder in recorders:
            recorder.cancel()
        await asyncio.gather(*recorders, return_exceptions=True)


@pytest.mark.asyncio
async def test_receipt_read_failure_retries_without_discarding_the_yield(drain, monkeypatch):
    from thomas.server.routes import evolve_agent_receipts as receipts

    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    read = receipts._action_receipt

    def unavailable(*_args):
        raise RuntimeError("receipts temporarily unreadable")

    monkeypatch.setattr(receipts, "_action_receipt", unavailable)
    await clear(drain)
    assert not drain.started
    assert case.cid in drain.app[resume.APP_DRAIN_RUNS]
    monkeypatch.setattr(receipts, "_action_receipt", read)
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [case.cid]


@pytest.mark.asyncio
async def test_a_failed_recording_is_not_resumed_even_with_a_yielded_turn(drain):
    from thomas.server.routes.evolve_agent_receipts import _save_action_receipt

    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    _save_action_receipt(
        drain.root,
        "run",
        case.turn["request_id"],
        {"state": "persistence_failed", "persistence": {"persistence_confirmed": False}},
    )
    await clear(drain)
    assert not drain.started
    assert case.cid in drain.app[resume.APP_DRAIN_RUNS]
    _save_action_receipt(
        drain.root,
        "run",
        case.turn["request_id"],
        {"state": "completed", "persistence": {"persistence_confirmed": True}},
    )
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [case.cid]
    assert case.cid not in drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_run_launched_during_drain_is_remembered_after_it_leaves_the_registry(drain):
    await begin(drain)
    case, task = drain.add()
    session = drain.app[APP_EVOLVE_AGENT_RUNS][case.cid]["session"]
    attach_cleanup(drain.app, task, case.cid, None, session=session)
    drain.yield_run(case, task)
    drain.app[APP_EVOLVE_AGENT_RUNS].pop(case.cid)
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [case.cid]
