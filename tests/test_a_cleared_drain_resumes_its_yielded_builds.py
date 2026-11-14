"""A drain cancelled on the same server carries its yielded Builds on, once."""

import asyncio
import sqlite3

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
async def test_all_four_yielded_runs_resume_without_a_server_start(drain):
    cases = [drain.add(thomas=i < 3) for i in range(4)]
    await begin(drain)
    for case, task in cases:
        drain.yield_run(case, task)
    await clear(drain)
    assert {body["conversation_id"] for body in drain.started} == {case.cid for case, _ in cases}
    assert {slot["session"]["run_id"] for slot in drain.app[APP_EVOLVE_AGENT_RUNS].values()} == {
        f"resumed-{case.cid}" for case, _ in cases
    }
    assert all("without a reload" in body["message"] for body in drain.started)
    assert all(case.turn["text"] in body["message"] for (case, _), body in zip(cases, drain.started, strict=True))
    await clear(drain)
    assert len(drain.started) == 4
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_all_four_resume_as_each_capacity_slot_becomes_available(drain, monkeypatch):
    cases = [drain.add() for _ in range(4)]
    await begin(drain)
    for case in cases:
        drain.yield_run(*case)
    monkeypatch.setattr(resume.machine_capacity, "admission_refusal", lambda count: "full" if count >= 2 else None)
    await clear(drain)
    assert len(drain.started) == 2
    assert len(drain.app[resume.APP_DRAIN_RUNS]) == 2
    for slot in drain.app[APP_EVOLVE_AGENT_RUNS].values():
        slot["drain"].cancel()
    await clear(drain)
    assert {body["conversation_id"] for body in drain.started} == {case.cid for case, _ in cases}
    assert not drain.app[resume.APP_DRAIN_RUNS]
    await clear(drain)
    assert len(drain.started) == 4


@pytest.mark.asyncio
async def test_late_yield_and_capacity_wait_are_retried_on_later_watcher_ticks(drain, monkeypatch):
    first, second = drain.add(), drain.add()
    await begin(drain)
    drain.yield_run(*first)
    monkeypatch.setattr(resume.machine_capacity, "admission_refusal", lambda _n: "full")
    await clear(drain)
    assert not drain.started
    assert len(drain.app[resume.APP_DRAIN_RUNS]) == 2
    drain.yield_run(*second)
    monkeypatch.setattr(resume.machine_capacity, "admission_refusal", lambda _n: None)
    await clear(drain)
    assert {body["conversation_id"] for body in drain.started} == {first[0].cid, second[0].cid}


@pytest.mark.asyncio
async def test_only_runs_from_this_drain_resume_and_a_newer_user_turn_wins(drain):
    unrelated, task = drain.add()
    drain.yield_run(unrelated, task)
    drain.app[APP_EVOLVE_AGENT_RUNS].clear()
    completed, completed_task = drain.add()
    steered, steered_task = drain.add()
    await begin(drain)
    completed_task.set_result(None)
    forge_code_store.append_agent_turn(completed.root, completed.cid, **FIRST_RUN)
    drain.yield_run(steered, steered_task)
    forge_code_store.append_user_turn(steered.root, steered.cid, "Wait, leave it stopped", request_id="newer")
    await clear(drain)
    assert not drain.started
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_an_unreadable_conversation_does_not_block_other_yielded_builds(drain, monkeypatch):
    from thomas.server import thomas_project

    broken, healthy = drain.add(), drain.add()
    await begin(drain)
    for case in (broken, healthy):
        drain.yield_run(*case)
    read = thomas_project._read_live

    def unreadable(root, catalog, cid):
        if cid == broken[0].cid:
            raise sqlite3.OperationalError("conversation temporarily locked")
        return read(root, catalog, cid)

    monkeypatch.setattr(thomas_project, "_read_live", unreadable)
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [healthy[0].cid]
    assert set(drain.app[resume.APP_DRAIN_RUNS]) == {broken[0].cid}
    monkeypatch.setattr(thomas_project, "_read_live", read)
    await clear(drain)
    assert len(drain.started) == 2
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_transient_start_refusal_retries_on_the_next_watcher_tick(drain, monkeypatch):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    start = ap._start_continuation

    async def refuse_once(*args, **kwargs):
        return False

    monkeypatch.setattr(ap, "_start_continuation", refuse_once)
    await clear(drain)
    assert not drain.started
    assert len(drain.app[resume.APP_DRAIN_RUNS]) == 1
    monkeypatch.setattr(ap, "_start_continuation", start)
    await clear(drain)
    assert len(drain.started) == 1
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "receipt", [{"state": "persistence_failed"}, {"persistence": {"persistence_confirmed": False}}]
)
async def test_an_unconfirmed_yield_receipt_is_retried_until_saved(drain, monkeypatch, receipt):
    from thomas.server.routes import evolve_agent_receipts

    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    monkeypatch.setattr(evolve_agent_receipts, "_action_receipt", lambda *a: receipt)
    await clear(drain)
    assert not drain.started
    assert len(drain.app[resume.APP_DRAIN_RUNS]) == 1
    receipt.clear()
    receipt["persistence_confirmed"] = True
    await clear(drain)
    assert len(drain.started) == 1
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_real_shutdown_does_not_resume_yielded_runs(drain):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    drain.app[APP_SHUTDOWN_EVENT].set()
    await reload.check_once(drain.app, None, 10, work=(), landed=None)
    assert not drain.started


@pytest.mark.asyncio
async def test_refused_start_is_retained_until_the_start_hook_accepts(drain):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    start = drain.app.pop(APP_PRAXIS_START_CODE_RUN)
    await clear(drain)
    assert not drain.started
    assert drain.app[resume.APP_DRAIN_RUNS]
    drain.app[APP_PRAXIS_START_CODE_RUN] = start
    await clear(drain)
    assert len(drain.started) == 1
    await clear(drain)
    assert len(drain.started) == 1


@pytest.mark.asyncio
async def test_a_start_already_admitted_when_the_drain_began_is_remembered(drain):
    reload.drain_signal_path().parent.mkdir(parents=True, exist_ok=True)
    lock = drain.app[APP_EVOLVE_AGENT_LOCK] = asyncio.Lock()
    await lock.acquire()
    await begin(drain)
    clearing = asyncio.create_task(clear(drain))
    try:
        await asyncio.sleep(0)
        assert not clearing.done()
        case = drain.add()
    finally:
        lock.release()
        await asyncio.wait_for(clearing, timeout=10)
    drain.yield_run(*case)
    await clear(drain)
    assert len(drain.started) == 1


@pytest.mark.asyncio
async def test_a_second_drain_tracks_the_new_run_in_the_same_conversation(drain):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    # A replacement start won the conversation before the first recovery tick.
    forge_code_store.append_user_turn(case.root, case.cid, "carry on", request_id="replacement-request")
    case.turn = forge_code_store.load_conversation(case.root, case.cid)["turns"][-1]
    case.run_id = "replacement-run"
    task = asyncio.get_running_loop().create_future()
    drain.app[APP_EVOLVE_AGENT_RUNS][case.cid] = {
        "session": {"project_root": str(case.root), "run_id": case.run_id, "request_id": case.turn["request_id"]},
        "drain": task,
    }
    await begin(drain)
    drain.yield_run(case, task)
    await clear(drain)
    assert len(drain.started) == 1


@pytest.mark.asyncio
async def test_an_inactive_yielded_slot_before_this_drain_is_not_adopted(drain):
    case = drain.add()
    drain.yield_run(*case)
    await begin(drain)
    await clear(drain)
    assert not drain.started


@pytest.mark.asyncio
async def test_a_run_admitted_during_the_drain_is_remembered_before_it_finishes(drain):
    await begin(drain)
    case, task = drain.add()
    session = drain.app[APP_EVOLVE_AGENT_RUNS][case.cid]["session"]
    attach_cleanup(drain.app, task, case.cid, None, session=session)
    drain.yield_run(case, task)
    drain.app[APP_EVOLVE_AGENT_RUNS].pop(case.cid)
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [case.cid]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_read", [1, 2])
@pytest.mark.parametrize("read_failure", [None, sqlite3.OperationalError("database is locked")])
async def test_a_transient_read_keeps_the_yield_pending(drain, monkeypatch, read_failure, failed_read):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    read = thomas_project._read_live
    calls = 0

    def unavailable_once(*args):
        nonlocal calls
        calls += 1
        if calls == failed_read:
            if isinstance(read_failure, Exception):
                raise read_failure
            return read_failure
        return read(*args)

    monkeypatch.setattr(thomas_project, "_read_live", unavailable_once)
    await clear(drain)
    assert not drain.started
    assert case.cid in drain.app[resume.APP_DRAIN_RUNS]
    await clear(drain)
    assert [body["conversation_id"] for body in drain.started] == [case.cid]
