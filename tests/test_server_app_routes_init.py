from __future__ import annotations

import asyncio
import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server.app_keys import (
    APP_ENGINE_MANAGER,
    APP_MEMORY,
    APP_RESTART_REQUESTED,
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    APP_RUNTIME_GUARD_TASK,
    APP_SESSIONS,
    APP_SHUTDOWN_EVENT,
    APP_TASK_LEDGER,
    APP_TOOLS,
    ChatSession,
)
from thomas.server.app_routes_init import _setup_routes_and_handlers


class _Snapshot:
    def __init__(self, session_id: str, payload: dict[str, object]) -> None:
        self.session_id = session_id
        self._payload = dict(payload)

    def to_dict(self) -> dict[str, object]:
        return dict(self._payload)


class _Ledger:
    def __init__(self, snapshot: _Snapshot | None = None, history: list[dict[str, object]] | None = None) -> None:
        self.snapshot = snapshot
        self.history = history or []

    def get_current(self, session_id: str) -> _Snapshot | None:
        _ = session_id
        return self.snapshot

    def get_latest(self) -> _Snapshot | None:
        return self.snapshot

    def get_history(self, session_id: str, *, limit: int) -> list[dict[str, object]]:
        _ = session_id
        return list(self.history[:limit])


class _Memory:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RunStore:
    def __init__(self) -> None:
        self.startup_reconciliations: list[dict[str, object]] = []
        self.shutdown_calls: list[dict[str, object]] = []
        self.stale_reconciliations: list[dict[str, object]] = []

    def reconcile_orphaned_runs(self, **kwargs: object) -> int:
        self.startup_reconciliations.append(dict(kwargs))
        return 1

    def reconcile_stale_runs(self, **kwargs: object) -> int:
        self.stale_reconciliations.append(dict(kwargs))
        return 0

    def shutdown(self, **kwargs: object) -> None:
        self.shutdown_calls.append(dict(kwargs))


class _ToolRegistry:
    def __init__(self, tools: list[object]) -> None:
        self._tools = list(tools)

    def list_tools(self) -> list[object]:
        return list(self._tools)


def _block_optional_route_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def _guarded_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # type: ignore[no-untyped-def]
        if name.startswith("thomas.server.routes."):
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)


def _build_test_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ledger: _Ledger | None = None,
    sessions: dict[str, ChatSession] | None = None,
    run_store_enabled: bool = False,
    run_store: _RunStore | None = None,
    memory: _Memory | None = None,
) -> tuple[web.Application, dict[str, dict[str, object]]]:
    _block_optional_route_imports(monkeypatch)

    async def _fake_runtime_guard_loop(app_ref: web.Application) -> None:
        _ = app_ref
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr("thomas.server.app_routes_init._runtime_guard_loop", _fake_runtime_guard_loop)

    web_dir = tmp_path / "web"
    static_dir = web_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "hello.txt").write_text("hello static", encoding="utf-8")
    (static_dir / "my_stuff.html").write_text("my stuff static", encoding="utf-8")

    stored_chats: dict[str, dict[str, object]] = {}
    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    app[APP_RESTART_REQUESTED] = False
    app[APP_TASK_LEDGER] = ledger
    app[APP_SESSIONS] = sessions or {}
    app[APP_MEMORY] = memory or _Memory()
    app[APP_RUN_STORE_ENABLED] = run_store_enabled
    app[APP_RUN_STORE_MODULE] = run_store
    app[APP_ENGINE_MANAGER] = SimpleNamespace(status=lambda: {"primary": "ok"})

    async def _read_json(request: web.Request) -> dict[str, object]:
        return dict(await request.json())

    async def _save_chat_to_disk(chat: dict[str, object]) -> None:
        stored_chats[str(chat["id"])] = dict(chat)

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        return stored_chats.pop(chat_id, None) is not None

    async def _load_all_chats_from_disk() -> list[dict[str, object]]:
        return list(stored_chats.values())

    async def _simple_page(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    locals_dict = {
        "_require_api_access": lambda request: None,
        "_require_loopback": lambda request: None,
        "_is_json_content_type": lambda request: True,
        "_read_json": _read_json,
        "_sanitize_chat_payload": lambda payload: dict(payload),
        "_save_chat_to_disk": _save_chat_to_disk,
        "_delete_chat_from_disk": _delete_chat_from_disk,
        "_load_all_chats_from_disk": _load_all_chats_from_disk,
        "_session_lock_for": None,
        "_begin_session_run": None,
        "_end_session_run": None,
        "_task_ledger_update": None,
        "_model_cfg_with_secrets": None,
        "_failover_cfgs_with_secrets": None,
        "_chat_file_for": None,
        "_read_chat_from_disk": None,
        "_build_tools": None,
        "index": _simple_page,
        "settings": _simple_page,
        "companion": _simple_page,
        "landing": _simple_page,
    }

    async def _webhook(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_post("/webhooks/receive/github", _webhook)

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )
    _setup_routes_and_handlers(
        app,
        cfg,
        web_dir,
        tmp_path / "chat_store",
        asyncio.Lock(),
        locals_dict=locals_dict,
    )
    return app, stored_chats


async def _start_client(app: web.Application) -> TestClient:
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_task_ledger_routes_enrich_snapshot_and_validate_history_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = ChatSession(
        id="sess-1",
        conversation=[
            {"role": "user", "content": "Need help with invoicing."},
            {"role": "assistant", "content": "Please send the customer email."},
        ],
        profile="local",
        last_user_message="Need help with invoicing.",
        last_assistant_message="Please send the customer email.",
    )
    ledger = _Ledger(
        snapshot=_Snapshot("sess-1", {"status": "in_progress", "active_goal": "", "last_progress": ""}),
        history=[{"status": "started"}],
    )
    app, _ = _build_test_app(tmp_path, monkeypatch, ledger=ledger, sessions={"sess-1": session})

    client = await _start_client(app)
    try:
        response = await client.get("/api/task-ledger/current?session_id=sess-1")
        assert response.status == 200
        payload = await response.json()
        assert payload["snapshot"]["active_goal"] == ""
        assert payload["snapshot"]["status"] == "in_progress"
        assert payload["snapshot"]["missing_inputs"] == []

        invalid = await client.get("/api/task-ledger/history?limit=oops")
        assert invalid.status == 400

        history = await client.get("/api/task-ledger/history?session_id=sess-1&limit=1")
        assert history.status == 200
        history_payload = await history.json()
        assert history_payload["events"] == [{"status": "started"}]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_chat_storage_static_compat_tools_and_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app, stored_chats = _build_test_app(tmp_path, monkeypatch)
    client = await _start_client(app)
    try:
        tools = await client.get("/api/tools")
        assert tools.status == 200
        tools_payload = await tools.json()
        assert tools_payload == {"tools": [], "count": 0}

        created = await client.put("/api/chats", json={"id": "chat-1", "title": "Inbox"})
        # api_chat_put now returns 200 + {ok: True, chat: ...} (was 201) to
        # align with tests/test_server_chats_api.py — see 0.15.36 in CHANGELOG.
        assert created.status == 200
        assert stored_chats["chat-1"]["title"] == "Inbox"

        listed = await client.get("/api/chats")
        assert listed.status == 200
        listed_payload = await listed.json()
        assert listed_payload["chats"] == [{"id": "chat-1", "title": "Inbox"}]

        deleted = await client.delete("/api/chats/chat-1")
        # api_chat_delete now returns 200 + {ok: True, deleted: <id>} (was 204).
        assert deleted.status == 200

        missing = await client.delete("/api/chats/chat-1")
        assert missing.status == 404

        static_file = await client.get("/static/hello.txt")
        assert static_file.status == 200
        assert await static_file.text() == "hello static"

        not_found = await client.get("/static/missing.txt")
        assert not_found.status == 404

        restart = await client.post("/api/server/restart")
        assert restart.status == 200
        assert app[APP_RESTART_REQUESTED] is True
        assert app[APP_SHUTDOWN_EVENT].is_set() is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_security_snapshot_and_engine_status_surface_registered_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = _build_test_app(tmp_path, monkeypatch)
    client = await _start_client(app)
    try:
        engines = await client.get("/api/engines")
        assert engines.status == 200
        assert (await engines.json())["engines"] == {"primary": "ok"}

        security = await client.get("/api/security/mutating-routes")
        assert security.status == 200
        payload = await security.json()
        policies = payload["policies"]
        assert any(item["sample_path"] == "/api/server/restart" for item in policies)
        assert any(item["path"] == "/webhooks/receive/github" for item in policies)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_startup_and_cleanup_manage_run_store_and_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _RunStore()
    memory = _Memory()
    app, _ = _build_test_app(
        tmp_path,
        monkeypatch,
        run_store_enabled=True,
        run_store=run_store,
        memory=memory,
    )

    client = await _start_client(app)
    try:
        assert run_store.startup_reconciliations
        assert APP_RUNTIME_GUARD_TASK in app
    finally:
        await client.close()

    assert run_store.shutdown_calls == [{"close_timeout": 5.0}]
    assert memory.closed is True


@pytest.mark.asyncio
async def test_run_store_janitor_reconciles_stale_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_store = _RunStore()

    def _reconcile_stale_runs(**kwargs: object) -> int:
        run_store.stale_reconciliations.append(dict(kwargs))
        return 2

    run_store.reconcile_stale_runs = _reconcile_stale_runs  # type: ignore[method-assign]
    monkeypatch.setattr("thomas.server.app_routes_init._RUN_STORE_JANITOR_INTERVAL_SECONDS", 0.01)
    app, _ = _build_test_app(
        tmp_path,
        monkeypatch,
        run_store_enabled=True,
        run_store=run_store,
        memory=_Memory(),
    )

    client = await _start_client(app)
    try:
        await asyncio.sleep(0.05)
    finally:
        await client.close()

    assert run_store.stale_reconciliations
    assert run_store.shutdown_calls == [{"close_timeout": 5.0}]


@pytest.mark.asyncio
async def test_static_compat_rejects_traversal_and_page_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _ = _build_test_app(tmp_path, monkeypatch)
    client = await _start_client(app)
    try:
        for route in ("/", "/mission", "/settings", "/companion", "/landing"):
            response = await client.get(route)
            assert response.status == 200
            assert await response.text() == "ok"

        for route in ("/my-stuff", "/my-stuff/", "/my_stuff", "/my_stuff/"):
            response = await client.get(route)
            assert response.status == 200
            assert await response.text() == "my stuff static"

        static_file = await client.get("/static/hello.txt")
        assert static_file.status == 200
        assert static_file.headers["Content-Type"].startswith("text/plain")

        blocked = await client.get("/static/../secrets.txt")
        assert blocked.status == 404
    finally:
        await client.close()


def test_optional_route_registration_wires_runtime_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_runtime_guard_loop(app_ref: web.Application) -> None:
        _ = app_ref
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr("thomas.server.app_routes_init._runtime_guard_loop", _fake_runtime_guard_loop)

    web_dir = tmp_path / "web"
    (web_dir / "static").mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    app[APP_RESTART_REQUESTED] = False
    app[APP_TASK_LEDGER] = SimpleNamespace(update=lambda *args, **kwargs: None)
    app[APP_SESSIONS] = {}
    app[APP_MEMORY] = _Memory()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ENGINE_MANAGER] = SimpleNamespace(status=lambda: {"primary": "ok"})

    called: dict[str, object] = {}

    def _record(name: str):
        def _inner(*args, **kwargs):  # type: ignore[no-untyped-def]
            called[name] = {"args": args, "kwargs": kwargs}

        return _inner

    monkeypatch.setitem(
        sys.modules, "thomas.server.routes.gateway", SimpleNamespace(register_gateway_routes=_record("gateway"))
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.chat_auxiliary",
        SimpleNamespace(register_chat_auxiliary_routes=_record("chat_aux")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.sessions_aiohttp",
        SimpleNamespace(register_sessions_routes=_record("sessions")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.models_aiohttp",
        SimpleNamespace(register_models_routes=_record("models")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.setup_aiohttp",
        SimpleNamespace(register_setup_routes=_record("setup")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.third_party_agent_access_aiohttp",
        SimpleNamespace(register_third_party_agent_access_routes=_record("third_party")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.preferences_aiohttp",
        SimpleNamespace(register_preferences_routes=_record("preferences")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.onboarding_aiohttp",
        SimpleNamespace(register_onboarding_routes=_record("onboarding")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.memory_aiohttp",
        SimpleNamespace(register_memory_routes=_record("memory_routes")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.search",
        SimpleNamespace(register_search_routes=_record("search")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.secrets_aiohttp",
        SimpleNamespace(register_secrets_routes=_record("secrets")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.local_projects_aiohttp",
        SimpleNamespace(register_local_project_routes=_record("local_projects")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.marketplace_catalog_aiohttp",
        SimpleNamespace(register_marketplace_catalog_routes=_record("marketplace")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.plugin_hosting",
        SimpleNamespace(register_plugin_hosting_routes=_record("plugin_hosting")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.life_manager_aiohttp",
        SimpleNamespace(register_life_manager_routes=_record("life_manager")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.mission",
        SimpleNamespace(register_mission_routes=_record("mission")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.observability",
        SimpleNamespace(register_observability_routes=_record("observability")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.chat_v2",
        SimpleNamespace(register_chat_v2_routes=_record("chat_v2")),
    )

    async def _read_json(request: web.Request) -> dict[str, object]:
        return dict(await request.json())

    async def _save_chat_to_disk(chat: dict[str, object]) -> None:
        _ = chat

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        _ = chat_id
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, object]]:
        return []

    async def _read_chat_from_disk(chat_id: str) -> dict[str, object]:
        return {"id": chat_id}

    locals_dict = {
        "_require_api_access": lambda request: None,
        "_require_loopback": lambda request: None,
        "_is_json_content_type": lambda request: True,
        "_read_json": _read_json,
        "_sanitize_chat_payload": lambda payload: dict(payload),
        "_save_chat_to_disk": _save_chat_to_disk,
        "_delete_chat_from_disk": _delete_chat_from_disk,
        "_load_all_chats_from_disk": _load_all_chats_from_disk,
        "_session_lock_for": lambda session_id: asyncio.Lock(),
        "_begin_session_run": lambda session_id: None,
        "_end_session_run": lambda session_id: None,
        "_task_ledger_update": lambda session_id, goal=None, status="in_progress": None,
        "_model_cfg_with_secrets": lambda cfg, profile, model_cfg: {"profile": profile, "model": model_cfg.model},
        "_failover_cfgs_with_secrets": lambda cfg, profile: [{"profile": "backup"}],
        "_chat_file_for": lambda chat_id: tmp_path / f"{chat_id}.json",
        "_read_chat_from_disk": _read_chat_from_disk,
        "_build_tools": lambda runtime_cfg: [{"name": "shell"}],
        "index": lambda request: web.Response(text="index"),
        "settings": lambda request: web.Response(text="settings"),
        "companion": lambda request: web.Response(text="companion"),
        "landing": lambda request: web.Response(text="landing"),
    }

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )
    _setup_routes_and_handlers(
        app,
        cfg,
        web_dir,
        tmp_path / "chat_store",
        asyncio.Lock(),
        locals_dict=locals_dict,
    )

    assert {"gateway", "sessions", "chat_aux", "models", "setup", "third_party", "preferences", "onboarding"}.issubset(
        called.keys()
    )
    assert {"memory_routes", "search", "secrets", "local_projects", "marketplace", "plugin_hosting"}.issubset(
        called.keys()
    )
    assert {"life_manager", "mission", "observability", "chat_v2"}.issubset(called.keys())
    assert callable(called["chat_aux"]["kwargs"]["require_api_access"])


@pytest.mark.asyncio
async def test_route_edges_cover_missing_ledger_engine_tool_registry_and_unknown_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _block_optional_route_imports(monkeypatch)

    async def _fake_runtime_guard_loop(app_ref: web.Application) -> None:
        _ = app_ref
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr("thomas.server.app_routes_init._runtime_guard_loop", _fake_runtime_guard_loop)

    web_dir = tmp_path / "web"
    static_dir = web_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "hello.txt").write_text("hello static", encoding="utf-8")

    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    app[APP_RESTART_REQUESTED] = False
    app[APP_TASK_LEDGER] = None
    app[APP_SESSIONS] = {}
    app[APP_MEMORY] = _Memory()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ENGINE_MANAGER] = None
    app[APP_TOOLS] = _ToolRegistry(
        [
            SimpleNamespace(name="shell", description="Run shell commands", category="system", parameters="bad"),
            SimpleNamespace(name="memory", description="Query memory", category="knowledge", parameters={"q": "str"}),
        ]
    )

    async def _read_json(request: web.Request) -> dict[str, object]:
        return dict(await request.json())

    async def _save_chat_to_disk(chat: dict[str, object]) -> None:
        _ = chat

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        _ = chat_id
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, object]]:
        return []

    async def _simple_page(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def _custom_mutation(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_post("/custom/action", _custom_mutation)

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )
    _setup_routes_and_handlers(
        app,
        cfg,
        web_dir,
        tmp_path / "chat_store",
        asyncio.Lock(),
        locals_dict={
            "_require_api_access": lambda request: None,
            "_require_loopback": lambda request: None,
            "_is_json_content_type": lambda request: True,
            "_read_json": _read_json,
            "_sanitize_chat_payload": lambda payload: dict(payload),
            "_save_chat_to_disk": _save_chat_to_disk,
            "_delete_chat_from_disk": _delete_chat_from_disk,
            "_load_all_chats_from_disk": _load_all_chats_from_disk,
            "_session_lock_for": None,
            "_begin_session_run": None,
            "_end_session_run": None,
            "_task_ledger_update": None,
            "_model_cfg_with_secrets": None,
            "_failover_cfgs_with_secrets": None,
            "_chat_file_for": None,
            "_read_chat_from_disk": None,
            "_build_tools": None,
            "index": _simple_page,
            "settings": _simple_page,
            "companion": _simple_page,
            "landing": _simple_page,
        },
    )

    client = await _start_client(app)
    try:
        current = await client.get("/api/task-ledger/current")
        assert current.status == 404

        history = await client.get("/api/task-ledger/history")
        assert history.status == 404

        engines = await client.get("/api/engines")
        assert engines.status == 200
        assert await engines.json() == {"status": "unavailable"}

        tools = await client.get("/api/tools")
        assert tools.status == 200
        tools_payload = await tools.json()
        assert tools_payload == {
            "tools": [
                {
                    "id": "shell",
                    "name": "shell",
                    "description": "Run shell commands",
                    "category": "system",
                    "status": "active",
                    "params": {},
                    "parameters": {},
                },
                {
                    "id": "memory",
                    "name": "memory",
                    "description": "Query memory",
                    "category": "knowledge",
                    "status": "active",
                    "params": {"q": "str"},
                    "parameters": {"q": "str"},
                },
            ],
            "count": 2,
        }

        blocked = await client.get("/static/")
        assert blocked.status == 404

        security = await client.get("/api/security/mutating-routes")
        assert security.status == 200
        policies = (await security.json())["policies"]
        assert {
            "method": "POST",
            "path": "/custom/action",
            "sample_path": "/custom/action",
            "authz": "unknown",
            "csrf": "unknown",
            "enforced_by": [],
        } in policies
    finally:
        await client.close()


def test_route_registration_skips_when_runtime_guards_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _fake_runtime_guard_loop(app_ref: web.Application) -> None:
        _ = app_ref
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr("thomas.server.app_routes_init._runtime_guard_loop", _fake_runtime_guard_loop)
    web_dir = tmp_path / "web"
    (web_dir / "static").mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    app[APP_RESTART_REQUESTED] = False
    app[APP_TASK_LEDGER] = None
    app[APP_SESSIONS] = {}
    app[APP_MEMORY] = _Memory()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ENGINE_MANAGER] = None

    async def _simple_page(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )

    with caplog.at_level("WARNING"):
        _setup_routes_and_handlers(
            app,
            cfg,
            web_dir,
            tmp_path / "chat_store",
            asyncio.Lock(),
            locals_dict={
                "_require_api_access": None,
                "_require_loopback": None,
                "_is_json_content_type": lambda request: True,
                "_read_json": None,
                "_sanitize_chat_payload": lambda payload: dict(payload),
                "_save_chat_to_disk": None,
                "_delete_chat_from_disk": None,
                "_load_all_chats_from_disk": lambda: [],
                "_session_lock_for": None,
                "_begin_session_run": None,
                "_end_session_run": None,
                "_task_ledger_update": None,
                "_model_cfg_with_secrets": None,
                "_failover_cfgs_with_secrets": None,
                "_chat_file_for": None,
                "_read_chat_from_disk": None,
                "_build_tools": None,
                "index": _simple_page,
                "settings": _simple_page,
                "companion": _simple_page,
                "landing": _simple_page,
            },
        )

    text = caplog.text
    assert "Chat/session route registration skipped: missing runtime dependencies" in text
    assert "Models route registration skipped: missing runtime dependencies" in text
    assert "Setup route registration skipped: missing runtime dependencies" in text
    assert "Third-party access route registration skipped: missing runtime dependencies" in text
    assert "Preferences/memory route registration skipped: missing runtime dependencies" in text
    assert "Search route registration skipped: missing runtime dependencies" in text
    assert "Secrets route registration skipped: missing runtime dependencies" in text
    assert "Local project route registration skipped: missing runtime dependencies" in text
    assert "Marketplace route registration skipped: missing runtime dependencies" in text
    assert "Mission routes unavailable: missing API access guard" in text


def test_route_registration_logs_module_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    async def _fake_runtime_guard_loop(app_ref: web.Application) -> None:
        _ = app_ref
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise

    monkeypatch.setattr("thomas.server.app_routes_init._runtime_guard_loop", _fake_runtime_guard_loop)
    web_dir = tmp_path / "web"
    (web_dir / "static").mkdir(parents=True, exist_ok=True)
    app = web.Application()
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    app[APP_RESTART_REQUESTED] = False
    app[APP_TASK_LEDGER] = SimpleNamespace(update=lambda *args, **kwargs: None)
    app[APP_SESSIONS] = {}
    app[APP_MEMORY] = _Memory()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ENGINE_MANAGER] = SimpleNamespace(status=lambda: {"primary": "ok"})

    def _boom(name: str, exc: Exception):
        def _inner(*args, **kwargs):  # type: ignore[no-untyped-def]
            _ = args, kwargs
            raise exc

        return _inner

    session_calls: list[object] = []
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.chat_auxiliary",
        SimpleNamespace(register_chat_auxiliary_routes=_boom("chat-aux", KeyError("chat-aux"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.sessions_aiohttp",
        SimpleNamespace(register_sessions_routes=lambda *args, **kwargs: session_calls.append((args, kwargs))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.models_aiohttp",
        SimpleNamespace(register_models_routes=_boom("models", KeyError("models"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.setup_aiohttp",
        SimpleNamespace(register_setup_routes=_boom("setup", RuntimeError("setup"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.third_party_agent_access_aiohttp",
        SimpleNamespace(register_third_party_agent_access_routes=_boom("third-party", KeyError("third-party"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.preferences_aiohttp",
        SimpleNamespace(register_preferences_routes=_boom("preferences", ValueError("preferences"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.onboarding_aiohttp",
        SimpleNamespace(register_onboarding_routes=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.memory_aiohttp",
        SimpleNamespace(register_memory_routes=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.search",
        SimpleNamespace(register_search_routes=_boom("search", ValueError("search"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.secrets_aiohttp",
        SimpleNamespace(register_secrets_routes=_boom("secrets", ValueError("secrets"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.local_projects_aiohttp",
        SimpleNamespace(register_local_project_routes=_boom("local-projects", ValueError("local-projects"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.marketplace_catalog_aiohttp",
        SimpleNamespace(register_marketplace_catalog_routes=_boom("marketplace", KeyError("marketplace"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.plugin_hosting",
        SimpleNamespace(register_plugin_hosting_routes=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.life_manager_aiohttp",
        SimpleNamespace(register_life_manager_routes=lambda *args, **kwargs: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.mission",
        SimpleNamespace(register_mission_routes=_boom("mission", KeyError("mission"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.observability",
        SimpleNamespace(register_observability_routes=_boom("observability", KeyError("observability"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.chat_v2",
        SimpleNamespace(register_chat_v2_routes=_boom("chat-v2", KeyError("chat-v2"))),
    )

    async def _read_json(request: web.Request) -> dict[str, object]:
        return dict(await request.json())

    async def _save_chat_to_disk(chat: dict[str, object]) -> None:
        _ = chat

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        _ = chat_id
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, object]]:
        return []

    async def _read_chat_from_disk(chat_id: str) -> dict[str, object]:
        return {"id": chat_id}

    async def _simple_page(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )

    with caplog.at_level("WARNING"):
        _setup_routes_and_handlers(
            app,
            cfg,
            web_dir,
            tmp_path / "chat_store",
            asyncio.Lock(),
            locals_dict={
                "_require_api_access": lambda request: None,
                "_require_loopback": lambda request: None,
                "_is_json_content_type": lambda request: True,
                "_read_json": _read_json,
                "_sanitize_chat_payload": lambda payload: dict(payload),
                "_save_chat_to_disk": _save_chat_to_disk,
                "_delete_chat_from_disk": _delete_chat_from_disk,
                "_load_all_chats_from_disk": _load_all_chats_from_disk,
                "_session_lock_for": lambda session_id: asyncio.Lock(),
                "_begin_session_run": lambda session_id: None,
                "_end_session_run": lambda session_id: None,
                "_task_ledger_update": lambda session_id, goal=None, status="in_progress": None,
                "_model_cfg_with_secrets": lambda cfg_ref, profile, model_cfg: {
                    "profile": profile,
                    "model": model_cfg.model,
                },
                "_failover_cfgs_with_secrets": lambda cfg_ref, profile: [{"profile": "backup"}],
                "_chat_file_for": lambda chat_id: tmp_path / f"{chat_id}.json",
                "_read_chat_from_disk": _read_chat_from_disk,
                "_build_tools": lambda runtime_cfg: [{"name": "shell"}],
                "index": _simple_page,
                "settings": _simple_page,
                "companion": _simple_page,
                "landing": _simple_page,
            },
        )

    text = caplog.text
    assert session_calls, "session lifecycle must register even when optional chat helpers fail"
    assert "Chat auxiliary routes unavailable:" in text
    assert "Session routes unavailable:" not in text
    assert "Models routes unavailable:" in text
    assert "Setup routes unavailable:" in text
    assert "Third-party access routes unavailable:" in text
    assert "Preferences/memory routes unavailable:" in text
    assert "Search routes unavailable:" in text
    assert "Secrets routes unavailable:" in text
    assert "Local project routes unavailable:" in text
    assert "Marketplace routes unavailable:" in text
    assert "Mission routes unavailable:" in text
    assert "Observability routes unavailable:" in text
    assert "Chat V2 routes unavailable:" in text
