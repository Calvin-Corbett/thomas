"""A refused recovery launch leaves its yielded transcript available for retry."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from tests.drain_recovery_fixture import begin, clear
from tests.drain_recovery_fixture import drain as drain
from thomas.forge.anvil import forge_code_store
from thomas.server import landed_code_reload as reload
from thomas.server import landed_code_resume as recovery
from thomas.server import thomas_project
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_routes as routes
from thomas.server.routes import evolve_agent_runtime as runtime
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS


@pytest.mark.asyncio
@pytest.mark.parametrize("steers", [[], ["Keep my requested wording"]])
async def test_new_drain_during_real_launch_rolls_back_and_retries(drain, monkeypatch, steers):
    case, task = drain.add()
    monkeypatch.setattr(thomas_project, "_HELD_STEERS", {case.cid: list(steers)})
    await begin(drain)
    drain.yield_run(case, task)
    # Model settings are rewritten by the real route before it appends its turn.
    yielded = forge_code_store.load_conversation(case.root, case.cid)
    yielded["runtime_settings"] = {"before": "recovery"}
    forge_code_store._write_conversation(case.root, yielded)
    drain.app.pop(APP_EVOLVE_AGENT_RUNS, None)
    monkeypatch.setattr(routes, "attach_cleanup", lambda *a, **kw: None)
    monkeypatch.setattr(routes.evolve_agent_autopilot, "attach_after_run", lambda *a, **kw: None)
    monkeypatch.setattr(routes, "_attach_code_activity_release", lambda *a, **kw: None)
    routes.build_evolve_agent_handlers(drain.app, require_api_access=lambda _: None, root_resolver=lambda: drain.root)
    start = drain.app[APP_PRAXIS_START_CODE_RUN]
    responses = []

    async def capture(*a, **kw):
        result = await start(*a, **kw)
        responses.append(result)
        return result

    drain.app[APP_PRAXIS_START_CODE_RUN] = capture
    monkeypatch.setattr(routes.forge_code_projects, "validate_project_root", lambda root, **kw: Path(root))
    monkeypatch.setattr(routes.forge_code_projects, "thomas_source_repo_root", lambda: None)
    monkeypatch.setattr(routes, "_agent_launch", lambda *a, **kw: (["child"], {}))

    async def credential(*a, **kw):
        return "", None

    monkeypatch.setattr(routes, "prepare_code_oauth_credential", credential)
    monkeypatch.setattr(routes.forge_code_git, "snapshot", lambda root: {})

    children = []

    async def spawn(*a, **kw):
        child = SimpleNamespace(returncode=None)
        children.append(child)
        return child

    async def acquire(app, run_id):
        if len(children) == 1:
            app["landed_code_drain"] = {"id": "second"}
        return "lease"

    async def discard(child):
        child.returncode = 1
        return {"termination_confirmed": True}

    async def release(child, *a, **kw):
        child.released = True
        return "lease"

    async def record(*a, **kw):
        return None

    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(runtime, "acquire_code_activity_lease_async", acquire)
    monkeypatch.setattr(runtime, "_release_code_activity_lease", lambda *a: None)
    monkeypatch.setattr(runtime, "_terminate_process", discard)
    monkeypatch.setattr(routes, "_terminate_process", discard)
    monkeypatch.setattr(runtime, "_release_start_gate", release)
    monkeypatch.setattr(routes, "_drain_and_record", record)
    await reload.check_once(drain.app, None, 10, work=(), landed=None)
    assert len(children) == 1, responses
    assert not getattr(children[0], "released", False)
    assert forge_code_store.load_conversation(case.root, case.cid) == yielded
    assert thomas_project.held_steers(case.cid) == steers
    assert drain.app[recovery.APP_DRAIN_RUNS][case.cid].run_id == case.run_id
    drain.app.pop("landed_code_drain", None)
    await recovery.resume(drain.app)
    assert len(children) == 2
    assert children[1].released is True
    assert not drain.app[recovery.APP_DRAIN_RUNS]
    conversation = forge_code_store.load_conversation(case.root, case.cid)
    assert conversation["turns"][-2]["outcome"] == "reload_yielded"
    assert conversation["turns"][-1]["role"] == "user"
    assert "drain cleared without a reload" in conversation["turns"][-1]["text"]
    for steer in steers:
        assert steer in conversation["turns"][-1]["text"]
    assert thomas_project.held_steers(case.cid) == []
    assert responses[-1][0] == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_run_id", [True, False])
async def test_stop_after_registry_pruning_cancels_only_the_requested_yield(drain, explicit_run_id):
    from thomas.server.routes.evolve_agent_control_routes import build_evolve_agent_control_handlers
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_SESSION

    case, task = drain.add()
    other, other_task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    drain.yield_run(other, other_task)
    drain.app.pop(APP_EVOLVE_AGENT_RUNS, None)
    drain.app[APP_EVOLVE_AGENT_SESSION] = {"run_id": case.run_id}
    handlers = build_evolve_agent_control_handlers(
        drain.app,
        require_api_access=lambda _: None,
        _slot_for_run_id=lambda _: None,
        _running=lambda: False,
        _kill_tree=lambda _: None,
    )

    class Request:
        async def json(self):
            return {"run_id": case.run_id} if explicit_run_id else {}

    response = await handlers["stop"](Request())
    assert response.status == 409, json.loads(response.text)
    assert json.loads(response.text)["state"] == "not_running"
    await clear(drain)
    assert len(drain.started) == 1
    assert drain.started[0]["conversation_id"] == other.cid
    assert not drain.app[recovery.APP_DRAIN_RUNS]


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_stop_while_recording_cannot_be_reenrolled_by_another_drain_snapshot(drain, legacy):
    from thomas.server.routes.evolve_agent_run_state import (
        APP_EVOLVE_AGENT_CONVO,
        APP_EVOLVE_AGENT_DRAIN,
        APP_EVOLVE_AGENT_SESSION,
        APP_EVOLVE_AGENT_TASK,
    )

    case, task = drain.add()
    proc = SimpleNamespace(returncode=0)
    session = drain.app[APP_EVOLVE_AGENT_RUNS][case.cid]["session"]
    if legacy:
        drain.app[APP_EVOLVE_AGENT_RUNS].clear()
        drain.app[APP_EVOLVE_AGENT_SESSION] = session
        drain.app[APP_EVOLVE_AGENT_CONVO] = case.cid
        drain.app[APP_EVOLVE_AGENT_TASK] = proc
        drain.app[APP_EVOLVE_AGENT_DRAIN] = task
    else:
        session["proc"] = proc
    await begin(drain)
    recovery.cancel(drain.app, case.cid)
    runtime._mark_stop_requested(proc)
    await begin(drain)
    drain.yield_run(case, task)
    await clear(drain)
    assert drain.started == []
    assert not drain.app[recovery.APP_DRAIN_RUNS]
