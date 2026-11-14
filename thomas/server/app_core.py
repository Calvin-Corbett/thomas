"""Core application factory and route/middleware setup."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig, load_config
from thomas.core.event_loop_offload import off_loop
from thomas.core.kernel import late, seams
from thomas.marketplace.observability import file_audit as _file_audit
from thomas.marketplace.observability.task_ledger import TaskLedgerStore, resolve_task_ledger_db_path
from thomas.preferences.store import PreferencesStore
from thomas.server.app_keys import (
    APP_ACTION_AUDIT,
    APP_APPROVALS_BROKER,
    APP_BOOT_DOCTOR_ROOT,
    APP_BOOT_DURATION,
    APP_BOOT_TIME,
    APP_CHAT_AUTOPILOT_LAST_BY_GOAL,
    APP_CHAT_AUTOPILOT_LAST_BY_GOAL_LOCK,
    APP_CONFIG,
    APP_CRASH_COUNT,
    APP_DIAGNOSTICS,
    APP_ENGINE_MANAGER,
    APP_GUARDED_TOOL_RUNNER,
    APP_GUARDRAILS_CTX,
    APP_GUARDRAILS_ENABLED,
    APP_MEMORY,
    APP_REQUIRE_API_ACCESS,
    APP_RESTART_REQUESTED,
    APP_RUN_STORE_ENABLED,
    APP_RUN_STORE_MODULE,
    APP_RUNTIME_GUARD_STATE,
    APP_RUNTIME_GUARD_TASK,
    APP_SECRETS,
    APP_SESSION_ACTIVE_RUNS,
    APP_SESSION_ACTIVE_RUNS_LOCK,
    APP_SESSION_LOCKS,
    APP_SESSION_LOCKS_LOCK,
    APP_SESSIONS,
    APP_SHUTDOWN_EVENT,
    APP_TASK_LEDGER,
    APP_TOOLS,
)
from thomas.server.secrets import SecretStore

from .app_helpers import (
    _build_memory,
    _build_tools,
    _env_flag,
    _FallbackSecretStore,
    _web_dir,
)
from .app_runtime_guard import (
    _runtime_guard_boot_state,
    _runtime_guard_refresh,
)

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)

_BEARER_TOKEN_RE = re.compile(r"^Bearer\s+([^\s]+)\s*$", re.IGNORECASE)

from thomas.agent.loop import AgentLoop

try:
    from thomas.models.capabilities import supports as model_supports
except (ImportError, ModuleNotFoundError, AttributeError, RuntimeError):  # pragma: no cover

    def model_supports(*_args, **_kwargs):
        return False


def _require_api_access(request: Any) -> None:
    """Default access check used by audit routes.

    Reads the closure populated by app_middleware_handlers.setup_middleware_and_handlers
    from request.app[APP_REQUIRE_API_ACCESS]. Tests that need a custom behavior
    monkeypatch this module-level function (`monkeypatch.setattr(app_core,
    "_require_api_access", ...)`); the audit handlers call through this name so
    such patches take effect.
    """
    from aiohttp import web

    closure = request.app.get(APP_REQUIRE_API_ACCESS)
    if closure is None:
        raise web.HTTPInternalServerError(text="server access guard is not configured")
    closure(request)


def _secret_store_root(config: AppConfig) -> Path:
    override = str(os.environ.get("THOMAS_SECRET_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return config.memory.root_path / ".thomas"


def create_app(config: AppConfig | None = None):
    """Create and configure the aiohttp application with all routes and middleware."""
    # Start the clock on the first line of create_app, not partway down it. The
    # reported duration has to cover tool-registry construction and optional-tool
    # registration, because that is where the boot seconds actually go; timing
    # from after that phase described a boot the user never experienced.
    _boot_start = time.time()

    from aiohttp import web

    if config is None:
        config = load_config()
    try:
        from thomas.preferences.model_resolution import resolve_effective_model
        from thomas.preferences.store import get_db_path

        resolved_profile, resolved_model_id = resolve_effective_model(
            config,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
            db_path=get_db_path(),
        )
        if resolved_profile in config.models:
            config.default_model = resolved_profile
            if resolved_model_id:
                config.models[resolved_profile].model = resolved_model_id
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        log.debug("Persisted default-model resolution unavailable: %s", exc)

    # Validate configuration before use
    validation_errors = config.validate()
    if validation_errors:
        raise ValueError("Configuration validation failed:\n" + "\n".join(validation_errors))

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    from .page_response_timing import page_response_timing

    app.middlewares.append(page_response_timing)
    # Freeze the loaded build before the checkout can advance while this process runs.
    try:
        from thomas.core.build_info import build_info

        running_build = build_info().copy()
    except (ImportError, ModuleNotFoundError, OSError, ValueError, TypeError, AttributeError) as exc:
        log.debug("build identity unavailable: %s", exc)
        running_build = {"version": str(THOMAS_VERSION)}
    app[APP_BOOT_DOCTOR_ROOT] = Path(__file__).resolve().parents[2]
    app[APP_CONFIG] = config
    app[APP_TOOLS] = _build_tools(config)
    app[APP_MEMORY] = _build_memory(config)
    try:
        app[APP_SECRETS] = SecretStore(_secret_store_root(config))
    except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as secret_exc:
        log.warning("SecretStore initialization failed: %s", secret_exc)
        app[APP_SECRETS] = _FallbackSecretStore()
    from thomas.server.openai_codex_oauth import bind_server_secret_store

    bind_server_secret_store(app[APP_SECRETS])
    from thomas.core.llm_slot import models as _models_slot
    from thomas.server.model_credentials import embed_credentials

    _undo_credentials = _models_slot().credentials(lambda cfg, name: embed_credentials(cfg, name, app[APP_SECRETS]))

    async def _drop_credentials(_app: Any) -> None:
        _undo_credentials()

    app.on_cleanup.append(_drop_credentials)
    app[APP_CHAT_AUTOPILOT_LAST_BY_GOAL_LOCK] = asyncio.Lock()
    app[APP_SESSIONS] = {}
    app[APP_SESSION_LOCKS] = OrderedDict()
    app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
    app[APP_SESSION_ACTIVE_RUNS] = set()
    app[APP_SESSION_ACTIVE_RUNS_LOCK] = asyncio.Lock()
    app[APP_RUN_STORE_ENABLED] = False
    app[APP_RUN_STORE_MODULE] = None
    app[APP_ACTION_AUDIT] = None
    app[APP_GUARDRAILS_ENABLED] = False
    app[APP_GUARDED_TOOL_RUNNER] = None
    app[APP_TASK_LEDGER] = None
    app[APP_CHAT_AUTOPILOT_LAST_BY_GOAL] = {}
    app[APP_RUNTIME_GUARD_STATE] = _runtime_guard_boot_state(config)
    app[APP_RUNTIME_GUARD_TASK] = None
    try:
        # This refresh stays: it is what populates state["current"] and
        # state["status"], which /api/models reads long before the periodic
        # refresher first fires ~45s later. It no longer re-runs git, though -
        # boot_state just collected that snapshot, so app_runtime_guard reuses it
        # for this one call. See _runtime_guard_refresh.
        _runtime_guard_refresh(app)
    except (OSError, KeyError, ValueError) as runtime_guard_exc:
        log.warning("Runtime guard initialization failed: %s", runtime_guard_exc)

    web_dir = _web_dir()
    chat_store_dir = config.memory.root_path / ".thomas" / "chats"
    chat_store_dir.mkdir(parents=True, exist_ok=True)
    chat_store_lock = asyncio.Lock()

    # Startup diagnostics
    _diagnostics: dict[str, bool] = {}
    _diagnostics["runtime_guard"] = bool(app.get(APP_RUNTIME_GUARD_STATE))

    # Optional: durable per-session task ledger
    try:
        task_ledger_db_path = resolve_task_ledger_db_path(config.memory.root_path)
        app[APP_TASK_LEDGER] = TaskLedgerStore(task_ledger_db_path)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("Task ledger unavailable: %s", e)
        app[APP_TASK_LEDGER] = None
    _diagnostics["task_ledger"] = app.get(APP_TASK_LEDGER) is not None

    # Optional: time-travel run store persistence
    run_store_mod = None
    try:
        from thomas.marketplace.observability import run_store as _run_store_mod

        _run_store_mod.init_db(config.memory.root_path / ".thomas" / "runs.sqlite3")
        run_store_mod = _run_store_mod
        app[APP_RUN_STORE_ENABLED] = True
        app[APP_RUN_STORE_MODULE] = _run_store_mod
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("Run store unavailable (persistence disabled): %s", e)
    _diagnostics["run_store"] = run_store_mod is not None

    # Optional: durable action audit trail
    try:
        from thomas.marketplace.policy.redact import Redactor
        from thomas.server.audit_log import AuditLog

        action_redactor = Redactor()
        app[APP_ACTION_AUDIT] = AuditLog(
            path=(config.memory.root_path / ".thomas" / "audit.sqlite3"),
            redactor=action_redactor,
        )
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("Action audit unavailable: %s", e)
        app[APP_ACTION_AUDIT] = None
    _diagnostics["action_audit"] = app.get(APP_ACTION_AUDIT) is not None

    # Optional: File-change audit log. Its two routes belong to the file_audit row; the store starts here.
    try:
        audit_db_path = config.memory.root_path / ".thomas" / "file_audit.db"
        _file_audit.init_audit(audit_db_path)
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("File audit unavailable: %s", e)
        _diagnostics["file_audit"] = False
    else:
        _diagnostics["file_audit"] = True

    # Optional: Guardrails policy + approval API
    try:
        from thomas.agent.approval import ApprovalBroker
        from thomas.agent.guarded_tools import GuardedToolRunner
        from thomas.marketplace.policy.config import load_policy_config
        from thomas.marketplace.policy.policy import PolicyEngine
        from thomas.marketplace.policy.redact import Redactor
        from thomas.server.guardrails_api import install_guardrails_routes

        policy_cfg = load_policy_config(str(config.memory.root_path))
        if "THOMAS_NO_HUMAN_MODE" not in os.environ and "THOMAS_GUARDRAILS_NO_HUMAN_MODE" not in os.environ:
            os.environ["THOMAS_NO_HUMAN_MODE"] = policy_cfg.guardrails.no_human_mode

        # Wire AdvancedToolsPrefs boolean toggles into policy deny_groups
        try:
            _prefs_store = PreferencesStore(get_db_path())
            _tool_prefs = _prefs_store.get().advanced.tools
            _deny = list(policy_cfg.deny_groups)
            if not _tool_prefs.allow_shell and "shell" not in _deny:
                _deny.append("shell")
            if not _tool_prefs.allow_file_write and "file_write" not in _deny:
                _deny.append("file_write")
            if not _tool_prefs.allow_network and "network" not in _deny:
                _deny.append("network")
            if not _tool_prefs.allow_browser and "browser" not in _deny:
                _deny.append("browser")
            if not _tool_prefs.allow_channels and "channels" not in _deny:
                _deny.append("channels")
            if not _tool_prefs.allow_git and "git" not in _deny:
                _deny.append("git")
            policy_cfg.deny_groups = _deny
        except (AttributeError, KeyError, OSError) as _pe:
            log.debug("Tool prefs -> deny_groups merge skipped: %s", _pe)

        approvals = ApprovalBroker()
        redactor = Redactor(additional_patterns=policy_cfg.redact_additional_patterns)
        audit = app.get(APP_ACTION_AUDIT)

        # Build tool category map
        _tool_cats: dict = {}
        try:
            for t in app.get(APP_TOOLS) or []:
                tname = getattr(t, "name", "") or ""
                tcat = getattr(t, "category", "") or ""
                if tname and tcat:
                    _tool_cats[tname] = tcat
        except (AttributeError, TypeError):
            pass
        policy = PolicyEngine.from_config(policy_cfg, tool_categories=_tool_cats)
        guarded_runner = GuardedToolRunner(
            policy=policy,
            approvals=approvals,
            redactor=redactor,
            audit=audit,
            approval_timeout_s=policy_cfg.guardrails.approval_timeout_s,
            no_human_mode=policy_cfg.guardrails.no_human_mode,
        )
        install_guardrails_routes(app, approvals)
        app[APP_GUARDRAILS_ENABLED] = bool(policy_cfg.guardrails.enabled)
        app[APP_GUARDED_TOOL_RUNNER] = guarded_runner
        app[APP_APPROVALS_BROKER] = approvals
        app[APP_GUARDRAILS_CTX] = {
            "config": policy_cfg,
            "approvals": approvals,
            "redactor": redactor,
            "audit": audit,
            "policy": policy,
        }
        app["approvals"] = approvals
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError, OSError) as e:
        log.warning("Guardrails unavailable: %s", e)
    _diagnostics["guardrails"] = app.get(APP_GUARDRAILS_ENABLED, False)

    # Not optional: without it a raised dial has nowhere to ask, and the server
    # would hold every chat at the level below it with no way out.
    from thomas.server.routes.dial_elevation_routes import setup_dial_elevation_routes

    setup_dial_elevation_routes(app, require_api_access=_require_api_access)

    # Optional: autonomy engine
    _autonomy_ok = False
    try:
        from thomas.marketplace.autonomy import install_autonomy

        autonomy_enabled = _env_flag("THOMAS_AUTONOMY_ENABLED", False)
        autonomy_token = os.environ.get("THOMAS_AUTONOMY_TOKEN")
        # Work execution stages run through the governed delegation path with
        # durable receipts (codex's WorkExecutionAdapter); planning keeps the
        # base adapter. Optional on purpose: without that module the engine
        # installs exactly as before, so this file can land ahead of it.
        work_adapter = None
        try:
            from thomas.marketplace.autonomy.adapters import ChatAdapterConfig
            from thomas.server.work_execution_adapter import WorkExecutionAdapter

            work_adapter = WorkExecutionAdapter(app=app, cfg=ChatAdapterConfig(api_token=autonomy_token))
        except (ImportError, ModuleNotFoundError, TypeError, ValueError) as adapter_error:
            log.info("Work execution adapter not installed: %s", adapter_error)
        install_autonomy(app, config, enabled=autonomy_enabled, api_token=autonomy_token, chat_adapter=work_adapter)
        _autonomy_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError) as e:
        log.warning("Autonomy engine unavailable: %s", e)
    _diagnostics["autonomy"] = _autonomy_ok

    # Background engines: ALL engines via unified EngineManager
    try:
        from thomas.server.aliveness_default import start_engines

        engine_manager, results = start_engines()
        log.info("EngineManager: started all engines - %s", results)
        app[APP_ENGINE_MANAGER] = engine_manager
    except (ImportError, ModuleNotFoundError, RuntimeError, OSError) as e:
        log.warning("Background engines unavailable: %s", e)
    _diagnostics["engines"] = app.get(APP_ENGINE_MANAGER) is not None

    # Store diagnostics + health endpoint
    _diagnostics["memory"] = app[APP_MEMORY] is not None
    app[APP_DIAGNOSTICS] = _diagnostics
    app[APP_BOOT_TIME] = time.time()
    app[APP_BOOT_DURATION] = time.time() - _boot_start
    app[APP_CRASH_COUNT] = 0

    async def api_health(request: web.Request) -> web.Response:
        diag = request.app.get(APP_DIAGNOSTICS, {})
        boot_time = request.app.get(APP_BOOT_TIME, 0)
        degraded = [k for k, v in diag.items() if not v]
        protected_mode = False

        def _protected_mode() -> bool:
            from thomas.preferences.store import PreferencesStore, get_db_path

            mode = PreferencesStore(get_db_path()).get().advanced.security.enforcement_mode
            return str(mode or "").strip().lower() == "protected"

        try:
            # Off the loop: the store opens SQLite and checks its schema, and while the database was busy every request
            # waited behind it for up to its 30 s timeout (freeze dumps, 2026-10-27).
            protected_mode = await off_loop("health.protected_mode", _protected_mode)
        except (AttributeError, ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.debug("Protected-mode preference unavailable: %s", exc)
            protected_mode = False

        # The checkout may have moved since boot; health must describe the code
        # loaded by this process, never a later HEAD observed by a request.
        build = running_build.copy()
        if build.get("commit") and build.get("root"):
            from thomas.core.git_process import run_git
            from thomas.core.head_sha import head_sha

            # Read from .git's own files (a few microseconds, remembered until HEAD moves); asking git cost a
            # process start per health check, 1.4 s each while the machine was busy.
            quick = head_sha(str(build["root"]))
            if quick:
                latest_short = quick[:8]
            else:
                latest = await off_loop(
                    "health.latest_commit",
                    lambda: run_git(
                        ("rev-parse", "--short=8", "HEAD"),
                        cwd=Path(str(build["root"])),
                        timeout=2.0,
                    ),
                )
                latest_short = latest.output() if latest.ok else ""
            if latest_short:
                build["latest_commit"] = latest_short
                # A landing swapped into the running rows is served already (landed_code_reload.APP_LANDED_SWAP_BASE),
                # so the corner says "newer code is available" only past the last swap, not past boot.
                swapped = str(request.app.get("landed_swap_base") or "")
                build["stale"] = latest_short != (swapped[:8] if swapped else build["commit"])
                if swapped:
                    build["swapped_commit"] = swapped[:8]

        # A credential that dies AFTER boot was invisible here: health reported
        # "ok" while every chat turn failed with a 401. Model auth is checked
        # locally (no network call) so a broken sign-in shows up as degraded
        # instead of being rediscovered one failed message at a time.
        auth_health: dict[str, Any] = {"ok": True}
        try:
            from thomas.core.model_auth_health import model_auth_health

            auth_health = model_auth_health(request.app)
        except (ImportError, ModuleNotFoundError, OSError, ValueError, TypeError, KeyError) as exc:
            log.debug("model auth health unavailable: %s", exc)
        if not auth_health.get("ok", True):
            degraded = [*degraded, "model_auth"]
        # The restart the page follows: draining or not, what it waits for, the full-restart notice and the rows a
        # landing swapped in place. On health because every page polls it already and the shell adds no routes.
        from thomas.server import owner_restart

        restart = owner_restart.status(request.app)

        return web.json_response(
            {
                "status": "degraded" if degraded else "ok",
                "version": str(THOMAS_VERSION),
                # The version alone cannot tell two instances apart -- several
                # worktrees here sit on the same version string at once -- so
                # health also names the commit it was built from.
                "build": build,
                "restart": restart,
                "uptime_s": round(time.time() - boot_time, 1) if boot_time else 0,
                "pid": os.getpid(),
                "features": diag,
                "degraded": degraded,
                "model_auth": auth_health,
                "crash_count": request.app.get(APP_CRASH_COUNT, 0),
                "security": {"protected_mode": protected_mode},
            }
        )

    def _bootdoctor_repo_root() -> Path:
        configured = app.get(APP_BOOT_DOCTOR_ROOT)
        try:
            return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.debug("Configured boot-doctor root is invalid: %s", exc)
            return Path(__file__).resolve().parents[2]

    def _bootdoctor_current_port(request: web.Request) -> int:
        try:
            if request.url.port:
                return int(request.url.port)
        except (AttributeError, TypeError, ValueError) as exc:
            log.debug("Request URL did not expose a usable port: %s", exc)
        try:
            return int(getattr(config.server, "port", 8899) or 8899)
        except (AttributeError, TypeError, ValueError) as exc:
            log.debug("Configured server port is invalid: %s", exc)
            return 8899

    def _bootdoctor_default_actions(severity_raw: str, *, report_available: bool) -> list[str]:
        severity = str(severity_raw or "").strip().lower()
        actions: list[str] = []
        if report_available:
            actions.append("view_report")
        actions.append("retry_repair")
        if severity != "fatal":
            actions.extend(["restart", "dismiss_notice"])
        actions.append("open_rescue")
        deduped: list[str] = []
        for action in actions:
            if action not in deduped:
                deduped.append(action)
        return deduped

    def _bootdoctor_spawn_report(*, repo_root: Path, reason: str, port: int) -> subprocess.Popen[str]:
        runtime_dir = repo_root / "runtime" / "boot_doctor"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log_path = runtime_dir / "server_action_bootdoctor.log"
        log_handle = log_path.open("a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "thomas.bootdoctor",
                "report",
                "--force",
                "--port",
                str(int(port)),
                "--reason",
                reason,
                "--relaunch",
            ],
            cwd=str(repo_root),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )

    def _bootdoctor_spawn_rescue(
        *, repo_root: Path, reason: str, port: int, status_payload: dict[str, Any] | None = None
    ) -> subprocess.Popen[str] | None:
        runtime_dir = repo_root / "runtime" / "boot_doctor"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        context_path = runtime_dir / f"startup_context_{stamp}.json"
        payload = {
            "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "reason": reason,
            "attempted_launch_mode": "web",
            "target_port": int(port),
            "current_health_status": str((status_payload or {}).get("severity") or "fatal"),
            "ever_healthy_during_boot": False,
            "stderr_tail": "",
            "startup_log_paths": [],
        }
        context_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if os.name == "nt":
            bootdoctor_script = repo_root / "scripts" / "bootdoctor.ps1"
            if not bootdoctor_script.exists():
                return None
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            return subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(bootdoctor_script),
                    "rescue",
                    "--force",
                    "--port",
                    str(int(port)),
                    "--reason",
                    reason,
                    "--startup-context",
                    str(context_path),
                    "--relaunch",
                ],
                cwd=str(repo_root),
                creationflags=creationflags,
                text=True,
            )
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "thomas.bootdoctor",
                "rescue",
                "--force",
                "--port",
                str(int(port)),
                "--reason",
                reason,
                "--startup-context",
                str(context_path),
                "--relaunch",
            ],
            cwd=str(repo_root),
            text=True,
        )

    async def api_bootdoctor_recovery_notice(request: web.Request) -> web.Response:
        from thomas.server.boot_recovery import read_boot_recovery_notice

        consume = str(request.query.get("consume", "")).strip().lower() in {"1", "true", "yes"}
        notice = read_boot_recovery_notice(_bootdoctor_repo_root(), consume=consume)
        return web.json_response({"notice": notice})

    async def api_bootdoctor_status(request: web.Request) -> web.Response:
        from thomas.server.boot_recovery import reconcile_boot_doctor_runtime_state

        # Note: This function is defined before middleware setup, so we can't use _require_loopback directly
        # We'll use a placeholder that will be defined in middleware setup
        repo_root = _bootdoctor_repo_root()
        status_payload, notice_payload = reconcile_boot_doctor_runtime_state(
            repo_root,
            port=_bootdoctor_current_port(request),
        )
        return web.json_response({"status": status_payload, "notice": notice_payload})

    async def api_bootdoctor_report(request: web.Request) -> web.Response:
        from thomas.server.boot_recovery import read_boot_doctor_status, read_boot_recovery_notice

        repo_root = _bootdoctor_repo_root()
        status_payload = read_boot_doctor_status(repo_root, consume=False) or {}
        notice_payload = read_boot_recovery_notice(repo_root, consume=False) or {}
        report_path_raw = str(status_payload.get("report_path") or notice_payload.get("report_path") or "").strip()
        if not report_path_raw:
            raise web.HTTPNotFound(text="bootdoctor report unavailable")
        report_path = Path(report_path_raw)
        if not report_path.exists():
            raise web.HTTPNotFound(text="bootdoctor report missing")
        text_body = report_path.read_text(encoding="utf-8", errors="replace")
        return web.Response(text=text_body, content_type="text/plain", headers={"Cache-Control": "no-store"})

    async def api_bootdoctor_action(request: web.Request) -> web.Response:
        from thomas.server.boot_recovery import (
            clear_boot_recovery_notice,
            read_boot_doctor_status,
            read_boot_recovery_notice,
            write_boot_doctor_status,
        )

        try:
            payload = await request.json()
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            log.debug("Boot-doctor action body is not valid JSON: %s", exc)
            payload = {}
        action = str((payload or {}).get("action") or "").strip().lower()
        if action not in {"retry_repair", "restart", "open_rescue", "dismiss_notice"}:
            raise web.HTTPBadRequest(text="unsupported bootdoctor action")

        repo_root = _bootdoctor_repo_root()
        status_payload = read_boot_doctor_status(repo_root, consume=False) or {}
        notice_payload = read_boot_recovery_notice(repo_root, consume=False) or {}
        (
            str(status_payload.get("severity") or notice_payload.get("severity") or "degraded").strip().lower()
            or "degraded"
        )
        reason = str(
            (payload or {}).get("reason")
            or status_payload.get("reason")
            or notice_payload.get("reason")
            or "Startup issue detected from Thomas web UI."
        ).strip()
        port = _bootdoctor_current_port(request)

        if action == "dismiss_notice":
            clear_boot_recovery_notice(repo_root)
            return web.json_response({"ok": True, "action": action, "message": "Recovery notice dismissed."})

        if action == "restart":
            app[APP_RESTART_REQUESTED] = True
            shutdown_event = app.get(APP_SHUTDOWN_EVENT)
            if shutdown_event:
                shutdown_event.set()
            return web.json_response({"ok": True, "action": action, "message": "Thomas restart requested."})

        if action == "retry_repair":
            report_hint = str(status_payload.get("report_path") or notice_payload.get("report_path") or "").strip()
            write_boot_doctor_status(
                repo_root,
                status="degraded",
                phase="repairing",
                message="Boot Doctor is investigating the degraded startup issue.",
                reason=reason,
                port=int(port),
                severity="degraded",
                recovered=True,
                blocking=False,
                report_path=report_hint or None,
                repairs=list(status_payload.get("repairs") or notice_payload.get("repairs") or []),
                ai_summary=str(status_payload.get("ai_summary") or notice_payload.get("ai_summary") or ""),
                recommended_actions=_bootdoctor_default_actions("degraded", report_available=bool(report_hint)),
                probe_results=list(status_payload.get("probe_results") or notice_payload.get("probe_results") or []),
            )
            _bootdoctor_spawn_report(repo_root=repo_root, reason=reason, port=int(port))
            return web.json_response({"ok": True, "action": action, "message": "Boot Doctor repair started."})

        proc = _bootdoctor_spawn_rescue(
            repo_root=repo_root, reason=reason, port=int(port), status_payload=status_payload or notice_payload
        )
        if proc is None:
            raise web.HTTPServiceUnavailable(text="advanced rescue unavailable")
        return web.json_response({"ok": True, "action": action, "message": "Advanced rescue opened."})

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/healthz", api_health)
    app.router.add_get("/api/bootdoctor/recovery_notice", api_bootdoctor_recovery_notice)
    app.router.add_get("/api/bootdoctor/status", api_bootdoctor_status)
    app.router.add_get("/api/bootdoctor/report", api_bootdoctor_report)
    app.router.add_post("/api/bootdoctor/action", api_bootdoctor_action)

    # Register health readiness check
    from thomas.server.routes.health import register_health_ready_route

    register_health_ready_route(app)

    # Setup middleware and handlers
    from .app_middleware_handlers import setup_middleware_and_handlers

    setup_middleware_and_handlers(app, config, web_dir, chat_store_dir, chat_store_lock)

    from thomas.server import chat_offers, self_project_queue_tick  # noqa: F401 -- each provides calls by name

    late.require(seams.CALLS)
    return app
