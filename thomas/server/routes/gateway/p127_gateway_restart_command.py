"""
Gateway restart route (Thomas-native).

Route
-----
POST /gateway/restart

Request JSON body (optional)
----------------------------
{
  "gateway": "default",   # optional, non-empty string (<=128 chars)
  "force": false          # optional, boolean
}

Response JSON (success)
-----------------------
{
  "ok": true,
  "gateway": "default",
  "status": "restart_requested",
  "method": "controller" | "command",
  "message": "Gateway restart requested."
}

Response JSON (failure)
-----------------------
{
  "ok": false,
  "error": {
    "code": "invalid_input" | "missing_config" | "external_failure" | "access_denied" | "rate_limited" | "restart_in_progress",
    "message": "...",
    "details": {...}
  }
}

Notes
-----
Restart is performed using the first available mechanism:

1) A restart-capable callable stored on the aiohttp app (e.g. app["gateway"] or
   app["gateway_controller"]) with a callable method:
   - restart_gateway / restart / restart_gateway_process / restart_gateway_service

2) A configured restart command stored on the app (app["gateway_restart_command"])
   or in app["config"]["gateway_restart_command"] (string or argv list)

3) Environment variable: THOMAS_GATEWAY_RESTART_COMMAND

All failures are returned with deterministic error codes/messages suitable for automation.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import ipaddress
import json
import logging
import os
import shlex
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, TypedDict, cast
from collections.abc import Awaitable, Mapping, Sequence

from aiohttp import web

log = logging.getLogger(__name__)

_APP_RATE_LIMIT_STATE: web.AppKey[dict[str, Any]] = web.AppKey(
    "__p127_restart_rate_limit_state", dict
)
_APP_RATE_LIMIT_LOCK: web.AppKey[asyncio.Lock] = web.AppKey("__p127_restart_rate_limit_lock", asyncio.Lock)
_APP_RESTART_LOCK: web.AppKey[asyncio.Lock] = web.AppKey("__p127_restart_lock", asyncio.Lock)
_APP_REGISTERED: web.AppKey[bool] = web.AppKey("__p127_gateway_restart_registered", bool)


# -----------------------------
# Contracts
# -----------------------------

class GatewayRestartRequestBody(TypedDict, total=False):
    gateway: str
    force: bool


class GatewayRestartErrorBody(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class GatewayRestartFailureResponse(TypedDict):
    ok: Literal[False]
    error: GatewayRestartErrorBody


class GatewayRestartSuccessResponse(TypedDict, total=False):
    ok: Literal[True]
    gateway: str
    status: Literal["restart_requested"]
    method: Literal["controller", "command"]
    message: str
    deferral: dict[str, Any]


GatewayRestartResponse = GatewayRestartSuccessResponse | GatewayRestartFailureResponse


ROUTE_SCHEMA: dict[str, Any] = {
    "path": "/gateway/restart",
    "method": "POST",
    "request": {
        "type": "object",
        "properties": {
            "gateway": {"type": "string", "minLength": 1, "maxLength": 128, "default": "default"},
            "force": {"type": "boolean", "default": False},
        },
        "additionalProperties": False,
    },
    "responses": {
        "200": {
            "type": "object",
            "properties": {
                "ok": {"const": True},
                "gateway": {"type": "string"},
                "status": {"const": "restart_requested"},
                "method": {"enum": ["controller", "command"]},
                "message": {"type": "string"},
            },
            "required": ["ok", "gateway", "status", "method", "message"],
        },
        "400": {"$ref": "#/definitions/failure"},
        "401": {"$ref": "#/definitions/failure"},
        "409": {"$ref": "#/definitions/failure"},
        "429": {"$ref": "#/definitions/failure"},
        "500": {"$ref": "#/definitions/failure"},
        "502": {"$ref": "#/definitions/failure"},
    },
    "definitions": {
        "failure": {
            "type": "object",
            "properties": {
                "ok": {"const": False},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "enum": [
                                "invalid_input",
                                "missing_config",
                                "external_failure",
                                "access_denied",
                                "rate_limited",
                                "restart_in_progress",
                            ]
                        },
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                    },
                    "required": ["code", "message", "details"],
                },
            },
            "required": ["ok", "error"],
        }
    },
}


@dataclass(frozen=True)
class GatewayRestartRequest:
    """Validated gateway restart request."""

    gateway: str = "default"
    force: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> GatewayRestartRequest:
        allowed = {"gateway", "force"}
        unknown = sorted(k for k in data.keys() if k not in allowed)
        if unknown:
            raise InvalidGatewayRestartInput(details={"unknown_fields": unknown})

        gateway = data.get("gateway", "default")
        force = data.get("force", False)

        if not isinstance(gateway, str) or not gateway.strip():
            raise InvalidGatewayRestartInput(details={"field": "gateway"})
        if not isinstance(force, bool):
            raise InvalidGatewayRestartInput(details={"field": "force"})

        gateway = gateway.strip()
        if len(gateway) > 128:
            raise InvalidGatewayRestartInput(details={"field": "gateway", "reason": "too_long"})

        return cls(gateway=gateway, force=force)


# -----------------------------
# Deterministic error types
# -----------------------------

class GatewayRestartError(Exception):
    code: str = "external_failure"
    http_status: int = 502
    message: str = "Gateway restart failed."

    def __init__(
        self,
        *,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
        code: str | None = None,
        message: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if http_status is not None:
            self.http_status = int(http_status)
        if code is not None:
            self.code = str(code)
        if message is not None:
            self.message = str(message)
        super().__init__(self.message)
        self.details: dict[str, Any] = details or {}
        self.headers: dict[str, str] = dict(headers or {})


class InvalidGatewayRestartInput(GatewayRestartError):
    code = "invalid_input"
    http_status = 400
    message = "Invalid gateway restart request."


class GatewayRestartConfigMissing(GatewayRestartError):
    code = "missing_config"
    http_status = 500
    message = "Gateway restart is not configured."


class GatewayRestartFailed(GatewayRestartError):
    code = "external_failure"
    http_status = 502
    message = "Gateway restart failed."


class GatewayRestartAccessDenied(GatewayRestartError):
    code = "access_denied"
    http_status = 401
    message = "Gateway restart access denied."


class GatewayRestartRateLimited(GatewayRestartError):
    code = "rate_limited"
    http_status = 429
    message = "Gateway restart rate limit exceeded."


class GatewayRestartInProgress(GatewayRestartError):
    code = "restart_in_progress"
    http_status = 409
    message = "A gateway restart is already in progress."


def _error_response(err: GatewayRestartError) -> web.Response:
    payload: GatewayRestartFailureResponse = {
        "ok": False,
        "error": {
            "code": err.code,
            "message": err.message,
            "details": err.details,
        },
    }
    return web.json_response(payload, status=err.http_status, headers=err.headers)


def _coerce_int(raw: Any, *, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    if value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def _coerce_bool(raw: Any, *, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off", ""}:
            return False
    return bool(default)


def _truncate_text(raw: Any, *, max_len: int = 240) -> str:
    txt = str(raw or "").replace("\r", " ").replace("\n", " ").strip()
    if len(txt) <= max_len:
        return txt
    return txt[: max_len - 3] + "..."


def _extract_request_token(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Api-Token") or "").strip()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def _is_loopback_request(request: web.Request) -> bool:
    remote = str(request.remote or "").strip()
    if not remote:
        return False
    try:
        return ipaddress.ip_address(remote).is_loopback
    except ValueError:
        return False


def _extract_from_mapping_or_object(obj: Any, *path: str) -> Any:
    cur: Any = obj
    for part in path:
        if isinstance(cur, Mapping):
            if part not in cur:
                return None
            cur = cur.get(part)
            continue
        cur = getattr(cur, part, None)
        if cur is None:
            return None
    return cur


def _resolve_server_access_mode(app: web.Application) -> str:
    if "gateway_restart_access_mode" in app:
        return str(app["gateway_restart_access_mode"] or "local").strip().lower()

    cfg = app.get("config")
    mode = _extract_from_mapping_or_object(cfg, "server", "access_mode")
    if mode is None:
        mode = os.environ.get("THOMAS_GATEWAY_RESTART_ACCESS_MODE", "local")
    mode_text = str(mode or "local").strip().lower()
    if mode_text not in {"local", "remote"}:
        return "local"
    return mode_text


def _resolve_server_api_token(app: web.Application) -> str:
    if "gateway_restart_api_token" in app:
        return str(app["gateway_restart_api_token"] or "").strip()

    cfg = app.get("config")
    token = _extract_from_mapping_or_object(cfg, "server", "api_token")
    if token is None:
        token = os.environ.get("THOMAS_GATEWAY_RESTART_API_TOKEN", "")
    return str(token or "").strip()


def _enforce_restart_access(request: web.Request) -> None:
    mode = _resolve_server_access_mode(request.app)
    if mode == "remote":
        expected = _resolve_server_api_token(request.app)
        if not expected:
            raise GatewayRestartConfigMissing(details={"reason": "missing_api_token_for_remote_mode"})
        incoming = _extract_request_token(request)
        if not incoming:
            raise GatewayRestartAccessDenied(details={"reason": "missing_api_token"})
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise GatewayRestartAccessDenied(details={"reason": "invalid_api_token"})
        return

    if not _is_loopback_request(request):
        raise GatewayRestartAccessDenied(details={"reason": "loopback_only"})


def _enforce_gateway_auth_policy_if_present(request: web.Request) -> None:
    try:
        from thomas.server.routes.gateway import p136_gateway_auth_policy_enforcement as gw_auth
    except Exception:
        return

    try:
        policy = gw_auth.load_gateway_auth_policy(request.app)
        decision = gw_auth.authorize_gateway_request(request, policy)
    except gw_auth.GatewayAuthPolicyConfigError as e:
        raise GatewayRestartConfigMissing(details={"reason": "gateway_auth_config_error", "message": str(e)}) from e
    except gw_auth.GatewayAuthPolicyExternalError as e:
        raise GatewayRestartConfigMissing(details={"reason": "gateway_auth_external_error", "message": str(e)}) from e
    except Exception as e:  # noqa: BLE001
        raise GatewayRestartFailed(details={"reason": "gateway_auth_check_failed", "exception_type": type(e).__name__}) from e

    if decision.allowed:
        return

    if int(decision.http_status) >= 500:
        raise GatewayRestartConfigMissing(details={"reason": decision.code or "gateway_auth_misconfigured"})

    raise GatewayRestartAccessDenied(
        http_status=int(decision.http_status),
        details={"reason": decision.code or "gateway_auth_denied"},
    )


def _restart_rate_limit_settings(app: web.Application) -> tuple[bool, int, int]:
    enabled_raw = app.get(
        "gateway_restart_rate_limit_enabled",
        os.environ.get("THOMAS_GATEWAY_RESTART_RATE_LIMIT_ENABLED", "1"),
    )
    max_raw = app.get(
        "gateway_restart_rate_limit_max_requests",
        os.environ.get("THOMAS_GATEWAY_RESTART_RATE_LIMIT_MAX_REQUESTS", "5"),
    )
    window_raw = app.get(
        "gateway_restart_rate_limit_window_seconds",
        os.environ.get("THOMAS_GATEWAY_RESTART_RATE_LIMIT_WINDOW_SECONDS", "60"),
    )
    enabled = _coerce_bool(enabled_raw, default=True)
    max_requests = _coerce_int(max_raw, default=5, minimum=1, maximum=200)
    window_seconds = _coerce_int(window_raw, default=60, minimum=1, maximum=3600)
    return enabled, max_requests, window_seconds


def _restart_rate_limit_key(request: web.Request) -> str:
    token = _extract_request_token(request)
    if token:
        return f"token:{_token_hash(token)}"
    remote = str(request.remote or "").strip() or "unknown"
    return f"ip:{remote}"


async def _consume_restart_rate_limit(request: web.Request) -> None:
    enabled, max_requests, window_seconds = _restart_rate_limit_settings(request.app)
    if not enabled:
        return

    state = request.app.get(_APP_RATE_LIMIT_STATE)
    if not isinstance(state, dict):
        state = {"__gc_at__": 0.0}

    lock = request.app.get(_APP_RATE_LIMIT_LOCK)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()

    now = time.monotonic()
    cutoff = now - float(window_seconds)
    bucket_key = _restart_rate_limit_key(request)

    async with lock:
        bucket = state.get(bucket_key)
        if not isinstance(bucket, deque):
            bucket = deque()
            state[bucket_key] = bucket

        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= max_requests:
            oldest = float(bucket[0]) if bucket else now
            retry_after = max(1, int(round(float(window_seconds) - (now - oldest))))
            raise GatewayRestartRateLimited(
                details={
                    "retry_after_seconds": retry_after,
                    "window_seconds": window_seconds,
                    "max_requests": max_requests,
                },
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)

        gc_at = float(state.get("__gc_at__", 0.0) or 0.0)
        gc_interval = min(max(float(window_seconds), 5.0), 60.0)
        if (now - gc_at) >= gc_interval:
            stale_before = now - float(window_seconds)
            stale_keys = [
                k
                for k, b in state.items()
                if isinstance(b, deque) and (not b or float(b[-1]) <= stale_before)
            ]
            for stale_key in stale_keys:
                state.pop(stale_key, None)
            state["__gc_at__"] = now


def _get_restart_lock(app: web.Application) -> asyncio.Lock:
    lock = app.get(_APP_RESTART_LOCK)
    if isinstance(lock, asyncio.Lock):
        return lock
    lock = asyncio.Lock()
    if _APP_RESTART_LOCK in app:
        app[_APP_RESTART_LOCK] = lock
    return lock


def _restart_command_timeout_s(app: web.Application) -> int:
    raw = app.get(
        "gateway_restart_command_timeout_s",
        os.environ.get("THOMAS_GATEWAY_RESTART_COMMAND_TIMEOUT_S", "30"),
    )
    return _coerce_int(raw, default=30, minimum=1, maximum=600)


def _restart_deferral_settings(app: web.Application) -> tuple[int, int]:
    poll_raw = app.get(
        "gateway_restart_deferral_poll_ms",
        os.environ.get("THOMAS_GATEWAY_RESTART_DEFERRAL_POLL_MS", "500"),
    )
    max_wait_raw = app.get(
        "gateway_restart_deferral_max_wait_ms",
        os.environ.get("THOMAS_GATEWAY_RESTART_DEFERRAL_MAX_WAIT_MS", "30000"),
    )
    poll_ms = _coerce_int(poll_raw, default=500, minimum=10, maximum=5_000)
    max_wait_ms = _coerce_int(max_wait_raw, default=30_000, minimum=poll_ms, maximum=600_000)
    return poll_ms, max_wait_ms


async def _defer_restart_until_idle(app: web.Application) -> dict[str, Any]:
    check_pending = app.get("gateway_restart_pending_count")
    if not callable(check_pending):
        return {"enabled": False, "waited_ms": 0, "timed_out": False, "pending": 0}

    poll_ms, max_wait_ms = _restart_deferral_settings(app)
    started = time.monotonic()

    while True:
        try:
            pending = int(check_pending())
        except Exception as e:  # noqa: BLE001
            log.warning("gateway restart deferral check failed: %s", e)
            return {
                "enabled": True,
                "waited_ms": int((time.monotonic() - started) * 1000.0),
                "timed_out": False,
                "pending": 0,
                "check_error": type(e).__name__,
            }

        if pending <= 0:
            return {
                "enabled": True,
                "waited_ms": int((time.monotonic() - started) * 1000.0),
                "timed_out": False,
                "pending": 0,
            }

        waited_ms = int((time.monotonic() - started) * 1000.0)
        if waited_ms >= max_wait_ms:
            return {
                "enabled": True,
                "waited_ms": waited_ms,
                "timed_out": True,
                "pending": pending,
            }

        await asyncio.sleep(float(poll_ms) / 1000.0)


def _get_restart_command(app: web.Application) -> str | Sequence[str] | None:
    if "gateway_restart_command" in app:
        return cast(str | Sequence[str], app["gateway_restart_command"])

    cfg = app.get("config")
    if isinstance(cfg, Mapping):
        cmd = cfg.get("gateway_restart_command") or cfg.get("gateway_restart_cmd")
        if isinstance(cmd, (str, list, tuple)):
            return cast(str | Sequence[str], cmd)

    env_cmd = os.environ.get("THOMAS_GATEWAY_RESTART_COMMAND")
    if env_cmd:
        return env_cmd
    return None


def _find_restart_callable(app: web.Application) -> Any | None:
    candidate_keys = (
        "gateway_controller",
        "gateway",
        "gateway_manager",
        "gateway_service",
        "gateway_runtime",
    )
    method_names = (
        "restart_gateway",
        "restart",
        "restart_gateway_process",
        "restart_gateway_service",
    )

    for key in candidate_keys:
        if key not in app:
            continue
        obj = app[key]
        for meth in method_names:
            fn = getattr(obj, meth, None)
            if callable(fn):
                return fn
    return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await cast(Awaitable[Any], value)
    return value


async def _invoke_restart_callable(fn: Any, *, gateway: str, force: bool) -> None:
    kwargs: dict[str, Any] = {}
    sig = None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        sig = None

    if sig is not None:
        params = sig.parameters
        if "gateway" in params:
            kwargs["gateway"] = gateway
        elif "gateway_id" in params:
            kwargs["gateway_id"] = gateway
        elif "name" in params:
            kwargs["name"] = gateway

        if "force" in params:
            kwargs["force"] = force
        elif "hard" in params:
            kwargs["hard"] = force

    try:
        if kwargs:
            await _maybe_await(fn(**kwargs))
        else:
            await _maybe_await(fn())
    except GatewayRestartError:
        raise
    except Exception as e:  # noqa: BLE001
        raise GatewayRestartFailed(details={"exception_type": type(e).__name__}) from e


def _normalize_argv(cmd: str | Sequence[str]) -> Sequence[str]:
    if isinstance(cmd, str):
        argv = shlex.split(cmd)
    else:
        argv = [str(x) for x in cmd]
    return [a for a in argv if a.strip()]


async def _run_restart_command(app: web.Application, cmd: str | Sequence[str]) -> None:
    argv = _normalize_argv(cmd)
    if not argv:
        raise GatewayRestartConfigMissing(details={"reason": "empty_restart_command"})

    timeout_s = _restart_command_timeout_s(app)

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=float(timeout_s),
        )

    try:
        proc = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired as e:
        raise GatewayRestartFailed(
            details={
                "exception_type": "TimeoutExpired",
                "timeout_seconds": timeout_s,
                "argv": list(argv),
                "stdout": _truncate_text(getattr(e, "stdout", "")),
                "stderr": _truncate_text(getattr(e, "stderr", "")),
            }
        ) from e
    except FileNotFoundError as e:
        raise GatewayRestartFailed(
            details={
                "exception_type": "FileNotFoundError",
                "argv": list(argv),
            }
        ) from e
    except Exception as e:  # noqa: BLE001
        raise GatewayRestartFailed(details={"exception_type": type(e).__name__}) from e

    if proc.returncode != 0:
        raise GatewayRestartFailed(
            details={
                "returncode": int(proc.returncode),
                "argv": list(argv),
                "stdout": _truncate_text(proc.stdout),
                "stderr": _truncate_text(proc.stderr),
            }
        )


async def _restart_gateway(app: web.Application, req: GatewayRestartRequest) -> Literal["controller", "command"]:
    fn = _find_restart_callable(app)
    if fn is not None:
        await _invoke_restart_callable(fn, gateway=req.gateway, force=req.force)
        return "controller"

    cmd = _get_restart_command(app)
    if cmd is not None:
        await _run_restart_command(app, cmd)
        return "command"

    raise GatewayRestartConfigMissing(details={})


# -----------------------------
# Route registration
# -----------------------------

routes = web.RouteTableDef()


def _parse_optional_json_body(request: web.Request) -> Mapping[str, Any]:
    raw = request.get("_p127_cached_body_bytes")
    if raw is None or raw == b"":
        return {}

    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        raise InvalidGatewayRestartInput(details={"reason": "invalid_json"}) from None

    if obj is None:
        return {}
    if not isinstance(obj, Mapping):
        raise InvalidGatewayRestartInput(details={"reason": "body_must_be_object"})
    return cast(Mapping[str, Any], obj)


@routes.post("/gateway/restart")
async def gateway_restart(request: web.Request) -> web.Response:
    try:
        try:
            raw = await request.read()
        except Exception:
            raw = b""
        request["_p127_cached_body_bytes"] = raw

        body_obj = _parse_optional_json_body(request)
        req_model = GatewayRestartRequest.from_mapping(body_obj)

        await _consume_restart_rate_limit(request)
        _enforce_restart_access(request)
        _enforce_gateway_auth_policy_if_present(request)

        restart_lock = _get_restart_lock(request.app)
        if restart_lock.locked():
            raise GatewayRestartInProgress(details={"reason": "restart_already_in_progress"})

        await restart_lock.acquire()
        try:
            deferral = await _defer_restart_until_idle(request.app)
            method = await _restart_gateway(request.app, req_model)
        finally:
            restart_lock.release()

        payload: GatewayRestartSuccessResponse = {
            "ok": True,
            "gateway": req_model.gateway,
            "status": "restart_requested",
            "method": method,
            "message": "Gateway restart requested.",
        }
        payload["deferral"] = deferral
        return web.json_response(payload, status=200)
    except GatewayRestartError as e:
        return _error_response(e)
    except Exception as e:  # noqa: BLE001
        return _error_response(GatewayRestartFailed(details={"exception_type": type(e).__name__}))


@routes.get("/gateway/restart/schema")
async def gateway_restart_schema(_: web.Request) -> web.Response:
    return web.json_response(ROUTE_SCHEMA, status=200)


def setup_routes(app: web.Application) -> None:
    if app.get(_APP_REGISTERED):
        return
    app[_APP_REGISTERED] = True
    app[_APP_RATE_LIMIT_STATE] = {"__gc_at__": 0.0}
    app[_APP_RATE_LIMIT_LOCK] = asyncio.Lock()
    app[_APP_RESTART_LOCK] = asyncio.Lock()
    app.add_routes(routes)


ROUTES = routes
SetupRoutes = setup_routes
