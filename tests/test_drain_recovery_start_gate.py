"""A drain cancelled on the same server carries its yielded Builds on, once."""

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web

from tests.drain_recovery_fixture import begin
from tests.drain_recovery_fixture import drain as drain
from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_store
from thomas.server import landed_code_reload as reload
from thomas.server import landed_code_resume as resume
from thomas.server import thomas_project
from thomas.server.app_keys import APP_SHUTDOWN_EVENT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, guarded_start
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes import evolve_agent_routes, evolve_agent_runtime
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_LOCK, active_code_runs


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "steering", "stop", "instruction", "replacement"])
@pytest.mark.parametrize("pause", ["lease", "payload", "pipe"])
async def test_recovery_rechecks_conversation_after_waiting_for_activity_lease(drain, monkeypatch, change, pause):
    case, task = drain.add()
    await begin(drain)
    drain.yield_run(case, task)
    await resume.finish_drain(drain.app)
    reload._clear_drain(drain.app)
    pending = drain.app[resume.APP_DRAIN_RUNS][case.cid]
    message = f"{ap.RESTART_PREFIX} after a cleared drain\n\n{ap.RESTART_MARK}Finish the requested change"
    steers = ["Check the regression first"] if change == "steering" else []
    monkeypatch.setattr(thomas_project, "held_steers", lambda _cid: steers)
    steered = thomas_project.steering_message(steers, message)
    forge_code_store.append_user_turn(case.root, case.cid, steered, request_id="resuming")
    released, leases = [], []

    def change_ownership():
        if change == "stop":
            conversation = forge_code_store.load_conversation(case.root, case.cid)
            conversation.setdefault("thomas_project", {})["stopped_at"] = "2999-01-01T00:00:00+00:00"
            forge_code_store.write_conversation(case.root, conversation)
        elif change == "instruction":
            forge_code_store.append_user_turn(case.root, case.cid, "Do something else", request_id="new")
        elif change == "replacement":
            resume.track_start(drain.app, {"conversation_id": case.cid, "run_id": "replacement"})

    async def acquire(*_args):
        if pause == "lease":
            change_ownership()
        return "lease"

    async def release(*_args, **_kwargs):
        from thomas.server.praxis.launch import recovery_start_allowed

        released.append(True)
        assert recovery_start_allowed()

    class Pipe:
        def write(self, payload):
            released.append(True)

        async def drain(self):
            change_ownership()

        def close(self):
            pass

    monkeypatch.setattr(evolve_agent_runtime, "acquire_code_activity_lease_async", acquire)
    if pause == "lease":
        monkeypatch.setattr(evolve_agent_runtime, "_release_start_gate", release)
    monkeypatch.setattr(evolve_agent_runtime, "_release_code_activity_lease", lambda *args: leases.append(args[-1]))
    dumps = evolve_agent_runtime.json.dumps

    def payload(*args, **kwargs):
        result = dumps(*args, **kwargs)
        if pause == "payload":
            change_ownership()
        return result

    monkeypatch.setattr(evolve_agent_runtime.json, "dumps", payload)
    with guarded_start(None, lambda: resume._gate_admit(drain.app, drain.root, case.cid, pending, message)):
        proc = SimpleNamespace(stdin=Pipe())
        operation = evolve_agent_runtime._release_code_start_gate(drain.app, proc, "start", "", "run", message)
        if pause == "pipe" or change in {"unchanged", "steering"}:
            assert await operation == "lease"
        else:
            with pytest.raises(RuntimeError, match="recovery admission changed"):
                await operation
    assert released == ([True] if pause == "pipe" or change in {"unchanged", "steering"} else [])
    assert leases == ([] if pause == "pipe" or change in {"unchanged", "steering"} else ["lease"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["shutdown", "new_drain", "generation"])
async def test_recovery_rechecks_after_the_real_route_prepares_a_child(tmp_path, monkeypatch, change):
    repo = _new_repo(tmp_path)
    catalog = repo
    conversation = forge_code_store.new_conversation(repo, title="Recovery")
    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    stopping = {"generation": False}
    monkeypatch.setattr(resume.workers, "generation_stopping", lambda: stopping["generation"])
    terminated, leases = [], []
    proc = SimpleNamespace(pid=12345, returncode=None)

    async def spawn(*args, **kwargs):
        return proc

    async def acquire(*args):
        if change == "shutdown":
            app[APP_SHUTDOWN_EVENT].set()
        elif change == "new_drain":
            app[reload.APP_LANDED_CODE_DRAIN] = {"seen_at": 1}
        else:
            stopping["generation"] = True
        return "lease"

    async def terminate(child):
        terminated.append(child)
        child.returncode = 1
        return True

    async def opened(*args, **kwargs):
        pytest.fail("the prepared child must not receive a start payload after admission changes")

    async def allowed():
        return resume._can_resume(app)

    async def oauth(*args, **kwargs):
        return "test-oauth-token", None

    monkeypatch.setattr(evolve_agent_routes, "prepare_code_oauth_credential", oauth)
    monkeypatch.setattr(evolve_agent_routes, "_default_repo_root", lambda: repo)
    monkeypatch.setattr(evolve_agent_routes, "_agent_launch", lambda *a, **k: (["stub"], {}))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(evolve_agent_routes, "_terminate_process", terminate)
    monkeypatch.setattr(evolve_agent_runtime, "acquire_code_activity_lease_async", acquire)
    monkeypatch.setattr(evolve_agent_runtime, "_release_start_gate", opened)
    monkeypatch.setattr(evolve_agent_runtime, "_release_code_activity_lease", lambda *a: leases.append(a[-1]))
    handlers = evolve_agent_routes.build_evolve_agent_handlers(
        app, require_api_access=lambda request: None, root_resolver=lambda: catalog
    )
    cid = conversation["id"]
    request_id = f"recovery-{change}"
    body = {
        "project_root": str(repo),
        "conversation_id": cid,
        "request_id": request_id,
        "message": "carry on",
        "autonomy_level": 3,
        "provider": "gpt",
        "model": "gpt-5.5",
        "gpt_profile": "forgecode",
        "guardrails": "guarded",
        "file_access": "workspace",
    }
    start = app[APP_PRAXIS_START_CODE_RUN]
    with guarded_start(allowed, lambda: resume._can_resume(app)):
        with pytest.raises(RuntimeError, match="recovery admission changed"):
            await start(body, port=8899)
    assert terminated == [proc]
    assert leases == ["lease"]
    assert not evolve_agent_routes._action_receipt(catalog, "run", request_id)
    assert not forge_code_store.load_conversation(repo, cid)["turns"]
    assert not active_code_runs(app)
