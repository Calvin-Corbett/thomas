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
from typing import TYPE_CHECKING, Any
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
    APP_APPROVALS_BROKER,
    APP_BOOT_DURATION,
    APP_BOOT_TIME,
    APP_CHAT_AUTOPILOT_LAST_BY_GOAL,
    APP_CHAT_AUTOPILOT_LAST_BY_GOAL_LOCK,
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

if TYPE_CHECKING:
    from aiohttp import web

log = logging.getLogger(__name__)

_BEARER_TOKEN_RE = re.compile(r"^Bearer\s+([^\s]+)\s*$", re.IGNORECASE)

try:
    from thomas.server.routes.chat_aiohttp import AgentLoop as _DEFAULT_APP_AGENT_LOOP
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover
    from thomas.agent.loop import AgentLoop as _DEFAULT_APP_AGENT_LOOP

AgentLoop = _DEFAULT_APP_AGENT_LOOP

try:
    from thomas.models.capabilities import supports as model_supports
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover

    def model_supports(*_args, **_kwargs):
        return False


try:
    from thomas.models.chat_controls import resolve_ui_control_request
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover

    def resolve_ui_control_request(*_args, **_kwargs):
        return None


try:
    from thomas.server.chat_control_mode import handle_ui_control_chat
except (ImportError, ModuleNotFoundError, AttributeError):  # pragma: no cover
    from aiohttp import web

    async def handle_ui_control_chat(request: web.Request, **_kwargs):
        raise web.HTTPInternalServerError(text="ui control handler unavailable")


try:
    from thomas.memory.autonomy import AutonomyMemoryEngine
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    AutonomyMemoryEngine = None  # type: ignore[assignment]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class _FallbackSecretStore:
    """Graceful fallback when SecretStore initialization is unavailable."""

    def get(self, _key: str, default: str | None = None) -> str | None:
        return default


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


# ── chat autopilot helpers and control handlers extracted → routes/chat_aiohttp.py ──


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
        "git_branch": "",
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

    ok_branch, branch_out = _runtime_guard_run_git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    if ok_branch:
        snapshot["git_branch"] = branch_out
    else:
        snapshot["errors"].append(f"git_branch: {branch_out}")

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
            enable_legacy=_env_flag("THOMAS_MEMORY_LEGACY_ENABLED", False),
        )
        engine.start()
        return engine
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        log.warning("Memory engine failed to start: %s", e)
        return None


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"
