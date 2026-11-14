"""A drain cancelled on the same server carries its yielded Builds on, once."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from aiohttp import web

from tests.drain_recovery_fixture import FIRST_RUN, begin, clear
from tests.drain_recovery_fixture import drain as drain
from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_restart, thomas_project
from thomas.server import landed_code_reload as reload
from thomas.server import landed_code_resume as resume
from thomas.server.app_keys import APP_SHUTDOWN_EVENT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, attach_cleanup, guarded_start
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes import evolve_agent_routes, evolve_agent_runtime
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_LOCK, APP_EVOLVE_AGENT_RUNS, active_code_runs


@pytest.mark.asyncio
async def test_recovery_gate_is_not_inherited_by_a_build_followup():
    from thomas.server.praxis.launch import recovery_start_allowed

    state = {"allowed": True}

    async def followup():
        state["allowed"] = False
        return recovery_start_allowed()

    with guarded_start(None, lambda: state["allowed"]):
        assert recovery_start_allowed()
        assert await asyncio.create_task(followup())


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["shutdown", "generation", "drain"])
async def test_a_stop_while_waiting_for_the_launch_lock_prevents_a_new_start(drain, monkeypatch, stop):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    await resume.finish_drain(drain.app)
    reload._clear_drain(drain.app)
    lock = drain.app[APP_EVOLVE_AGENT_LOCK]
    await lock.acquire()
    clearing = asyncio.create_task(resume.resume(drain.app))
    try:
        async with asyncio.timeout(30):
            while not lock._waiters:
                await asyncio.sleep(0.01)
        if stop == "shutdown":
            drain.app[APP_SHUTDOWN_EVENT].set()
        elif stop == "generation":
            monkeypatch.setattr(reload.workers, "generation_stopping", lambda: True)
        else:
            drain.app[reload.APP_LANDED_CODE_DRAIN] = {"head": "newer-head", "since": 10}
    finally:
        lock.release()
        await clearing
    assert not drain.started
    assert case[0].cid in drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["shutdown", "generation", "drain"])
async def test_a_stop_during_async_recovery_prevents_a_new_start(drain, monkeypatch, stop):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    entered, release = asyncio.Event(), threading.Event()

    def check_handoff(*_args):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(30)
        return False

    monkeypatch.setattr(autopilot_restart, "_handed_in", check_handoff)
    clearing = asyncio.create_task(reload.check_once(drain.app, None, 10, work=(), landed=None))
    try:
        async with asyncio.timeout(10):
            await entered.wait()
        if stop == "shutdown":
            drain.app[APP_SHUTDOWN_EVENT].set()
        elif stop == "generation":
            monkeypatch.setattr(resume.workers, "generation_stopping", lambda: True)
        else:
            drain.app[reload.APP_LANDED_CODE_DRAIN] = {"head": "newer"}
    finally:
        release.set()
    await clearing
    assert not drain.started
    assert drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_new_drain_during_final_admission_keeps_the_yield_for_retry(drain, monkeypatch):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    admit = resume._admit

    async def interrupted(*args):
        drain.app[reload.APP_LANDED_CODE_DRAIN] = {"head": "newer-head"}
        return await admit(*args)

    monkeypatch.setattr(resume, "_admit", interrupted)
    await reload.check_once(drain.app, None, 10, work=(), landed=None)
    assert not drain.started
    assert case.cid in drain.app[resume.APP_DRAIN_RUNS]
    monkeypatch.setattr(resume, "_admit", admit)
    await clear(drain)
    assert len(drain.started) == 1
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_replacement_live_run_takes_ownership_from_drain_recovery(drain):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    replacement = asyncio.get_running_loop().create_future()
    drain.app[APP_EVOLVE_AGENT_RUNS][case.cid] = {
        "session": {"run_id": "replacement-run"},
        "drain": replacement,
    }
    await clear(drain)
    assert not drain.app[resume.APP_DRAIN_RUNS]
    replacement.set_result(None)
    await clear(drain)
    assert not drain.started


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["instruction", "stop", "replacement", "finished_replacement"])
async def test_recovery_rechecks_conversation_ownership_under_the_launch_lock(drain, change):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    lock = drain.app[APP_EVOLVE_AGENT_LOCK]
    await lock.acquire()
    recovery = asyncio.create_task(clear(drain))
    try:
        for _ in range(200):
            if lock._waiters:
                break
            await asyncio.sleep(0.01)
        assert lock._waiters, "recovery did not reach the launch lock"
        if change == "instruction":
            forge_code_store.append_user_turn(case.root, case.cid, "Do something else", request_id="newer")
        elif change == "stop":
            conversation = forge_code_store.load_conversation(case.root, case.cid)
            conversation.setdefault("thomas_project", {})["stopped_at"] = "2999-01-01T00:00:00+00:00"
            forge_code_store.write_conversation(case.root, conversation)
        else:
            replacement = asyncio.create_task(asyncio.sleep(0))
            session = {"project_root": str(case.root), "conversation_id": case.cid, "run_id": "replacement"}
            drain.app[APP_EVOLVE_AGENT_RUNS][case.cid] = {"task": replacement, "session": session}
            attach_cleanup(drain.app, replacement, "replacement", None, session=session)
            if change == "finished_replacement":
                await replacement
                drain.app[APP_EVOLVE_AGENT_RUNS].pop(case.cid)
    finally:
        lock.release()
        await asyncio.wait_for(recovery, timeout=10)
    assert not drain.started
    await clear(drain)
    assert not drain.started


@pytest.mark.asyncio
async def test_a_different_runs_yield_is_not_resumed(drain):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    forge_code_store.append_agent_turn(
        case.root, case.cid, **{**FIRST_RUN, "outcome": "reload_yielded", "run_id": "replacement"}
    )
    await clear(drain)
    assert not drain.started
    assert not drain.app[resume.APP_DRAIN_RUNS]


@pytest.mark.asyncio
async def test_a_missing_conversation_is_retried_after_a_transient_read_failure(drain, monkeypatch):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    read = thomas_project._read_live
    monkeypatch.setattr(thomas_project, "_read_live", lambda *_a: None)
    await clear(drain)
    assert not drain.started
    assert case[0].cid in drain.app[resume.APP_DRAIN_RUNS]
    monkeypatch.setattr(thomas_project, "_read_live", read)
    await clear(drain)
    assert len(drain.started) == 1


@pytest.mark.asyncio
async def test_a_new_drain_blocks_resume_until_it_too_clears(drain):
    case = drain.add()
    await begin(drain)
    drain.yield_run(*case)
    assert (
        await reload.check_once(
            drain.app, None, 1, work=("check threads",), landed=("old", "newer", ["thomas/another.py"])
        )
        is None
    )
    assert not drain.started
    await clear(drain)
    assert len(drain.started) == 1
