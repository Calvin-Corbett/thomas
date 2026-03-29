from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import AppConfig, MemoryConfig, ModelConfig, ServerConfig
from thomas.server import app_core
from thomas.server.app_keys import (
    APP_CONFIG,
    APP_GUARDRAILS_CTX,
    APP_RESTART_REQUESTED,
    APP_SECRETS,
    APP_SHUTDOWN_EVENT,
)


class _PrefsStore:
    def __init__(self, _db_path: str = "") -> None:
        self._prefs = SimpleNamespace(
            advanced=SimpleNamespace(
                security=SimpleNamespace(enforcement_mode="protected"),
                tools=SimpleNamespace(
                    allow_shell=True,
                    allow_file_write=True,
                    allow_network=True,
                    allow_browser=True,
                    allow_channels=True,
                    allow_git=True,
                ),
            )
        )

    def get(self):  # noqa: ANN201
        return self._prefs


class _SecretStoreBoom:
    def __init__(self, _path: Path) -> None:
        raise RuntimeError("boom")


class _TaskLedgerStore:
    def __init__(self, path: Path) -> None:
        self.path = path


class _RunStoreModule:
    def __init__(self) -> None:
        self.init_db_calls: list[Path] = []

    def init_db(self, path: Path) -> None:
        self.init_db_calls.append(path)


class _PrefsStoreRestricted:
    def __init__(self, _db_path: str = "") -> None:
        self._prefs = SimpleNamespace(
            advanced=SimpleNamespace(
                security=SimpleNamespace(enforcement_mode="off"),
                tools=SimpleNamespace(
                    allow_shell=False,
                    allow_file_write=True,
                    allow_network=False,
                    allow_browser=False,
                    allow_channels=True,
                    allow_git=False,
                ),
            )
        )

    def get(self):  # noqa: ANN201
        return self._prefs


def _base_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy", base_url="http://127.0.0.1:11434/v1")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
        server=ServerConfig(access_mode="local"),
    )


async def _start_client(app: web.Application) -> TestClient:
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.fixture
def patch_create_app_dependencies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_core, "_build_tools", lambda cfg: [])
    monkeypatch.setattr(app_core, "_build_memory", lambda cfg: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(app_core, "_runtime_guard_boot_state", lambda cfg: {"status": "ok"})
    monkeypatch.setattr(app_core, "_runtime_guard_refresh", lambda app: None)
    monkeypatch.setattr(app_core, "SecretStore", lambda path: SimpleNamespace(path=path))
    monkeypatch.setattr(app_core, "resolve_task_ledger_db_path", lambda root: Path(root) / ".thomas" / "task_ledger.sqlite3")
    monkeypatch.setattr(app_core, "TaskLedgerStore", _TaskLedgerStore)
    run_store = _RunStoreModule()
    monkeypatch.setitem(sys.modules, "thomas.marketplace.observability.run_store", run_store)
    monkeypatch.setitem(sys.modules, "thomas.server.routes.runs", SimpleNamespace(register_runs_routes=lambda app, config: None))
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.policy.redact",
        SimpleNamespace(Redactor=lambda additional_patterns=None: SimpleNamespace(patterns=additional_patterns or [])),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.audit_log",
        SimpleNamespace(AuditLog=lambda path, redactor: SimpleNamespace(path=path, redactor=redactor)),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.audit",
        SimpleNamespace(
            handle_audit_files=lambda request: (b"{}", 200, {}),
            handle_audit_run_files=lambda request, run_id: (f'{{"run":"{run_id}"}}'.encode("utf-8"), 200, {}),
        ),
    )
    monkeypatch.setattr(app_core._file_audit, "init_audit", lambda path: None)
    monkeypatch.setitem(sys.modules, "thomas.agent.approval", SimpleNamespace(ApprovalBroker=lambda: SimpleNamespace()))
    monkeypatch.setitem(
        sys.modules,
        "thomas.agent.guarded_tools",
        SimpleNamespace(GuardedToolRunner=lambda **kwargs: SimpleNamespace(kwargs=kwargs)),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.policy.config",
        SimpleNamespace(
            load_policy_config=lambda root: SimpleNamespace(
                deny_groups=[],
                redact_additional_patterns=[],
                guardrails=SimpleNamespace(enabled=True, approval_timeout_s=3, no_human_mode="off"),
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.policy.policy",
        SimpleNamespace(PolicyEngine=SimpleNamespace(from_config=lambda cfg, tool_categories=None: SimpleNamespace())),
    )
    monkeypatch.setitem(sys.modules, "thomas.server.guardrails_api", SimpleNamespace(install_guardrails_routes=lambda app, approvals: None))
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.realtime.routes",
        SimpleNamespace(setup_realtime_routes=lambda app, require_api_access=None: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.autonomy",
        SimpleNamespace(install_autonomy=lambda app, config, enabled=False, api_token=None: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.core.engine_manager",
        SimpleNamespace(get_engine_manager=lambda: SimpleNamespace(start_all=lambda: {"ok": True})),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.health",
        SimpleNamespace(register_health_ready_route=lambda app: app.router.add_get("/readyz", lambda req: web.json_response({"ok": True}))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.boot_recovery",
        SimpleNamespace(
            read_boot_recovery_notice=lambda repo_root, consume=False: {"severity": "degraded", "report_path": ""},  # noqa: ARG005
            reconcile_boot_doctor_runtime_state=lambda repo_root, port=0: ({"severity": "ok"}, {"status": "clean"}),  # noqa: ARG005
            read_boot_doctor_status=lambda repo_root, consume=False: {},  # noqa: ARG005
            clear_boot_recovery_notice=lambda repo_root: None,  # noqa: ARG005
            write_boot_doctor_status=lambda *args, **kwargs: None,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.app_middleware_handlers",
        SimpleNamespace(setup_middleware_and_handlers=lambda app, config, web_dir, chat_store_dir, chat_store_lock: app.__setitem__(APP_SHUTDOWN_EVENT, asyncio.Event())),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.core.model_resolution",
        SimpleNamespace(resolve_effective_model=lambda config, env_profile="", user_id="", db_path="": ("local", "resolved-model")),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.preferences.store",
        SimpleNamespace(PreferencesStore=_PrefsStore, get_db_path=lambda: str(tmp_path / "prefs.sqlite3")),
    )


def test_create_app_applies_model_resolution_and_health_security_flag(
    tmp_path: Path, patch_create_app_dependencies: None
) -> None:
    app = app_core.create_app(_base_config(tmp_path))
    assert app[APP_CONFIG].default_model == "local"
    assert app[APP_CONFIG].models["local"].model == "resolved-model"


@pytest.mark.asyncio
async def test_api_health_reports_protected_mode_and_bootdoctor_routes(
    tmp_path: Path, patch_create_app_dependencies: None
) -> None:
    app = app_core.create_app(_base_config(tmp_path))
    client = await _start_client(app)
    try:
        health = await client.get("/api/health")
        assert health.status == 200
        payload = await health.json()
        assert payload["security"]["protected_mode"] is True
        assert "features" in payload

        healthz = await client.get("/healthz")
        assert healthz.status == 200

        ready = await client.get("/readyz")
        assert ready.status == 200

        notice = await client.get("/api/bootdoctor/recovery_notice?consume=1")
        assert notice.status == 200
        assert (await notice.json())["notice"]["severity"] == "degraded"

        status = await client.get("/api/bootdoctor/status")
        assert status.status == 200
        status_payload = await status.json()
        assert status_payload["status"]["severity"] == "ok"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_bootdoctor_report_and_actions_cover_success_and_failures(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "bootdoctor-report.txt"
    report_path.write_text("bootdoctor report", encoding="utf-8")

    clear_calls: list[Path] = []
    write_calls: list[dict[str, object]] = []

    monkeypatch.setitem(
        sys.modules,
        "thomas.server.boot_recovery",
        SimpleNamespace(
            read_boot_recovery_notice=lambda repo_root, consume=False: {
                "severity": "degraded",
                "reason": "Need repair",
                "report_path": str(report_path),
                "repairs": ["check"],
                "probe_results": ["probe"],
            },
            reconcile_boot_doctor_runtime_state=lambda repo_root, port=0: ({"severity": "degraded"}, {"severity": "degraded"}),
            read_boot_doctor_status=lambda repo_root, consume=False: {
                "severity": "degraded",
                "reason": "Need repair",
                "report_path": str(report_path),
                "repairs": ["check"],
                "probe_results": ["probe"],
            },
            clear_boot_recovery_notice=lambda repo_root: clear_calls.append(Path(repo_root)),
            write_boot_doctor_status=lambda repo_root, **kwargs: write_calls.append(dict(kwargs)),
        ),
    )

    popen_calls: list[list[str]] = []
    monkeypatch.setattr(
        app_core.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(list(args)) or SimpleNamespace(pid=1),
    )

    app = app_core.create_app(_base_config(tmp_path))
    app[app_core.APP_BOOT_DOCTOR_ROOT] = tmp_path
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "bootdoctor.ps1").write_text("Write-Output 'bootdoctor'", encoding="utf-8")
    client = await _start_client(app)
    try:
        report = await client.get("/api/bootdoctor/report")
        assert report.status == 200
        assert await report.text() == "bootdoctor report"

        dismiss = await client.post("/api/bootdoctor/action", json={"action": "dismiss_notice"})
        assert dismiss.status == 200
        assert clear_calls

        retry = await client.post("/api/bootdoctor/action", json={"action": "retry_repair", "reason": "Investigate"})
        assert retry.status == 200
        assert popen_calls and "report" in popen_calls[0]
        assert "Investigate" in popen_calls[0]
        assert write_calls

        rescue = await client.post("/api/bootdoctor/action", json={"action": "open_rescue"})
        assert rescue.status == 200
        assert any("rescue" in call for call in popen_calls)

        restart = await client.post("/api/bootdoctor/action", json={"action": "restart"})
        assert restart.status == 200
        assert app[APP_RESTART_REQUESTED] is True
        assert app[APP_SHUTDOWN_EVENT].is_set() is True

        unsupported = await client.post("/api/bootdoctor/action", json={"action": "nope"})
        assert unsupported.status == 400
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_api_bootdoctor_handles_missing_report_and_unavailable_rescue(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "missing-report.txt"
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.boot_recovery",
        SimpleNamespace(
            read_boot_recovery_notice=lambda repo_root, consume=False: {"severity": "fatal", "report_path": str(missing_path)},
            reconcile_boot_doctor_runtime_state=lambda repo_root, port=0: ({"severity": "fatal"}, {"severity": "fatal"}),
            read_boot_doctor_status=lambda repo_root, consume=False: {"severity": "fatal", "report_path": ""},
            clear_boot_recovery_notice=lambda repo_root: None,
            write_boot_doctor_status=lambda repo_root, **kwargs: None,
        ),
    )

    original_exists = Path.exists
    monkeypatch.setattr(
        app_core.Path,
        "exists",
        lambda self: False if str(self).endswith("bootdoctor.ps1") else original_exists(self),
    )
    app = app_core.create_app(_base_config(tmp_path))
    app[app_core.APP_BOOT_DOCTOR_ROOT] = tmp_path
    client = await _start_client(app)
    try:
        report = await client.get("/api/bootdoctor/report")
        assert report.status == 404

        rescue = await client.post("/api/bootdoctor/action", json={"action": "open_rescue"})
        assert rescue.status == 503
    finally:
        await client.close()


def test_create_app_uses_fallback_secret_store_and_rejects_invalid_config(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_core, "SecretStore", _SecretStoreBoom)
    app = app_core.create_app(_base_config(tmp_path))
    assert type(app[APP_SECRETS]).__name__ == "_FallbackSecretStore"

    bad_cfg = _base_config(tmp_path)
    bad_cfg.default_model = "missing"
    monkeypatch.setitem(
        sys.modules,
        "thomas.core.model_resolution",
        SimpleNamespace(resolve_effective_model=lambda config, env_profile="", user_id="", db_path="": ("missing", None)),
    )
    with pytest.raises(ValueError, match="Configuration validation failed"):
        app_core.create_app(bad_cfg)


@pytest.mark.asyncio
async def test_create_app_health_surfaces_optional_subsystem_failures(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_core, "_runtime_guard_refresh", lambda app: (_ for _ in ()).throw(OSError("guard")))
    monkeypatch.setattr(app_core, "TaskLedgerStore", lambda path: (_ for _ in ()).throw(RuntimeError("ledger")))
    run_store_mod = sys.modules["thomas.marketplace.observability.run_store"]
    monkeypatch.setattr(run_store_mod, "init_db", lambda path: (_ for _ in ()).throw(RuntimeError("run-store")))
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.audit_log",
        SimpleNamespace(AuditLog=lambda path, redactor: (_ for _ in ()).throw(RuntimeError("audit"))),
    )
    monkeypatch.setattr(app_core._file_audit, "init_audit", lambda path: (_ for _ in ()).throw(RuntimeError("file-audit")))
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.policy.config",
        SimpleNamespace(load_policy_config=lambda root: (_ for _ in ()).throw(ValueError("guardrails"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.realtime.routes",
        SimpleNamespace(setup_realtime_routes=lambda app, require_api_access=None: (_ for _ in ()).throw(RuntimeError("realtime"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.autonomy",
        SimpleNamespace(install_autonomy=lambda app, config, enabled=False, api_token=None: (_ for _ in ()).throw(ValueError("autonomy"))),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.core.engine_manager",
        SimpleNamespace(get_engine_manager=lambda: (_ for _ in ()).throw(RuntimeError("engines"))),
    )

    app = app_core.create_app(_base_config(tmp_path))
    client = await _start_client(app)
    try:
        response = await client.get("/api/health")
        assert response.status == 200
        payload = await response.json()
        assert payload["status"] == "degraded"
        degraded = set(payload["degraded"])
        assert {"task_ledger", "action_audit", "file_audit", "guardrails", "realtime", "autonomy", "engines"}.issubset(degraded)
        assert payload["security"]["protected_mode"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_audit_routes_and_guardrail_pref_denies_are_wired(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _handle_audit_files(request):
        _ = request
        return (b'{"files":1}', 200, {"Content-Type": "application/json"})

    async def _handle_audit_run_files(request, run_id):
        _ = request
        return (f'{{"run":"{run_id}"}}'.encode("utf-8"), 200, {"Content-Type": "application/json"})

    policy_cfg = SimpleNamespace(
        deny_groups=[],
        redact_additional_patterns=["secret"],
        guardrails=SimpleNamespace(enabled=True, approval_timeout_s=5, no_human_mode="off"),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.routes.audit",
        SimpleNamespace(handle_audit_files=_handle_audit_files, handle_audit_run_files=_handle_audit_run_files),
    )
    monkeypatch.setitem(
        sys.modules,
        "thomas.preferences.store",
        SimpleNamespace(PreferencesStore=_PrefsStoreRestricted, get_db_path=lambda: str(tmp_path / "prefs.sqlite3")),
    )
    monkeypatch.setattr(app_core, "PreferencesStore", _PrefsStoreRestricted)
    monkeypatch.setitem(
        sys.modules,
        "thomas.marketplace.policy.config",
        SimpleNamespace(load_policy_config=lambda root: policy_cfg),
    )
    monkeypatch.setattr(app_core, "_require_api_access", lambda request: None, raising=False)

    app = app_core.create_app(_base_config(tmp_path))
    client = await _start_client(app)
    try:
        files = await client.get("/api/audit/files")
        assert files.status == 200
        assert await files.text() == '{"files":1}'

        run_files = await client.get("/api/audit/runs/run-7/files")
        assert run_files.status == 200
        assert await run_files.text() == '{"run":"run-7"}'
    finally:
        await client.close()

    deny_groups = set(app[APP_GUARDRAILS_CTX]["config"].deny_groups)
    assert {"shell", "network", "browser", "git"}.issubset(deny_groups)


@pytest.mark.asyncio
async def test_create_app_loads_default_config_and_uses_posix_rescue_bootdoctor(
    tmp_path: Path, patch_create_app_dependencies: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _base_config(tmp_path)
    monkeypatch.setattr(app_core, "load_config", lambda: cfg)
    monkeypatch.setitem(
        sys.modules,
        "thomas.server.boot_recovery",
        SimpleNamespace(
            read_boot_recovery_notice=lambda repo_root, consume=False: {"severity": "fatal", "reason": "Need rescue"},
            reconcile_boot_doctor_runtime_state=lambda repo_root, port=0: ({"severity": "fatal"}, {"severity": "fatal"}),
            read_boot_doctor_status=lambda repo_root, consume=False: {"severity": "fatal", "reason": "Need rescue"},
            clear_boot_recovery_notice=lambda repo_root: None,
            write_boot_doctor_status=lambda *args, **kwargs: None,
        ),
    )

    popen_calls: list[list[str]] = []
    monkeypatch.setattr(
        app_core.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(list(args)) or SimpleNamespace(pid=7),
    )

    app = app_core.create_app()
    app[app_core.APP_BOOT_DOCTOR_ROOT] = tmp_path
    monkeypatch.setattr(app_core.os, "name", "posix")
    monkeypatch.setattr(app_core, "Path", type(tmp_path))
    client = await _start_client(app)
    try:
        rescue = await client.post("/api/bootdoctor/action", json={"action": "open_rescue", "reason": "Escalate"})
        assert rescue.status == 200
        assert (await rescue.json())["action"] == "open_rescue"
    finally:
        await client.close()

    assert popen_calls
    assert popen_calls[0][:4] == [sys.executable, "-m", "thomas.bootdoctor", "rescue"]
    assert "--startup-context" in popen_calls[0]
