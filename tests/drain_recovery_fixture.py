"""A drain cancelled on the same server carries its yielded Builds on, once."""

import asyncio
import copy
import time
from types import SimpleNamespace

import pytest
from aiohttp import web

from tests.restart_test_isolation import start_no_rows
from thomas.forge.anvil import forge_code_conversations, forge_code_projects, forge_code_settings, forge_code_store
from thomas.server import autopilot_restart, thomas_project
from thomas.server import landed_code_reload as reload
from thomas.server import landed_code_resume as resume
from thomas.server.app_keys import APP_SHUTDOWN_EVENT
from thomas.server.praxis.launch import bind_internal_start, recovery_start_allowed
from thomas.server.routes import evolve_agent_autopilot as ap
from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_LOCK, APP_EVOLVE_AGENT_RUNS
from thomas.server.routes.evolve_agent_runtime import _transcript_path

FIRST_RUN = {
    "model": "test",
    "transcript": "",
    "changed_files": ["example.py"],
    "returncode": 0,
    "ok": True,
    "noop": False,
    "reason": "1 file(s) changed",
    "outcome": "completed",
    "report": {"open_risks": []},
}


async def nothing():
    return None


def isolate_restart_boot(monkeypatch, tmp_path):
    from thomas.core import persistence
    from thomas.server import app_core, app_routes_init
    from thomas.tools.registry import ToolRegistry

    # Keep the real application lifecycle, without unrelated tool and route discovery.
    monkeypatch.setattr(app_core, "_build_tools", lambda _config: ToolRegistry())
    monkeypatch.setattr(app_routes_init, "register_optional_route_families", lambda *_args, **_kwargs: None)
    start_no_rows(monkeypatch)
    monkeypatch.setattr(
        persistence,
        "_engine",
        persistence.PersistenceEngine(state_file=tmp_path / "state.json", report_dir=tmp_path / "reports"),
    )


_RUNNER_SCAN = autopilot_restart._runners_of


@pytest.fixture(autouse=True)
def restart_isolated(tmp_path, monkeypatch):
    import threading

    from thomas.core import persistence
    from thomas.forge.anvil import forge_code_projects

    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(forge_code_projects, "validate_project_root", lambda p, **_kw: p)
    monkeypatch.setattr(forge_code_projects, "shield_thomas_dir", lambda _p: None)
    monkeypatch.setattr(autopilot_restart, "_pass", autopilot_restart._Pass())
    monkeypatch.setattr(autopilot_restart, "_lock", threading.RLock())
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(
        persistence,
        "_engine",
        persistence.PersistenceEngine(state_file=tmp_path / "state.json", report_dir=tmp_path / "reports"),
    )
    recorded = []
    monkeypatch.setattr(ap, "record_issue", lambda **kwargs: recorded.append(kwargs))
    return recorded


@pytest.fixture
def runner_scan(isolated, monkeypatch):
    import psutil

    pids = []

    def scan(cid):
        def processes(_attrs):
            for pid in pids:
                try:
                    root = psutil.Process(pid)
                    for proc in [root, *root.children(recursive=True)]:
                        proc.info = {"cmdline": proc.cmdline()}
                        yield proc
                except psutil.NoSuchProcess:
                    continue

        with monkeypatch.context() as patch:
            patch.setattr(psutil, "process_iter", processes)
            return _RUNNER_SCAN(cid)

    scan.register = pids.append
    return scan


def _pending_run(folder, *, thomas):
    root = folder / "work"
    record = {"execution_id": "thomas-0123456789ab"} if thomas else None
    cid = forge_code_store.new_conversation(root, title="drain recovery", thomas_project=record)["id"]
    forge_code_store.append_user_turn(root, cid, "Finish the requested change", request_id="request-before")
    return SimpleNamespace(root=root, cid=cid)


@pytest.fixture
def drain(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("THOMAS_OWNED_ROOT", str(tmp_path))
    monkeypatch.setenv("THOMAS_SELF_EDIT_HOME", str(tmp_path / "data"))
    monkeypatch.delenv(reload.TRAY_PORT_ENV, raising=False)
    monkeypatch.setattr(reload.cage_shell, "cage_root", lambda: tmp_path / "cage")
    registry = {}
    monkeypatch.setattr(forge_code_conversations, "_load_registry", lambda _root: dict(registry))
    monkeypatch.setattr(forge_code_conversations, "_write_registry", lambda _root, rows: registry.update(rows))
    monkeypatch.setattr(forge_code_projects, "validate_project_root", lambda root, **_kw: root)
    monkeypatch.setattr(forge_code_projects, "shield_thomas_dir", lambda _root: None)
    conversations = {}

    def write_conversation(root, conversation):
        conversations[(str(root), conversation["id"])] = copy.deepcopy(conversation)
        return conversation

    def load_conversation(root, cid):
        return copy.deepcopy(conversations.get((str(root), cid)))

    monkeypatch.setattr(forge_code_store, "_write_conversation", write_conversation)
    monkeypatch.setattr(forge_code_store, "load_conversation", load_conversation)
    monkeypatch.setattr(thomas_project, "_read_live", lambda root, _catalog, cid: load_conversation(root, cid))
    monkeypatch.setattr(thomas_project, "_catalog_root", lambda: tmp_path)
    # These tests are about Builds that are asked to stop: what happens once landed code has waited its longest.
    monkeypatch.setattr(reload, "BUILD_HOLD_S", 0.0)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_tray_port", lambda: None)
    monkeypatch.setattr(reload.cage_shell, "posture", lambda: "required")
    monkeypatch.setattr(reload.workers, "generation_stopping", lambda: False)
    monkeypatch.setattr(reload, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(autopilot_restart, "_pass", autopilot_restart._Pass(booted_at=time.time() - 3600))
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(autopilot_restart, "_cage_down", lambda: False)
    monkeypatch.setattr(autopilot_restart, "_keep_green", lambda *_a: None)
    monkeypatch.setattr(ap, "record_issue", lambda **_kw: None)
    monkeypatch.setattr(resume.machine_capacity, "admission_refusal", lambda _n: None)
    app = {APP_SHUTDOWN_EVENT: asyncio.Event(), APP_EVOLVE_AGENT_RUNS: {}, APP_EVOLVE_AGENT_LOCK: asyncio.Lock()}
    started = []

    async def start(body, _message, *, local_port):
        cid = body["conversation_id"]
        started.append(body)
        root = forge_code_projects.conversation_metadata(tmp_path, cid)["project_root"]
        forge_code_store.append_user_turn(root, cid, body["message"], request_id=f"resumed-{cid}")
        assert recovery_start_allowed(), "recovery admission changed"
        app.setdefault(APP_EVOLVE_AGENT_RUNS, {})[cid] = {
            "drain": asyncio.get_running_loop().create_future(),
            "session": {"run_id": f"resumed-{cid}", "project_root": root},
        }
        return web.json_response({"run_id": f"resumed-{cid}"}, status=202)

    bind_internal_start(app, start, app[APP_EVOLVE_AGENT_LOCK])
    app[ap.APP_LOCAL_PORT] = 8899

    cases = []

    def add(*, thomas=True, autonomy=1):
        case = _pending_run(tmp_path / f"case-{len(cases)}", thomas=thomas)
        cases.append(case)
        case.run_id = f"yield-{case.cid}"
        case.turn = forge_code_store.load_conversation(case.root, case.cid)["turns"][-1]
        forge_code_projects.bind_conversation(
            tmp_path,
            case.cid,
            case.root,
            settings={"requested": {"autonomy_level": autonomy}},
            allow_without_history=True,
        )
        task = asyncio.get_running_loop().create_future()
        app[APP_EVOLVE_AGENT_RUNS][case.cid] = {
            "drain": task,
            "session": {
                "project_root": str(case.root),
                "conversation_id": case.cid,
                "run_id": case.run_id,
                "request_id": case.turn["request_id"],
            },
        }
        return case, task

    def yield_run(case, task):
        forge_code_store.append_agent_turn(
            case.root, case.cid, **{**FIRST_RUN, "outcome": "reload_yielded", "run_id": case.run_id}
        )
        transcript = _transcript_path(tmp_path, case.run_id)
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text("yield recorded on this server", encoding="utf-8")
        task.set_result(None)

    async def no_retry_delay(_seconds):
        await asyncio.sleep(0)

    monkeypatch.setattr(ap, "_sleep", no_retry_delay)
    try:
        yield SimpleNamespace(app=app, root=tmp_path, started=started, add=add, yield_run=yield_run)
    finally:
        for slot in app.get(APP_EVOLVE_AGENT_RUNS, {}).values():
            task = slot.get("task") or slot.get("drain")
            if isinstance(task, dict):
                task = task.get("task")
            if task is not None:
                task.cancel()


async def begin(drain):
    assert (
        await reload.check_once(
            drain.app, None, 0, work=("Build run",), landed=("old", "new", ["thomas/not_loaded.py"])
        )
        is None
    )
    assert reload.APP_LANDED_CODE_DRAIN in drain.app


async def clear(drain):
    assert await reload.check_once(drain.app, None, 10, work=(), landed=None) is None
    assert reload.APP_LANDED_CODE_DRAIN not in drain.app
    assert not drain.app[APP_SHUTDOWN_EVENT].is_set()
