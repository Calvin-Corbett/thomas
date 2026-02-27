"""Thomas HTTP server and lightweight web UI.

This server is intentionally simple:
- Serves static UI from thomas/server/web/
- Exposes a small JSON/NDJSON API for chat + model listing

Install:
  pip install -e ".[server]"

Run:
  thomas serve --port 8899
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import inspect
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from collections import OrderedDict, deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig, load_config
from thomas.models.discovery import handshake_models_async
from thomas.models.switching import infer_profile_candidates, is_model_switch_request, resolve_model_switch_request
from thomas.observability import file_audit as _file_audit
from thomas.observability.task_ledger import (
    TaskLedgerStore,
    resolve_task_ledger_db_path,
)
from thomas.preferences.store import PreferencesStore, get_db_path
from thomas.server.app_keys import (
    APP_ACTION_AUDIT,
    APP_BOOT_DURATION,
    APP_BOOT_TIME,
    APP_CHAT_AUTOPILOT_LAST_BY_GOAL,
    APP_CODEX_BRIDGE,
    APP_CONFIG,
    APP_CRASH_COUNT,
    APP_DIAGNOSTICS,
    APP_ENGINE_MANAGER,
    APP_GUARDED_TOOL_RUNNER,
    APP_GUARDRAILS_CTX,
    APP_GUARDRAILS_ENABLED,
    APP_MEMORY,
    APP_MUTATING_ROUTE_POLICY_SNAPSHOT,
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
from thomas.server.tool_extensions import register_all_optional_tools
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools

log = logging.getLogger(__name__)

try:
    from thomas.memory.autonomy import AutonomyMemoryEngine
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    AutonomyMemoryEngine = None  # type: ignore[assignment]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _appkey_identity(key: Any) -> str:
    rep = repr(key)
    match = re.match(r"^<AppKey\(([^,]+),\s*type=.*\)>$", rep)
    if match:
        name = str(match.group(1) or "")
        marker = "thomas.server.app_keys."
        idx = name.find(marker)
        if idx >= 0:
            return name[idx:]
        return name
    return str(key)


def _resolve_app_value(
    app: web.Application,
    key: Any,
    *,
    expected_type: Any = None,
    default: Any = None,
    required: bool = False,
) -> Any:
    value = app.get(key)
    if expected_type is None:
        if value is not None:
            return value
    elif isinstance(value, expected_type):
        return value

    target_identity = _appkey_identity(key)
    for existing_key, existing_value in app.items():
        if _appkey_identity(existing_key) != target_identity:
            continue
        if expected_type is not None and not isinstance(existing_value, expected_type):
            continue
        app[key] = existing_value
        return existing_value

    if required:
        raise KeyError(key)
    return default


def _resolve_runtime_config(app: web.Application) -> AppConfig:
    cfg = _resolve_app_value(app, APP_CONFIG, expected_type=AppConfig)
    if isinstance(cfg, AppConfig):
        return cfg
    for value in app.values():
        if isinstance(value, AppConfig):
            app[APP_CONFIG] = value
            return value
    cfg = load_config()
    app[APP_CONFIG] = cfg
    return cfg


# ── chat autopilot helpers, swarm subagent, etc. extracted → routes/chat_aiohttp.py ──


def _runtime_guard_iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _runtime_guard_run_git(repo_root: Path, *args: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        return False, err or f"exit {result.returncode}"
    return True, (result.stdout or "").strip()


def _runtime_guard_find_repo_root() -> Path | None:
    candidates = [Path.cwd(), Path(__file__).resolve().parents[2]]
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.resolve())
        if marker in seen:
            continue
        seen.add(marker)
        ok, out = _runtime_guard_run_git(candidate, "rev-parse", "--show-toplevel")
        if not ok:
            continue
        try:
            repo_root = Path(out.strip()).resolve()
        except (OSError, ValueError):
            continue
        if repo_root.exists():
            return repo_root
    return None


def _runtime_guard_read_lock_info(config: AppConfig) -> dict[str, Any]:
    lock_file = Path(config.memory.root_path) / ".thomas" / "serve.lock"
    if not lock_file.exists():
        return {"exists": False, "path": str(lock_file)}
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
        payload = dict(payload)
        payload["exists"] = True
        payload["path"] = str(lock_file)
        return payload
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "exists": True,
            "path": str(lock_file),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _runtime_guard_collect_source_snapshot(repo_root: Path | None) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "repo_available": False,
        "repo_root": "",
        "git_head": "",
        "tracked_worktree_digest": "",
        "tracked_change_count": 0,
        "tracked_worktree_dirty": False,
        "errors": [],
    }
    if repo_root is None:
        return snapshot

    snapshot["repo_available"] = True
    snapshot["repo_root"] = str(repo_root)

    ok_head, head_out = _runtime_guard_run_git(repo_root, "rev-parse", "HEAD")
    if ok_head:
        snapshot["git_head"] = head_out
    else:
        snapshot["errors"].append(f"git_head: {head_out}")

    ok_status, status_out = _runtime_guard_run_git(
        repo_root,
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    if ok_status:
        rows = [row.rstrip() for row in status_out.splitlines() if row.strip()]
        normalized = "\n".join(rows)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""
        snapshot["tracked_worktree_digest"] = digest
        snapshot["tracked_change_count"] = len(rows)
        snapshot["tracked_worktree_dirty"] = bool(rows)
    else:
        snapshot["errors"].append(f"git_status: {status_out}")

    return snapshot


def _runtime_guard_boot_state(config: AppConfig) -> dict[str, Any]:
    try:
        interval_s = float(os.environ.get("THOMAS_RUNTIME_GUARD_INTERVAL_S", "45"))
    except (ValueError, TypeError):
        interval_s = 45.0
    interval_s = max(10.0, min(300.0, interval_s))

    repo_root = _runtime_guard_find_repo_root()
    source_snapshot = _runtime_guard_collect_source_snapshot(repo_root)
    lock_snapshot = _runtime_guard_read_lock_info(config)

    return {
        "enabled": True,
        "check_interval_s": interval_s,
        "boot": {
            "pid": os.getpid(),
            "version": THOMAS_VERSION,
            "booted_at_utc": _runtime_guard_iso_now(),
            "source": source_snapshot,
            "lock": lock_snapshot,
        },
        "status": {
            "checked_at_utc": "",
            "is_latest_code": True,
            "state": "ok",
            "reasons": [],
            "alert_message": "",
        },
        "current": {},
    }


def _runtime_guard_refresh(app: web.Application) -> dict[str, Any]:
    cfg = _resolve_runtime_config(app)
    state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, required=True)
    boot = dict(state.get("boot") or {})

    boot_source = dict(boot.get("source") or {})
    repo_root_raw = str(boot_source.get("repo_root") or "").strip()
    repo_root = Path(repo_root_raw) if repo_root_raw else None
    source_snapshot = _runtime_guard_collect_source_snapshot(repo_root)
    lock_snapshot = _runtime_guard_read_lock_info(cfg)

    reasons: list[str] = []
    lock_pid = lock_snapshot.get("pid")
    try:
        lock_pid_int = int(lock_pid)
    except (ValueError, TypeError):
        lock_pid_int = None
    if lock_pid_int is None:
        reasons.append("serve_lock_missing_or_invalid")
    elif lock_pid_int != os.getpid():
        reasons.append("serve_lock_points_to_other_pid")

    boot_head = str(boot_source.get("git_head") or "")
    current_head = str(source_snapshot.get("git_head") or "")
    if boot_head and current_head and boot_head != current_head:
        reasons.append("git_head_changed_since_boot")

    boot_digest = str(boot_source.get("tracked_worktree_digest") or "")
    current_digest = str(source_snapshot.get("tracked_worktree_digest") or "")
    if boot_digest != current_digest:
        reasons.append("tracked_worktree_changed_since_boot")

    stale = len(reasons) > 0
    if stale:
        if "serve_lock_points_to_other_pid" in reasons:
            alert_message = (
                "Not on the newest Thomas server process. " "Please restart Thomas so this tab uses the latest runtime."
            )
        else:
            alert_message = "Code changed after this Thomas server booted. " "Restart Thomas to run the newest version."
    else:
        alert_message = ""

    current = {
        "pid": os.getpid(),
        "source": source_snapshot,
        "lock": lock_snapshot,
    }
    status = {
        "checked_at_utc": _runtime_guard_iso_now(),
        "is_latest_code": not stale,
        "state": "ok" if not stale else "stale",
        "reasons": reasons,
        "alert_message": alert_message,
    }
    state["current"] = current
    state["status"] = status
    return status


async def _runtime_guard_loop(app: web.Application) -> None:
    while True:
        try:
            _runtime_guard_refresh(app)
        except asyncio.CancelledError:
            raise
        except (OSError, KeyError, ValueError) as exc:
            log.warning("Runtime guard check failed: %s", exc)
        state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, default={})
        interval_s = float(state.get("check_interval_s") or 45.0)
        await asyncio.sleep(max(10.0, interval_s))


def _build_tools(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    register_ssh_tools(registry)

    # Investigation tools -- registered only if investigation DB has cases
    try:
        from thomas.tools.investigation import register_investigation_tools

        register_investigation_tools(registry)
    except (ImportError, ModuleNotFoundError, OSError):
        pass

    # Register all optional domain module tools
    register_all_optional_tools(registry)

    return registry


def _build_memory(config: AppConfig):
    if AutonomyMemoryEngine is None:
        return None
    try:
        engine = AutonomyMemoryEngine(
            config,
            enable_v2=_env_flag("THOMAS_MEMORY_V2_ENABLED", True),
            enable_legacy=True,
        )
        engine.start()
        return engine
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("Memory engine failed to start: %s", e)
        return None


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def create_app(config: AppConfig | None = None):
    from aiohttp import web

    if config is None:
        config = load_config()

    # Validate configuration before use
    validation_errors = config.validate()
    if validation_errors:
        raise ValueError("Configuration validation failed:\n" + "\n".join(validation_errors))

    # AppKey constants imported from thomas.server.app_keys

    app = web.Application(client_max_size=25 * 1024 * 1024)  # 25 MB
    app[APP_CONFIG] = config
    app[APP_TOOLS] = _build_tools(config)
    app[APP_MEMORY] = _build_memory(config)
    app[APP_SECRETS] = SecretStore(config.memory.root_path / ".thomas")
    app[APP_SESSIONS] = {}
    app[APP_SESSION_LOCKS] = OrderedDict()  # LRU-evicted in _session_lock_for
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
        _runtime_guard_refresh(app)
    except (OSError, KeyError, ValueError) as runtime_guard_exc:
        log.warning("Runtime guard initialization failed: %s", runtime_guard_exc)

    web_dir = _web_dir()
    chat_store_dir = config.memory.root_path / ".thomas" / "chats"
    chat_store_dir.mkdir(parents=True, exist_ok=True)
    chat_store_lock = asyncio.Lock()

    # ── Startup diagnostics: track which features loaded vs failed ──
    _diagnostics: dict[str, bool] = {}
    _boot_start = time.time()
    _diagnostics["runtime_guard"] = bool(app.get(APP_RUNTIME_GUARD_STATE))

    # Optional: durable per-session task ledger.
    try:
        task_ledger_db_path = resolve_task_ledger_db_path(config.memory.root_path)
        app[APP_TASK_LEDGER] = TaskLedgerStore(task_ledger_db_path)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("Task ledger unavailable: %s", e)
        app[APP_TASK_LEDGER] = None
    _diagnostics["task_ledger"] = app.get(APP_TASK_LEDGER) is not None

    # Optional: time-travel run store persistence + endpoints.
    # Keep persistence enabled even if HTTP replay routes fail to register.
    run_store_mod = None
    try:
        from thomas.observability import run_store as _run_store_mod

        _run_store_mod.init_db(config.memory.root_path / ".thomas" / "runs.sqlite3")
        run_store_mod = _run_store_mod
        app[APP_RUN_STORE_ENABLED] = True
        app[APP_RUN_STORE_MODULE] = _run_store_mod
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("Run store unavailable (persistence disabled): %s", e)
    _diagnostics["run_store"] = run_store_mod is not None

    if run_store_mod is not None:
        try:
            from thomas.server.routes.runs import register_runs_routes

            register_runs_routes(app, config)
        except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
            log.warning("Run store routes unavailable (persistence still enabled): %s", e)

    # Optional: durable action audit trail (tool action lifecycle).
    try:
        from thomas.policy.redact import Redactor
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

    # Optional: File-change audit log
    try:
        from thomas.server.routes.audit import handle_audit_files, handle_audit_run_files

        audit_db_path = config.memory.root_path / ".thomas" / "file_audit.db"
        _file_audit.init_audit(audit_db_path)

        async def _audit_files_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            body, status, headers = await handle_audit_files(request)
            return web.Response(body=body, status=status, headers=headers)

        async def _audit_run_files_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            run_id = request.match_info.get("run_id", "")
            body, status, headers = await handle_audit_run_files(request, run_id)
            return web.Response(body=body, status=status, headers=headers)

        app.router.add_get("/api/audit/files", _audit_files_handler)
        app.router.add_get("/api/audit/runs/{run_id}/files", _audit_run_files_handler)
        log.info("File audit routes registered")
    except (ImportError, ModuleNotFoundError, OSError, RuntimeError) as e:
        log.warning("File audit routes unavailable: %s", e)
        _diagnostics["file_audit"] = False
    else:
        _diagnostics["file_audit"] = True

    # Optional: Guardrails policy + approval API
    try:
        from thomas.agent.approval import ApprovalBroker
        from thomas.agent.guarded_tools import GuardedToolRunner
        from thomas.policy.config import load_policy_config
        from thomas.policy.policy import PolicyEngine
        from thomas.policy.redact import Redactor
        from thomas.server.guardrails_api import install_guardrails_routes

        policy_cfg = load_policy_config(str(config.memory.root_path))

        # Wire AdvancedToolsPrefs boolean toggles into policy deny_groups.
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

        # Build tool category map from registry for group deny fallback matching.
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
        )
        install_guardrails_routes(app, approvals)
        app[APP_GUARDRAILS_ENABLED] = bool(policy_cfg.guardrails.enabled)
        app[APP_GUARDED_TOOL_RUNNER] = guarded_runner
        app[APP_GUARDRAILS_CTX] = {
            "config": policy_cfg,
            "approvals": approvals,
            "redactor": redactor,
            "audit": audit,
            "policy": policy,
        }
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError, OSError) as e:
        log.warning("Guardrails unavailable: %s", e)
    _diagnostics["guardrails"] = app.get(APP_GUARDRAILS_ENABLED, False)

    # Optional: realtime routes
    _realtime_ok = False
    try:
        from thomas.realtime.routes import setup_realtime_routes

        setup_realtime_routes(app, require_api_access=lambda req: _require_api_access(req))
        _realtime_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, KeyError) as e:
        log.warning("Realtime routes unavailable: %s", e)
    _diagnostics["realtime"] = _realtime_ok

    # Optional: autonomy engine
    _autonomy_ok = False
    try:
        from thomas.autonomy import install_autonomy

        autonomy_enabled = _env_flag("THOMAS_AUTONOMY_ENABLED", False)
        autonomy_token = os.environ.get("THOMAS_AUTONOMY_TOKEN")
        install_autonomy(app, config, enabled=autonomy_enabled, api_token=autonomy_token)
        _autonomy_ok = True
    except (ImportError, ModuleNotFoundError, RuntimeError, ValueError) as e:
        log.warning("Autonomy engine unavailable: %s", e)
    _diagnostics["autonomy"] = _autonomy_ok

    # Background engines: ALL engines via unified EngineManager
    # One call starts: persistence, tool_factory, initiative, testing_suite
    try:
        from thomas.core.engine_manager import get_engine_manager

        engine_manager = get_engine_manager()
        results = engine_manager.start_all()
        log.info("EngineManager: started all engines - %s", results)

        # Store reference for status endpoint
        app[APP_ENGINE_MANAGER] = engine_manager

    except (ImportError, ModuleNotFoundError, RuntimeError, OSError) as e:
        log.warning("Background engines unavailable: %s", e)
    _diagnostics["engines"] = app.get(APP_ENGINE_MANAGER) is not None

    # Optional: swarm cancellation endpoint
    try:
        from thomas.server.swarm_mode import handle_cancel as swarm_cancel_handler

        async def _swarm_cancel_handler(request: web.Request) -> web.Response:
            _require_api_access(request)
            return await swarm_cancel_handler(request)

        app.router.add_post("/api/runs/{run_id}/cancel", _swarm_cancel_handler)
    except (ImportError, ModuleNotFoundError, RuntimeError) as e:
        log.warning("Swarm cancel endpoint unavailable: %s", e)

    # ── Store diagnostics + health endpoint ──
    _diagnostics["memory"] = app[APP_MEMORY] is not None
    app[APP_DIAGNOSTICS] = _diagnostics
    app[APP_BOOT_TIME] = time.time()
    app[APP_BOOT_DURATION] = time.time() - _boot_start
    app[APP_CRASH_COUNT] = 0  # updated by supervisor if applicable

    async def api_health(request: web.Request) -> web.Response:
        diag = request.app.get(APP_DIAGNOSTICS, {})
        boot_time = request.app.get(APP_BOOT_TIME, 0)
        degraded = [k for k, v in diag.items() if not v]
        return web.json_response(
            {
                "status": "degraded" if degraded else "ok",
                "version": str(THOMAS_VERSION),
                "uptime_s": round(time.time() - boot_time, 1) if boot_time else 0,
                "pid": os.getpid(),
                "features": diag,
                "degraded": degraded,
                "crash_count": request.app.get(APP_CRASH_COUNT, 0),
            }
        )

    app.router.add_get("/api/health", api_health)
    app.router.add_get("/healthz", api_health)

    # Register health readiness check
    from thomas.server.routes.health import register_health_ready_route

    register_health_ready_route(app)

    _security_headers_enabled = _env_flag("THOMAS_SECURITY_HEADERS_ENABLED", True)
    _frame_options = str(os.environ.get("THOMAS_FRAME_OPTIONS", "SAMEORIGIN") or "").strip()
    _security_headers: dict[str, str] = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' blob: https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' https://cdn.jsdelivr.net https://unpkg.com; "
            "connect-src 'self'"
        ),
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
        "X-Permitted-Cross-Domain-Policies": "none",
    }
    if _frame_options:
        _security_headers["X-Frame-Options"] = _frame_options

    # ── Global exception logger ─────────────────────────────────────
    # Must be the FIRST middleware so it wraps everything.  Logs the
    # full traceback for any unhandled exception that would otherwise
    # surface as aiohttp's generic "500 Server got itself in trouble".
    @web.middleware
    async def exception_logger(request: web.Request, handler):  # type: ignore[no-untyped-def]
        try:
            return await handler(request)
        except web.HTTPException:
            raise  # normal HTTP errors (4xx, redirects, etc.) -- pass through
        except asyncio.CancelledError:
            raise  # don't suppress cancellation
        except Exception:  # REVIEWED: broad catch — last-resort error boundary
            log.exception("[thomas] Unhandled exception on %s %s", request.method, request.path)
            raise

    app.middlewares.append(exception_logger)

    @web.middleware
    async def security_headers(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        if _security_headers_enabled and not bool(getattr(resp, "prepared", False)):
            for header_name, header_value in _security_headers.items():
                resp.headers.setdefault(header_name, header_value)
        return resp

    app.middlewares.append(security_headers)

    @web.middleware
    async def no_cache_ui_assets(request: web.Request, handler):  # type: ignore[no-untyped-def]
        resp = await handler(request)
        cfg = _resolve_runtime_config(app)
        is_prod = bool(getattr(cfg, "is_production", False))

        if request.method == "GET":
            if request.path in {"/", "/mission", "/settings", "/companion"}:
                resp.headers.setdefault("Cache-Control", "no-store")
                resp.headers.setdefault("Pragma", "no-cache")
                resp.headers.setdefault("Expires", "0")
            elif request.path.startswith("/static/"):
                if is_prod:
                    resp.headers.setdefault(
                        "Cache-Control",
                        "public, max-age=31536000, immutable",
                    )
                else:
                    resp.headers.setdefault("Cache-Control", "no-store")
                    resp.headers.setdefault("Pragma", "no-cache")
                    resp.headers.setdefault("Expires", "0")
        return resp

    app.middlewares.append(no_cache_ui_assets)

    def _is_loopback_request(request: web.Request) -> bool:
        remote = request.remote or ""
        try:
            ip = ipaddress.ip_address(remote)
            return ip.is_loopback
        except ValueError:
            return False

    def _extract_request_token(request: web.Request) -> str:
        auth = str(request.headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return str(request.headers.get("X-Api-Token") or "").strip()

    rate_limit_state: dict[str, deque[float]] = {}
    rate_limit_lock = asyncio.Lock()
    rate_limit_gc_at = 0.0

    def _parse_server_int(raw: Any, default: int, minimum: int = 1) -> int:
        try:
            val = int(raw)
        except (ValueError, TypeError):
            val = default
        return max(minimum, val)

    def _remote_rate_limit_key(request: web.Request) -> str:
        token = _extract_request_token(request)
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
            return f"token:{digest}"
        remote = str(request.remote or "").strip() or "unknown"
        return f"ip:{remote}"

    async def _consume_remote_rate_limit(request: web.Request) -> tuple[bool, int]:
        """Best-effort fixed-window limiter for remote-mode API traffic."""
        nonlocal rate_limit_gc_at
        cfg: AppConfig = _resolve_runtime_config(app)
        srv = getattr(cfg, "server", None)
        max_requests = _parse_server_int(getattr(srv, "rate_limit_max_requests", 120), 120)
        window_s = _parse_server_int(getattr(srv, "rate_limit_window_seconds", 60), 60)

        key = _remote_rate_limit_key(request)
        now = time.monotonic()
        cutoff = now - float(window_s)

        async with rate_limit_lock:
            bucket = rate_limit_state.get(key)
            if bucket is None:
                bucket = deque()
                rate_limit_state[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= max_requests:
                oldest = bucket[0] if bucket else now
                retry_after = max(1, int(math.ceil(float(window_s) - (now - oldest))))
                return False, retry_after

            bucket.append(now)

            # Opportunistic cleanup to keep state bounded.
            gc_interval = min(max(float(window_s), 5.0), 60.0)
            if (now - rate_limit_gc_at) >= gc_interval:
                stale_before = now - float(window_s)
                stale_keys = [k for k, b in rate_limit_state.items() if (not b) or b[-1] <= stale_before]
                for stale_key in stale_keys:
                    rate_limit_state.pop(stale_key, None)
                rate_limit_gc_at = now

        return True, 0

    @web.middleware
    async def remote_api_rate_limit(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if request.path.startswith("/api/"):
            cfg: AppConfig = _resolve_runtime_config(app)
            srv = getattr(cfg, "server", None)
            mode = str(getattr(srv, "access_mode", "local") or "local").strip().lower()
            enabled = bool(getattr(srv, "rate_limit_enabled", True))
            if mode == "remote" and enabled:
                allowed, retry_after = await _consume_remote_rate_limit(request)
                if not allowed:
                    raise web.HTTPTooManyRequests(
                        text="remote api rate limit exceeded",
                        headers={"Retry-After": str(retry_after)},
                    )
        return await handler(request)

    app.middlewares.append(remote_api_rate_limit)

    # Token bucket rate limiter (configurable via config)
    from thomas.server.middleware.rate_limit import RateLimitStore, create_rate_limit_middleware

    cfg: AppConfig = _resolve_runtime_config(app)
    srv = getattr(cfg, "server", None)
    rate_limit_window = _parse_server_int(getattr(srv, "rate_limit_window_seconds", 60), 60)
    rate_limit_chat = _parse_server_int(getattr(srv, "rate_limit_max_requests", 120), 120)
    # Default: half the general limit for chat endpoints
    rate_limit_chat_default = max(1, rate_limit_chat // 2)

    rate_limit_store = RateLimitStore(window_seconds=rate_limit_window)
    rate_limit_middleware = create_rate_limit_middleware(
        rate_limit_store,
        chat_limit=rate_limit_chat_default,
        general_limit=rate_limit_chat,
        window_seconds=rate_limit_window,
        skip_loopback=True,
    )
    app.middlewares.append(rate_limit_middleware)

    def _require_api_token(request: web.Request) -> None:
        cfg: AppConfig = _resolve_runtime_config(app)
        expected = str(getattr(getattr(cfg, "server", None), "api_token", "") or "").strip()
        if not expected:
            raise web.HTTPUnauthorized(text="server api token is not configured")
        incoming = _extract_request_token(request)
        if not incoming:
            raise web.HTTPUnauthorized(text="missing api token")
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(text="invalid api token")

    def _require_loopback(request: web.Request) -> None:
        if not _is_loopback_request(request):
            raise web.HTTPForbidden(text="This endpoint is only available from localhost.")
        _require_same_origin_browser_request(request)

    def _require_api_access(request: web.Request) -> None:
        cfg: AppConfig = _resolve_runtime_config(app)
        mode = str(getattr(getattr(cfg, "server", None), "access_mode", "local") or "local").strip().lower()
        if mode == "remote":
            _require_api_token(request)
            return
        _require_loopback(request)

    def _is_mutating_control_plane_route(request: web.Request) -> bool:
        method = str(request.method or "").upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = str(request.path or "")
        if path.startswith("/webhooks/receive/"):
            return False
        return path.startswith("/api/") or path.startswith("/gateway/") or path.startswith("/v1/") or path == "/probe"

    def _is_local_browser_origin_host(host: str) -> bool:
        token = str(host or "").strip().lower()
        if not token:
            return False
        if _is_loopback_host(token):
            return True
        # Android/Genymotion emulator aliases that map back to host loopback.
        return token in {"10.0.2.2", "10.0.3.2"}

    def _require_csrf_guard(request: web.Request) -> None:
        raw_token = str(os.environ.get("THOMAS_MUTATING_CSRF_TOKEN", "") or "").strip()
        if not raw_token:
            return

        provided = str(request.headers.get("X-CSRF-Token") or "").strip()
        if not provided:
            raise web.HTTPForbidden(text="Missing X-CSRF-Token for this mutating request.")
        if not hmac.compare_digest(provided.encode("utf-8"), raw_token.encode("utf-8")):
            raise web.HTTPForbidden(text="Invalid X-CSRF-Token for this request.")

    @web.middleware
    async def csrf_guard_mutating_api(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if _is_mutating_control_plane_route(request):
            _require_csrf_guard(request)
        return await handler(request)

    app.middlewares.append(csrf_guard_mutating_api)

    @web.middleware
    async def authz_guard_mutating_api(request: web.Request, handler):  # type: ignore[no-untyped-def]
        if _is_mutating_control_plane_route(request):
            _require_api_access(request)
        return await handler(request)

    app.middlewares.append(authz_guard_mutating_api)

    def _require_same_origin_browser_request(request: web.Request) -> None:
        """Reject cross-origin browser requests to localhost-only endpoints.

        Browser-based CSRF attempts to localhost services include Origin and/or
        Sec-Fetch-Site headers; reject anything not same-origin.
        """
        fetch_site = str(request.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if fetch_site and fetch_site not in {"same-origin", "none"}:
            raise web.HTTPForbidden(text="Cross-site browser requests are not allowed.")

        raw_origin = str(request.headers.get("Origin") or "").strip()
        if not raw_origin:
            return

        try:
            origin = urlparse(raw_origin)
        except (ValueError, AttributeError):
            raise web.HTTPForbidden(text="Invalid Origin header.")

        if origin.scheme not in ("http", "https") or not origin.hostname:
            raise web.HTTPForbidden(text="Invalid Origin header.")

        origin_host = str(origin.hostname or "").lower()
        if not _is_local_browser_origin_host(origin_host):
            raise web.HTTPForbidden(text="Cross-origin browser requests are not allowed.")

        request_scheme = str(request.url.scheme or "").lower()
        request_host = str(request.url.host or "").lower()
        request_port = int(request.url.port or (443 if request_scheme == "https" else 80))

        origin_scheme = str(origin.scheme or "").lower()
        origin_port = int(origin.port or (443 if origin_scheme == "https" else 80))
        hosts_match = origin_host == request_host
        local_alias_match = _is_local_browser_origin_host(origin_host) and _is_local_browser_origin_host(request_host)

        if origin_scheme != request_scheme or not (hosts_match or local_alias_match) or origin_port != request_port:
            raise web.HTTPForbidden(text="Cross-origin browser requests are not allowed.")

    def _is_json_content_type(request: web.Request) -> bool:
        ctype = str(request.content_type or "").strip().lower()
        return ctype == "application/json" or ctype.endswith("+json")

    async def _read_json(request: web.Request) -> Any:
        """Parse JSON with a couple of real-world robustness tweaks.

        - Some Windows tools write UTF-8 with BOM, which breaks json.loads().
        - Avoid returning 500s on malformed JSON; surface as a 400 instead.
        """
        try:
            raw = await request.read()
        except (OSError, asyncio.TimeoutError) as e:
            raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")

        if not raw:
            return {}

        if not _is_json_content_type(request):
            raise web.HTTPUnsupportedMediaType(text="content-type must be application/json")

        try:
            text = raw.decode("utf-8-sig")
            return json.loads(text)
        except UnicodeDecodeError as e:
            raise web.HTTPBadRequest(text=f"invalid json: {type(e).__name__}: {e}")
        except json.JSONDecodeError as e:
            raise web.HTTPBadRequest(text=f"invalid json: {e}")

    _SESSION_LOCKS_MAX = 1024  # cap to prevent unbounded memory growth

    async def _session_lock_for(session_id: str) -> asyncio.Lock:
        token = str(session_id or "").strip()
        if not token:
            return asyncio.Lock()
        session_locks = _resolve_app_value(app, APP_SESSION_LOCKS, expected_type=dict, required=True)
        lock = session_locks.get(token)
        if lock is not None:
            session_locks.move_to_end(token)  # LRU refresh
            return lock
        session_locks_lock = _resolve_app_value(app, APP_SESSION_LOCKS_LOCK, required=True)
        async with session_locks_lock:
            session_locks = _resolve_app_value(app, APP_SESSION_LOCKS, expected_type=dict, required=True)
            existing = session_locks.get(token)
            if existing is not None:
                session_locks.move_to_end(token)
                return existing
            created = asyncio.Lock()
            session_locks[token] = created
            # Evict oldest entries that aren't currently held
            while len(session_locks) > _SESSION_LOCKS_MAX:
                oldest_key, oldest_lock = next(iter(session_locks.items()))
                if oldest_lock.locked():
                    break  # don't evict a lock that's in use
                del session_locks[oldest_key]
            return created

    async def _begin_session_run(session_id: str) -> bool:
        token = str(session_id or "").strip()
        if not token:
            return True
        active_runs_lock = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS_LOCK, required=True)
        async with active_runs_lock:
            active = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS, expected_type=set, required=True)
            if token in active:
                return False
            active.add(token)
            return True

    async def _end_session_run(session_id: str) -> None:
        token = str(session_id or "").strip()
        if not token:
            return
        active_runs_lock = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS_LOCK, required=True)
        async with active_runs_lock:
            active = _resolve_app_value(app, APP_SESSION_ACTIVE_RUNS, expected_type=set, required=True)
            active.discard(token)

    def _task_ledger_update(
        session_id: str,
        *,
        active_goal: Any = None,
        status: Any = None,
        missing_inputs: Any = None,
        last_progress: Any = None,
        source: str = "",
        force_event: bool = False,
    ) -> dict[str, Any] | None:
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return None
        try:
            snapshot = ledger.update(
                session_id,
                active_goal=active_goal,
                status=status,
                missing_inputs=missing_inputs,
                last_progress=last_progress,
                source=source,
                force_event=force_event,
            )
        except (OSError, RuntimeError, ValueError) as e:
            log.debug("Task ledger update failed (%s): %s", source, e)
            return None
        return snapshot.to_dict()

    # Optional: webhook routes (FastAPI logic bridged into aiohttp handlers)
    try:
        from thomas.server.routes.webhooks_aiohttp import register_webhooks_routes

        register_webhooks_routes(
            app,
            require_api_access=_require_api_access,
            signature_enforcement_default=str(config.server.access_mode or "local").strip().lower() == "remote",
        )
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Webhook routes unavailable: %s", e)

    def _join_url(base: str, path: str) -> str:
        b = (base or "").rstrip("/")
        p = path or ""
        if not p.startswith("/"):
            p = "/" + p
        return b + p

    def _is_loopback_host(host: str) -> bool:
        if not host:
            return False
        if host.lower() in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def _ollama_base_url(profile: str = "local") -> str:
        cfg: AppConfig = _resolve_runtime_config(app)
        if profile not in cfg.models:
            raise web.HTTPBadRequest(text=f"unknown profile: {profile}")
        base = str(cfg.models[profile].base_url or "").strip()
        if not base:
            raise web.HTTPBadRequest(text=f"models.{profile}.base_url is empty")
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        u = urlparse(base)
        if u.scheme not in ("http", "https"):
            raise web.HTTPBadRequest(text="local model base_url must be http(s)")
        if not _is_loopback_host(u.hostname or ""):
            raise web.HTTPBadRequest(text="local model base_url must be loopback (localhost/127.0.0.1)")
        return base

    def _model_cfg_with_secrets(profile: str):
        cfg: AppConfig = _resolve_runtime_config(app)
        base = cfg.get_model(profile)
        secrets: SecretStore = _resolve_app_value(app, APP_SECRETS, required=True)
        key = secrets.get(profile)
        if key:
            base = replace(base, api_key=key)
        return base

    def _failover_cfgs_with_secrets(primary_profile: str):
        cfg: AppConfig = _resolve_runtime_config(app)
        out: list[Any] = []
        for fb in cfg.failover_chain(primary_profile):
            try:
                out.append(_model_cfg_with_secrets(fb.name))
            except (KeyError, AttributeError, ValueError) as e:
                log.debug("Skipping failover profile %s: %s", getattr(fb, "name", "?"), e)
        return out

    async def _resolve_natural_model_switch_request(
        text: str,
        *,
        current_profile: str,
    ):
        if not is_model_switch_request(text):
            return None

        cfg: AppConfig = _resolve_runtime_config(app)
        default_models = {
            str(name): str(getattr(model_cfg, "model", "") or "").strip() for name, model_cfg in cfg.models.items()
        }
        candidate_profiles = infer_profile_candidates(
            text,
            current_profile=current_profile,
            available_profiles=default_models.keys(),
        )
        discovered: dict[str, list[str]] = {}
        for profile_name in candidate_profiles[:6]:
            profile_name = str(profile_name or "").strip()
            if not profile_name or profile_name not in cfg.models:
                continue
            ids: list[str] = []
            default_id = default_models.get(profile_name, "")
            if default_id:
                ids.append(default_id)
            try:
                hs = await handshake_models_async(_model_cfg_with_secrets(profile_name), timeout_s=2.5)
                for mid in list(hs.models or []):
                    m = str(mid or "").strip()
                    if m and m not in ids:
                        ids.append(m)
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as e:
                log.debug("Model switch discovery failed for profile %s: %s", profile_name, e)
            discovered[profile_name] = ids

        return resolve_model_switch_request(
            text,
            current_profile=current_profile,
            default_models=default_models,
            discovered_models=discovered,
        )

    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return int(default)

    def _clone_json(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False))

    def _chat_file_for(chat_id: str) -> Path:
        digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()
        return chat_store_dir / f"{digest}.json"

    def _sanitize_chat_payload(payload: Any, *, chat_id: str | None = None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest(text="chat payload must be a JSON object")

        requested_id = str(payload.get("id") or "").strip()
        resolved_id = str(chat_id or requested_id).strip()
        if not resolved_id:
            raise web.HTTPBadRequest(text="missing chat id")
        if len(resolved_id) > 160:
            raise web.HTTPBadRequest(text="chat id is too long")
        if requested_id and requested_id != resolved_id:
            raise web.HTTPBadRequest(text="chat id mismatch")

        now_ms = int(time.time() * 1000)
        created_at = _safe_int(payload.get("createdAt"), now_ms)
        updated_at = _safe_int(payload.get("updatedAt"), now_ms)
        updated_at = max(updated_at, created_at)

        title = str(payload.get("title") or "New Chat").strip() or "New Chat"
        if len(title) > 200:
            title = title[:200]

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise web.HTTPBadRequest(text="messages must be a list")

        messages: list[dict[str, Any]] = []
        for msg in raw_messages[:2000]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip()
            if role not in ("user", "assistant"):
                continue

            entry: dict[str, Any] = {
                "id": str(msg.get("id") or secrets.token_urlsafe(8)),
                "role": role,
                "createdAt": _safe_int(msg.get("createdAt"), now_ms),
                "status": str(msg.get("status") or "complete").strip() or "complete",
            }

            content = msg.get("content", "")
            if isinstance(content, str):
                entry["content"] = content[:200_000]
            else:
                try:
                    entry["content"] = _clone_json(content)
                except (json.JSONDecodeError, TypeError, ValueError):
                    entry["content"] = ""

            tool_calls = msg.get("toolCalls")
            if isinstance(tool_calls, list):
                tc_out: list[dict[str, Any]] = []
                for tc in tool_calls[:200]:
                    if not isinstance(tc, dict):
                        continue
                    try:
                        tc_out.append(_clone_json(tc))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
                entry["toolCalls"] = tc_out
            else:
                entry["toolCalls"] = []

            meta = msg.get("meta")
            if isinstance(meta, dict):
                try:
                    entry["meta"] = _clone_json(meta)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass

            messages.append(entry)

        session_id = payload.get("sessionId")
        if session_id is None:
            safe_session_id = None
        else:
            safe_session_id = str(session_id).strip() or None
            if safe_session_id and len(safe_session_id) > 512:
                safe_session_id = safe_session_id[:512]

        chat = {
            "id": resolved_id,
            "title": title,
            "model": str(payload.get("model") or payload.get("profile") or "").strip() or None,
            "messages": messages,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "pinned": bool(payload.get("pinned", False)),
            "sessionId": safe_session_id,
        }

        encoded = json.dumps(chat, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 10_000_000:
            raise web.HTTPBadRequest(text="chat payload too large")
        return chat

    def _read_chat_from_disk(path: Path) -> dict[str, Any] | None:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return None
            raw_id = str(payload.get("id") or "").strip()
            if not raw_id:
                return None
            return _sanitize_chat_payload(payload, chat_id=raw_id)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            log.debug("Skipping unreadable chat file %s: %s", path, e)
            return None

    async def _save_chat_to_disk(chat: dict[str, Any]) -> None:
        payload = json.dumps(chat, ensure_ascii=False, separators=(",", ":"))
        path = _chat_file_for(str(chat.get("id") or ""))
        tmp_path = Path(str(path) + ".tmp")
        async with chat_store_lock:
            try:
                await asyncio.to_thread(chat_store_dir.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(tmp_path.write_text, payload, encoding="utf-8")
                await asyncio.to_thread(tmp_path.replace, path)
            except Exception as e:
                log.error("Failed to save chat to disk: %s", e)
                with contextlib.suppress(OSError):
                    await asyncio.to_thread(tmp_path.unlink, missing_ok=True)
                raise

    async def _delete_chat_from_disk(chat_id: str) -> bool:
        path = _chat_file_for(chat_id)
        async with chat_store_lock:
            exists = await asyncio.to_thread(path.exists)
            if not exists:
                return False
            await asyncio.to_thread(path.unlink, missing_ok=True)
        return True

    async def _load_all_chats_from_disk() -> list[dict[str, Any]]:
        chats: list[dict[str, Any]] = []
        async with chat_store_lock:
            paths = await asyncio.to_thread(lambda: list(chat_store_dir.glob("*.json")))
        for path in paths:
            chat = await asyncio.to_thread(_read_chat_from_disk, path)
            if chat is not None:
                chats.append(chat)
        chats.sort(key=lambda c: _safe_int(c.get("updatedAt"), 0), reverse=True)
        return chats

    async def index(request: web.Request) -> web.StreamResponse:
        try:
            html = await asyncio.to_thread(
                lambda: (web_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            )
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "index.html")

    async def settings(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "settings.html").read_text(encoding="utf-8", errors="replace")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "settings.html")

    async def companion(request: web.Request) -> web.StreamResponse:
        try:
            html = (web_dir / "companion.html").read_text(encoding="utf-8", errors="replace")
            html = html.replace("__THOMAS_VERSION__", THOMAS_VERSION)
            return web.Response(
                text=html,
                content_type="text/html",
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, UnicodeDecodeError):
            return web.FileResponse(web_dir / "companion.html")

    # ── models/profiles/version routes extracted → routes/models_aiohttp.py ──

    # ── setup/diagnostics/local-pull routes extracted → routes/setup_aiohttp.py ──

    # ── onboarding routes extracted → routes/onboarding_aiohttp.py ──

    async def api_task_ledger_current(request: web.Request) -> web.Response:
        """Return current task ledger snapshot for a session (or latest session)."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return web.json_response({"ok": False, "error": "task_ledger_unavailable"}, status=503)

        session_id = str(request.query.get("session_id") or "").strip()
        snapshot = ledger.get_current(session_id) if session_id else ledger.get_latest()
        resolved_sid = session_id or (snapshot.session_id if snapshot is not None else "")
        return web.json_response(
            {
                "ok": True,
                "session_id": resolved_sid or None,
                "state": snapshot.to_dict() if snapshot is not None else None,
            }
        )

    async def api_task_ledger_history(request: web.Request) -> web.Response:
        """Return task ledger history events for a session."""
        _require_api_access(request)
        ledger = app.get(APP_TASK_LEDGER)
        if ledger is None:
            return web.json_response({"ok": False, "error": "task_ledger_unavailable"}, status=503)

        session_id = str(request.query.get("session_id") or "").strip()
        if not session_id:
            latest = ledger.get_latest()
            if latest is None:
                return web.json_response({"ok": True, "session_id": None, "events": [], "limit": 0})
            session_id = str(latest.session_id)

        try:
            limit = int(request.query.get("limit", "50") or 50)
        except (ValueError, TypeError):
            limit = 50
        limit = max(1, min(limit, 200))
        events = ledger.get_history(session_id, limit=limit)
        return web.json_response(
            {
                "ok": True,
                "session_id": session_id,
                "events": events,
                "limit": limit,
            }
        )

    async def api_security_mutating_routes(request: web.Request) -> web.Response:
        """Return the mutating routes policy snapshot."""
        _require_api_access(request)
        try:
            snapshot = dict(app.get(APP_MUTATING_ROUTE_POLICY_SNAPSHOT) or {})
        except (TypeError, ValueError) as exc:
            snapshot = {"ok": False, "error": str(exc)}
        return web.json_response(snapshot)

    async def api_engines(request: web.Request) -> web.Response:
        """Return status of all background engines."""
        _require_api_access(request)
        manager = app.get(APP_ENGINE_MANAGER)
        if manager is None:
            return web.json_response({"error": "engine manager not available"}, status=503)
        return web.json_response(manager.status())

    async def api_tools(request: web.Request) -> web.Response:
        _require_api_access(request)
        registry: ToolRegistry = app[APP_TOOLS]
        tools = [{"name": t.name, "category": t.category, "description": t.description} for t in registry.list_tools()]
        return web.json_response({"tools": tools})

    async def api_chats(request: web.Request) -> web.Response:
        _require_api_access(request)
        chats = await _load_all_chats_from_disk()
        return web.json_response({"chats": chats}, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def api_chat_put(request: web.Request) -> web.Response:
        _require_api_access(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat id")
        payload = await _read_json(request)
        chat = _sanitize_chat_payload(payload, chat_id=chat_id)
        await _save_chat_to_disk(chat)
        return web.json_response(
            {"ok": True, "chat": chat},
            dumps=lambda x: json.dumps(x, ensure_ascii=False),
        )

    async def api_chat_delete(request: web.Request) -> web.Response:
        _require_api_access(request)
        chat_id = str(request.match_info.get("chat_id") or "").strip()
        if not chat_id:
            raise web.HTTPBadRequest(text="missing chat id")
        deleted = await _delete_chat_from_disk(chat_id)
        return web.json_response({"ok": True, "id": chat_id, "deleted": bool(deleted)})

    # ── secrets routes extracted → routes/secrets_aiohttp.py ──

    # ── api_local_pull extracted → routes/setup_aiohttp.py ──

    # ── session lifecycle routes extracted → routes/sessions_aiohttp.py ──

    # ── chat execution extracted → routes/chat_aiohttp.py ──

    async def on_startup(app_: web.Application) -> None:
        task = app_.get(APP_RUNTIME_GUARD_TASK)
        if task is None or task.done():
            app_[APP_RUNTIME_GUARD_TASK] = asyncio.create_task(_runtime_guard_loop(app_))

    async def on_cleanup(app_: web.Application) -> None:
        mem = app_.get(APP_MEMORY)
        if mem is not None:
            try:
                mem.close()
            except (OSError, RuntimeError) as e:
                log.debug("Failed to close memory engine during cleanup: %s", e)
        task = app_.get(APP_RUNTIME_GUARD_TASK)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # Codex (ChatGPT OAuth) endpoints

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    from thomas.server.routes.asset_studio_aiohttp import register_asset_studio_routes
    from thomas.server.routes.codex_aiohttp import register_codex_routes
    from thomas.server.routes.companion_aiohttp import register_companion_routes
    from thomas.server.routes.core_aiohttp import register_core_routes
    from thomas.server.routes.engine_actions_aiohttp import register_engine_actions_routes
    from thomas.server.routes.gateway import p126_gateway_start_command as gateway_start_routes
    from thomas.server.routes.gateway import p127_gateway_restart_command as gateway_restart_routes
    from thomas.server.routes.gateway import p128_gateway_install_command as gateway_install_routes
    from thomas.server.routes.gateway import p129_gateway_uninstall_command as gateway_uninstall_routes
    from thomas.server.routes.gateway import p130_gateway_probe_command as gateway_probe_routes
    from thomas.server.routes.gateway import p131_gateway_discover_command as gateway_discover_routes
    from thomas.server.routes.gateway import p132_gateway_configured_command as gateway_configured_routes
    from thomas.server.routes.gateway import p133_gateway_health_detailed_payload as gateway_health_routes
    from thomas.server.routes.gateway import p134_gateway_usage_cost_command as gateway_usage_cost_routes
    from thomas.server.routes.gateway import p135_gateway_state_persistence_model as gateway_state_persistence_routes
    from thomas.server.routes.gateway import p136_gateway_auth_policy_enforcement as gateway_auth_policy_routes
    from thomas.server.routes.gateway import p137_gateway_logs_filter_command as gateway_logs_filter_routes
    from thomas.server.routes.gateway import p138_gateway_metrics_snapshot_command as gateway_metrics_snapshot_routes
    from thomas.server.routes.gateway import p139_openai_compat_route_scaffold as gateway_openai_compat_routes
    from thomas.server.routes.gateway import p140_openai_chat_completions_non_stream as gateway_openai_non_stream_routes
    from thomas.server.routes.gateway import p141_openai_chat_completions_stream as gateway_openai_stream_routes
    from thomas.server.routes.gateway import p142_openai_tool_call_passthrough_mapping as gateway_tool_call_routes
    from thomas.server.routes.gateway import p144_responses_compat_route_scaffold as gateway_responses_compat_routes
    from thomas.server.routes.gateway import p145_responses_create_non_stream as gateway_responses_create_routes
    from thomas.server.routes.gateway import p146_responses_create_stream_events as gateway_responses_stream_routes
    from thomas.server.routes.gateway import p147_responses_tool_result_mapping as gateway_tool_result_map_routes
    from thomas.server.routes.gateway import p148_compat_model_capability_resolver as gateway_compat_model_routes
    from thomas.server.routes.gateway import p149_compat_request_validation_layer as gateway_compat_validation_routes
    from thomas.server.routes.memory_aiohttp import register_memory_routes
    from thomas.server.routes.mission import register_mission_routes
    from thomas.server.routes.preferences_aiohttp import register_preferences_routes
    from thomas.server.routes.ui_engine_aiohttp import register_ui_engine_routes

    register_codex_routes(
        app,
        require_api_access=_require_api_access,
        codex_bridge_key=APP_CODEX_BRIDGE,
    )
    from thomas.server.routes.chat_aiohttp import ChatRouteDeps, register_chat_routes
    from thomas.server.routes.models_aiohttp import register_models_routes
    from thomas.server.routes.onboarding_aiohttp import register_onboarding_routes
    from thomas.server.routes.secrets_aiohttp import register_secrets_routes
    from thomas.server.routes.sessions_aiohttp import register_sessions_routes
    from thomas.server.routes.setup_aiohttp import register_setup_routes

    register_secrets_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    register_setup_routes(
        app,
        require_api_access=_require_api_access,
        require_loopback=_require_loopback,
        read_json=_read_json,
    )
    register_models_routes(
        app,
        require_api_access=_require_api_access,
        model_cfg_with_secrets=_model_cfg_with_secrets,
    )
    register_onboarding_routes(app, require_api_access=_require_api_access)
    register_sessions_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
        task_ledger_update=_task_ledger_update,
    )
    register_chat_routes(
        app,
        deps=ChatRouteDeps(
            require_api_access=_require_api_access,
            read_json=_read_json,
            session_lock_for=_session_lock_for,
            begin_session_run=_begin_session_run,
            end_session_run=_end_session_run,
            task_ledger_update=_task_ledger_update,
            model_cfg_with_secrets=_model_cfg_with_secrets,
            failover_cfgs_with_secrets=_failover_cfgs_with_secrets,
            resolve_natural_model_switch=_resolve_natural_model_switch_request,
            chat_file_for=_chat_file_for,
            read_chat_from_disk=_read_chat_from_disk,
            save_chat_to_disk=_save_chat_to_disk,
            build_tools=_build_tools,
        ),
    )
    register_preferences_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    from thomas.server.routes.spend import register_spend_routes

    register_spend_routes(app, require_api_access=_require_api_access)
    from thomas.server.routes.goals import register_goals_routes

    register_goals_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    from thomas.server.routes.search import register_search_routes

    register_search_routes(app, require_api_access=_require_api_access)
    register_asset_studio_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    register_ui_engine_routes(app, require_api_access=_require_api_access, read_json=_read_json)
    register_engine_actions_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
    )
    register_memory_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
    )
    register_companion_routes(
        app,
        require_api_access=_require_api_access,
        read_json=_read_json,
        config=config,
    )
    register_mission_routes(
        app,
        web_dir=web_dir,
        require_api_access=_require_api_access,
        run_store_enabled_key=APP_RUN_STORE_ENABLED,
        run_store_module_key=APP_RUN_STORE_MODULE,
    )
    try:
        from thomas.server.workspace.router import setup as setup_workspace_routes

        setup_workspace_routes(app, config, require_api_access=_require_api_access)
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Workspace routes unavailable: %s", e)

    def _normalize_gateway_mutating_path(path: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return ""
        if not raw.startswith("/"):
            raw = "/" + raw

        if raw == "/gateway" or raw.startswith("/gateway/"):
            return raw
        if raw == "/v1":
            return "/gateway/v1"
        if raw == "/v1/gateway" or raw.startswith("/v1/gateway/"):
            return raw[len("/v1") :]
        if raw.startswith("/v1/"):
            return "/gateway" + raw
        return "/gateway" + raw

    def _register_gateway_routes(
        module: Any,
        module_name: str,
        *,
        path_transform: Any = None,
    ) -> None:
        source_app = web.Application()
        target_transform = _normalize_gateway_mutating_path if path_transform is None else path_transform

        def _is_duplicate_route_error(exc: RuntimeError) -> bool:
            msg = str(exc).lower()
            return "already registered" in msg or "already exists" in msg or "conflict" in msg or "exists" in msg

        def _register_route_table(target: web.Application, routes_like: Any) -> None:
            if not routes_like:
                return
            try:
                target.router.add_routes(routes_like)
                return
            except RuntimeError as exc:
                if _is_duplicate_route_error(exc):
                    log.debug("%s: duplicate route table entries ignored", module_name)
                    return
                raise
            except TypeError:
                for route_item in routes_like:
                    if route_item is None:
                        continue
                    try:
                        if isinstance(route_item, tuple) and len(route_item) >= 3:
                            target.router.add_route(route_item[0], route_item[1], route_item[2])
                        else:
                            target.router.add_route(route_item.method, route_item.path, route_item.handler)
                    except RuntimeError as exc:
                        if not _is_duplicate_route_error(exc):
                            raise
                        log.debug("%s: duplicate route entry ignored", module_name)

        def _call_hook(hook: Any, hook_name: str) -> bool:
            try:
                signature = inspect.signature(hook)
                params = list(signature.parameters.values())
                if not params:
                    return False

                if params[0].name == "router":
                    hook(source_app.router)
                else:
                    hook(source_app)
                return True
            except TypeError as exc:
                # Mismatched target (typically app/router mix-up) -> ignore after warning.
                log.debug(
                    "Gateway module %s hook %s signature rejected: %s",
                    module_name,
                    hook_name,
                    exc,
                )
                return False
            except RuntimeError as exc:
                if _is_duplicate_route_error(exc):
                    log.debug(
                        "Gateway module %s hook %s produced duplicate routes; ignored",
                        module_name,
                        hook_name,
                    )
                    return True
                raise

        registered = False
        for hook_name in (
            "register",
            "setup_routes",
            "setup",
            "add_routes",
            "bind_routes",
            "register_routes",
        ):
            hook = getattr(module, hook_name, None)
            if not callable(hook):
                continue
            if _call_hook(hook, hook_name):
                registered = True
                break

        if not registered:
            routes_getter = getattr(module, "get_routes", None)
            if callable(routes_getter):
                try:
                    _register_route_table(source_app, routes_getter())
                    registered = True
                except (TypeError, RuntimeError, AttributeError):
                    log.debug("Gateway module %s get_routes registration failed", module_name, exc_info=True)
            if not registered:
                aiohttp_routes_getter = getattr(module, "get_aiohttp_routes", None)
                if callable(aiohttp_routes_getter):
                    try:
                        _register_route_table(source_app, aiohttp_routes_getter())
                        registered = True
                    except (TypeError, RuntimeError, AttributeError):
                        log.debug(
                            "Gateway module %s get_aiohttp_routes registration failed",
                            module_name,
                            exc_info=True,
                        )

        if not registered:
            return

        for route in source_app.router.routes():
            resource = getattr(route, "resource", None)
            if resource is None or not hasattr(resource, "get_info"):
                continue
            method = str(route.method or "").upper()
            if not method:
                continue
            info = resource.get_info()
            raw_path = info.get("path") or info.get("formatter") or info.get("prefix")
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                continue
            mapped_path = target_transform(raw_path)
            if not isinstance(mapped_path, str) or not mapped_path.startswith("/"):
                continue
            try:
                app.router.add_route(method, mapped_path, route.handler, name=getattr(route, "name", None))
            except RuntimeError as exc:
                if not _is_duplicate_route_error(exc):
                    raise
                log.debug("%s: duplicate transformed route entry ignored", module_name)

        for key, value in source_app.items():
            if key not in app:
                app[key] = value
        for cleanup_ctx in source_app.cleanup_ctx:
            app.cleanup_ctx.append(cleanup_ctx)

    try:
        _register_gateway_routes(gateway_start_routes, "p126_gateway_start_command")
        _register_gateway_routes(gateway_restart_routes, "p127_gateway_restart_command")
        _register_gateway_routes(gateway_uninstall_routes, "p129_gateway_uninstall_command")
        _register_gateway_routes(gateway_install_routes, "p128_gateway_install_command")
        _register_gateway_routes(gateway_discover_routes, "p131_gateway_discover_command")
        _register_gateway_routes(gateway_configured_routes, "p132_gateway_configured_command")
        _register_gateway_routes(gateway_health_routes, "p133_gateway_health_detailed_payload")
        _register_gateway_routes(gateway_usage_cost_routes, "p134_gateway_usage_cost_command")
        _register_gateway_routes(gateway_state_persistence_routes, "p135_gateway_state_persistence_model")
        _register_gateway_routes(gateway_auth_policy_routes, "p136_gateway_auth_policy_enforcement")
        _register_gateway_routes(gateway_logs_filter_routes, "p137_gateway_logs_filter_command")
        _register_gateway_routes(gateway_metrics_snapshot_routes, "p138_gateway_metrics_snapshot_command")
        _register_gateway_routes(gateway_openai_non_stream_routes, "p140_openai_chat_completions_non_stream")
        _register_gateway_routes(gateway_openai_stream_routes, "p141_openai_chat_completions_stream")
        _register_gateway_routes(gateway_tool_call_routes, "p142_openai_tool_call_passthrough_mapping")
        _register_gateway_routes(gateway_responses_compat_routes, "p144_responses_compat_route_scaffold")
        _register_gateway_routes(gateway_responses_create_routes, "p145_responses_create_non_stream")
        _register_gateway_routes(gateway_responses_stream_routes, "p146_responses_create_stream_events")
        _register_gateway_routes(gateway_tool_result_map_routes, "p147_responses_tool_result_mapping")
        _register_gateway_routes(gateway_compat_model_routes, "p148_compat_model_capability_resolver")
        _register_gateway_routes(gateway_compat_validation_routes, "p149_compat_request_validation_layer")
        _register_gateway_routes(gateway_openai_compat_routes, "p139_openai_compat_route_scaffold")
        _register_gateway_routes(gateway_probe_routes, "p130_gateway_probe_command")
    except (ImportError, ModuleNotFoundError, RuntimeError, AttributeError) as e:
        log.warning("Gateway control routes unavailable: %s", e)

    # Server restart endpoint -- sets shutdown event so supervisor loop restarts cleanly.
    async def api_server_restart(request: web.Request) -> web.Response:
        _require_api_access(request)
        log.warning("Server restart requested via API")
        shutdown_evt = request.app.get(APP_SHUTDOWN_EVENT)
        if shutdown_evt is not None:
            request.app[APP_RESTART_REQUESTED] = True
            shutdown_evt.set()
        else:
            # Fallback: no supervisor -- hard restart (legacy path)
            import subprocess

            def _do_restart() -> None:
                try:
                    kwargs: dict[str, Any] = {}
                    if sys.platform == "win32":
                        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                    subprocess.Popen([sys.executable] + sys.argv, close_fds=True, **kwargs)
                except (OSError, PermissionError) as exc:
                    log.error("Failed to spawn replacement server: %s", exc)
                os._exit(0)

            asyncio.get_event_loop().call_later(1.5, _do_restart)
        return web.json_response({"ok": True, "message": "Restarting..."})

    app.router.add_post("/api/server/restart", api_server_restart)

    register_core_routes(app, web_dir=web_dir, handlers=locals())

    def _build_mutating_route_policy_snapshot() -> dict[str, Any]:
        policies: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for route in app.router.routes():
            method = str(getattr(route, "method", "") or "").upper()
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                continue
            resource = getattr(route, "resource", None)
            if resource is None or not hasattr(resource, "get_info"):
                continue
            info = resource.get_info()
            raw_path = info.get("path") or info.get("formatter") or info.get("prefix")
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                continue
            sample_path = re.sub(r"\{[^}]+\}", "audit", raw_path)
            key = (method, sample_path)
            if key in seen:
                continue
            seen.add(key)
            if sample_path.startswith("/webhooks/receive/"):
                policies.append(
                    {
                        "method": method,
                        "path": raw_path,
                        "sample_path": sample_path,
                        "authz": "webhook_provider_signature_or_secret",
                        "csrf": "not_applicable_webhook_receiver",
                        "enforced_by": ["webhook_provider_signature_validation"],
                    }
                )
                continue
            if (
                sample_path.startswith("/api/")
                or sample_path.startswith("/gateway/")
                or sample_path.startswith("/v1/")
                or sample_path == "/probe"
            ):
                policies.append(
                    {
                        "method": method,
                        "path": raw_path,
                        "sample_path": sample_path,
                        "authz": "require_api_access",
                        "csrf": "same_origin_or_optional_custom_header",
                        "enforced_by": ["authz_guard_mutating_api", "csrf_guard_mutating_api"],
                    }
                )
                continue
            policies.append(
                {
                    "method": method,
                    "path": raw_path,
                    "sample_path": sample_path,
                    "authz": "unknown",
                    "csrf": "unknown",
                    "enforced_by": [],
                }
            )
        policies.sort(key=lambda row: (str(row.get("method") or ""), str(row.get("sample_path") or "")))
        return {
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "defaults": {"authz": "require_api_access", "csrf": "same_origin_or_optional_custom_header"},
            "route_count": len(policies),
            "policies": policies,
        }

    app[APP_MUTATING_ROUTE_POLICY_SNAPSHOT] = _build_mutating_route_policy_snapshot()

    return app


class _ServerRestartRequested(Exception):
    """Sentinel: supervisor loop should restart the server cleanly."""

    pass


async def serve_async(
    config: AppConfig,
    *,
    host: str = "127.0.0.1",
    port: int = 8899,
    crash_count: int = 0,
) -> None:
    from aiohttp import web

    app = create_app(config)
    app[APP_CRASH_COUNT] = crash_count

    # Shutdown event -- set by restart endpoint or signal handler
    shutdown_event = asyncio.Event()
    app[APP_SHUTDOWN_EVENT] = shutdown_event
    app[APP_RESTART_REQUESTED] = False

    runner = web.AppRunner(app)
    await runner.setup()

    # ── Port binding with retry (handles TIME_WAIT from previous instance) ──
    max_bind_attempts = 5
    for attempt in range(1, max_bind_attempts + 1):
        site = web.TCPSite(runner, host=host, port=port)
        try:
            await site.start()
            break
        except OSError as bind_err:
            # aiohttp may register the site before bind succeeds; stop() ensures
            # the next retry can create a fresh site without duplicate registration.
            with contextlib.suppress(Exception):
                await site.stop()
            if attempt == max_bind_attempts:
                print(f"[thomas] Port {port} still busy after {max_bind_attempts} attempts. Giving up.")
                await runner.cleanup()
                raise
            delay = attempt * 1.0
            print(
                f"[thomas] Port {port} busy ({bind_err}), retrying in {delay:.0f}s ({attempt}/{max_bind_attempts})..."
            )
            await asyncio.sleep(delay)

    # ── Startup summary ──
    diag = app.get(APP_DIAGNOSTICS, {})
    boot_dur = app.get(APP_BOOT_DURATION, 0)
    ok_features = [k for k, v in diag.items() if v]
    bad_features = [k for k, v in diag.items() if not v]
    print(f"[thomas] Server booted in {boot_dur:.1f}s")
    if ok_features:
        print(f"[thomas]   Features OK:  {', '.join(ok_features)}")
    if bad_features:
        print(f"[thomas]   Unavailable:  {', '.join(bad_features)}")
    if crash_count > 0:
        print(f"[thomas]   Crash count:  {crash_count}")
    print(f"[thomas]   Listening:    http://{host}:{port}/")

    # Keep running until shutdown event is set or interrupted.
    try:
        while not shutdown_event.is_set():
            await asyncio.sleep(1)
    finally:
        await runner.cleanup()
        if app.get(APP_RESTART_REQUESTED):
            raise _ServerRestartRequested()


def _check_single_instance(config: AppConfig, host: str, port: int) -> None:
    """Ensure only one Thomas server runs at a time.

    Uses a PID lock file. If another instance is alive, kills it first so the
    newest launch always wins. This prevents zombie accumulation when the user
    clicks "run UI" repeatedly.
    """
    import pathlib
    import signal
    import time as _time

    def _terminate_pid(pid: int, *, why: str, known_port: Any = "?") -> None:
        if pid == os.getpid():
            return
        try:
            os.kill(pid, 0)  # process exists
        except OSError:
            return

        print(f"[thomas] Stopping previous instance (PID {pid}, port {known_port}, {why})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

        # Wait up to 3s for graceful shutdown.
        for _ in range(30):
            _time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except OSError:
                break  # dead
        else:
            # Still alive -- force kill.
            try:
                os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
            except OSError:
                pass
        print("[thomas] Previous instance stopped.")

    def _list_duplicate_thomas_server_processes() -> list[tuple[int, str]]:
        """Best-effort process sweep for legacy/lockless server processes."""
        current_pid = os.getpid()
        matches: list[tuple[int, str]] = []

        def _match_cmdline(raw: str) -> bool:
            text = str(raw or "").strip().lower()
            if not text:
                return False
            return (" -m thomas serve" in text) or (" -m thomas.server" in text)

        try:
            if os.name == "nt":
                probe = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    data = json.loads(probe.stdout)
                    rows = data if isinstance(data, list) else [data]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        try:
                            pid = int(row.get("ProcessId"))
                        except (ValueError, TypeError):
                            continue
                        if pid <= 0 or pid == current_pid:
                            continue
                        name = str(row.get("Name") or "").lower()
                        if name and not name.startswith("python"):
                            continue
                        cmdline = str(row.get("CommandLine") or "")
                        if _match_cmdline(cmdline):
                            matches.append((pid, cmdline))
            else:
                probe = subprocess.run(
                    ["ps", "-eo", "pid=,args="],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5.0,
                    check=False,
                )
                if probe.returncode == 0:
                    for raw in (probe.stdout or "").splitlines():
                        line = raw.strip()
                        if not line:
                            continue
                        parts = line.split(maxsplit=1)
                        if not parts:
                            continue
                        try:
                            pid = int(parts[0])
                        except (ValueError, TypeError):
                            continue
                        if pid <= 0 or pid == current_pid:
                            continue
                        cmdline = parts[1] if len(parts) > 1 else ""
                        if _match_cmdline(cmdline):
                            matches.append((pid, cmdline))
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            log.debug("Duplicate process sweep unavailable: %s", exc)

        # Deduplicate while preserving order.
        seen: set[int] = set()
        unique: list[tuple[int, str]] = []
        for pid, cmd in matches:
            if pid in seen:
                continue
            seen.add(pid)
            unique.append((pid, cmd))
        return unique

    lock_dir = pathlib.Path(config.memory.root_path) / ".thomas"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "serve.lock"

    lock_pid_to_kill: int | None = None
    lock_port_to_kill: Any = "?"
    if lock_file.exists():
        try:
            data = json.loads(lock_file.read_text(encoding="utf-8"))
            old_pid = data.get("pid")
            old_port = data.get("port", "?")
            if old_pid is not None:
                try:
                    lock_pid_to_kill = int(old_pid)
                except (ValueError, TypeError):
                    lock_pid_to_kill = None
                lock_port_to_kill = old_port
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # corrupt lock file, overwrite it

    if lock_pid_to_kill is not None:
        _terminate_pid(lock_pid_to_kill, why="serve.lock owner", known_port=lock_port_to_kill)

    # Extra safeguard: terminate other Thomas server entrypoints, including
    # legacy `python -m thomas.server` processes that may have no lock file.
    for pid, cmdline in _list_duplicate_thomas_server_processes():
        _terminate_pid(pid, why="duplicate thomas server process", known_port="?")
        log.debug("Stopped duplicate Thomas server PID %s (%s)", pid, cmdline)

    # Write our lock
    lock_file.write_text(
        json.dumps({"pid": os.getpid(), "host": host, "port": port}),
        encoding="utf-8",
    )


def _release_lock(config: AppConfig) -> None:
    """Remove the lock file on clean shutdown."""
    import pathlib

    lock_file = pathlib.Path(config.memory.root_path) / ".thomas" / "serve.lock"
    try:
        lock_file.unlink(missing_ok=True)
    except OSError:
        pass


def serve(config: AppConfig, *, host: str = "127.0.0.1", port: int = 8899) -> None:
    """Run the server with a supervisor loop that auto-restarts on crashes.

    - Clean exits (Ctrl+C, SystemExit) stop immediately.
    - ``_ServerRestartRequested`` (from /api/server/restart) restarts with no
      crash count / backoff.
    - Unhandled exceptions trigger restart with exponential backoff.
    - After 5 crashes in 5 minutes, the supervisor gives up.
    """
    import asyncio
    import time as _time

    _check_single_instance(config, host, port)

    max_crashes = 5
    crash_window_s = 300  # 5 minutes
    crash_times: list = []
    crash_count = 0

    try:
        while True:
            try:
                asyncio.run(serve_async(config, host=host, port=port, crash_count=crash_count))
                break  # clean exit (e.g. Ctrl+C handled inside the event loop)
            except KeyboardInterrupt:
                print("\n[thomas] Stopped by user.")
                break
            except SystemExit:
                break
            except _ServerRestartRequested:
                print("[thomas] Restart requested. Rebooting...")
                # Clear bytecode cache to avoid stale .pyc issues after hot-edits
                try:
                    import importlib

                    import thomas

                    _pkg_root = os.path.dirname(thomas.__file__)
                    for _dirpath, _dirnames, _filenames in os.walk(_pkg_root):
                        if "__pycache__" in _dirnames:
                            _cache_dir = os.path.join(_dirpath, "__pycache__")
                            shutil.rmtree(_cache_dir, ignore_errors=True)
                    # Force re-import of critical modules
                    _stale = [k for k in sys.modules if k.startswith("thomas.")]
                    for k in _stale:
                        del sys.modules[k]
                    if "thomas" in sys.modules:
                        del sys.modules["thomas"]
                except (OSError, KeyError, ImportError) as _e:
                    print(f"[thomas] pycache cleanup: {_e}")
                continue  # no crash count, no backoff
            except BaseException as exc:
                # Catch most exceptions but not KeyboardInterrupt/SystemExit (handled above)
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                now = _time.time()
                crash_times.append(now)
                crash_times = [t for t in crash_times if now - t < crash_window_s]
                crash_count = len(crash_times)

                print(f"[thomas] CRASH ({crash_count}/{max_crashes}): {type(exc).__name__}: {exc}")

                if crash_count >= max_crashes:
                    print(
                        f"[thomas] {crash_count} crashes in {crash_window_s}s -- giving up. Fix the issue and restart manually."
                    )
                    break

                delay = min(2.0 * (2 ** (crash_count - 1)), 30.0)
                print(f"[thomas] Auto-restarting in {delay:.0f}s...")
                _time.sleep(delay)
    finally:
        _release_lock(config)
