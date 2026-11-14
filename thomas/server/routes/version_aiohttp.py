"""``GET /api/version``: the running version, whether the code on disk is newer, and whether this is a dev or prod run.

This route is part of the server itself. It answers the boot probes and the debug dock, so it is registered with the
shell's own routes and cannot be turned off.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from aiohttp import web

from thomas import __version__ as THOMAS_VERSION
from thomas.core.config import AppConfig
from thomas.server.app_helpers import _resolve_app_value, _resolve_runtime_config
from thomas.server.app_keys import APP_RUNTIME_GUARD_STATE

RequireAccessFn = Callable[[web.Request], None]

_RUNTIME_MODE_PROD_ENV = frozenset({"prod", "production", "release", "live"})
_RUNTIME_MODE_PROD_BRANCH = frozenset({"prod", "production", "release", "stable"})


def _runtime_guard_payload(app: web.Application) -> dict[str, Any]:
    state = _resolve_app_value(app, APP_RUNTIME_GUARD_STATE, expected_type=dict, default={})
    if not isinstance(state, dict) or not state:
        return {
            "enabled": False,
            "is_latest_code": True,
            "state": "unknown",
            "checked_at_utc": "",
            "reasons": [],
            "alert_message": "",
            "git_branch": "",
            "pid": None,
            "lock_pid": None,
            "lock_port": None,
        }

    status = state.get("status") if isinstance(state.get("status"), dict) else {}
    current = state.get("current") if isinstance(state.get("current"), dict) else {}
    current_source = current.get("source") if isinstance(current.get("source"), dict) else {}
    boot = state.get("boot") if isinstance(state.get("boot"), dict) else {}
    boot_source = boot.get("source") if isinstance(boot.get("source"), dict) else {}
    lock = current.get("lock") if isinstance(current.get("lock"), dict) else {}
    return {
        "enabled": bool(state.get("enabled", True)),
        "is_latest_code": bool(status.get("is_latest_code", True)),
        "state": str(status.get("state") or "unknown"),
        "checked_at_utc": str(status.get("checked_at_utc") or ""),
        "reasons": list(status.get("reasons") or []),
        "alert_message": str(status.get("alert_message") or ""),
        "git_branch": str(current_source.get("git_branch") or boot_source.get("git_branch") or ""),
        "pid": current.get("pid"),
        "lock_pid": lock.get("pid"),
        "lock_port": lock.get("port"),
    }


def _runtime_mode_payload(app: web.Application) -> dict[str, str]:
    runtime_guard = _runtime_guard_payload(app)
    git_branch = str(runtime_guard.get("git_branch") or "").strip()
    env_raw = str(os.environ.get("THOMAS_ENV") or os.environ.get("PYTHON_ENV") or os.environ.get("ENV") or "").strip()
    env_norm = env_raw.lower()
    branch_norm = git_branch.lower()

    label = "DEV"
    source = "default"
    if env_norm in _RUNTIME_MODE_PROD_ENV:
        label = "PROD"
        source = "env"
    elif branch_norm in _RUNTIME_MODE_PROD_BRANCH:
        label = "PROD"
        source = "git_branch"
    elif env_norm:
        source = "env"
    elif branch_norm:
        source = "git_branch"

    return {
        "label": label,
        "source": source,
        "env": env_raw,
        "git_branch": git_branch,
    }


def register_version_route(app: web.Application, *, require_api_access: RequireAccessFn) -> None:
    async def api_version(request: web.Request) -> web.Response:
        cfg: AppConfig = _resolve_runtime_config(request.app)
        if not bool(getattr(getattr(cfg, "server", None), "allow_unauthenticated_version", True)):
            require_api_access(request)
        return web.json_response(
            {
                "version": THOMAS_VERSION,
                "runtime_guard": _runtime_guard_payload(request.app),
                "runtime_mode": _runtime_mode_payload(request.app),
            }
        )

    app.router.add_get("/api/version", api_version)
