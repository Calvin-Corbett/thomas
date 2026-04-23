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
    "code": "invalid_input" | "missing_config" | "external_failure",
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
import inspect
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, Literal, Mapping, Optional, Sequence, TypedDict, cast

from aiohttp import web


# -----------------------------
# Contracts
# -----------------------------

class GatewayRestartRequestBody(TypedDict, total=False):
    gateway: str
    force: bool


class GatewayRestartErrorBody(TypedDict):
    code: str
    message: str
    details: Dict[str, Any]


class GatewayRestartFailureResponse(TypedDict):
    ok: Literal[False]
    error: GatewayRestartErrorBody


class GatewayRestartSuccessResponse(TypedDict):
    ok: Literal[True]
    gateway: str
    status: Literal["restart_requested"]
    method: Literal["controller", "command"]
    message: str


GatewayRestartResponse = GatewayRestartSuccessResponse | GatewayRestartFailureResponse


ROUTE_SCHEMA: Dict[str, Any] = {
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
                        "code": {"enum": ["invalid_input", "missing_config", "external_failure"]},
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
    def from_mapping(cls, data: Mapping[str, Any]) -> "GatewayRestartRequest":
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

    def __init__(self, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(self.message)
        self.details: Dict[str, Any] = details or {}


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


def _error_response(err: GatewayRestartError) -> web.Response:
    payload: GatewayRestartFailureResponse = {
        "ok": False,
        "error": {
            "code": err.code,
            "message": err.message,
            "details": err.details,
        },
    }
    return web.json_response(payload, status=err.http_status)


def _get_restart_command(app: web.Application) -> Optional[str | Sequence[str]]:
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


def _find_restart_callable(app: web.Application) -> Optional[Any]:
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
    kwargs: Dict[str, Any] = {}
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


async def _run_restart_command(cmd: str | Sequence[str]) -> None:
    argv = _normalize_argv(cmd)
    if not argv:
        raise GatewayRestartConfigMissing(details={"reason": "empty_restart_command"})

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    try:
        proc = await asyncio.to_thread(_run)
    except FileNotFoundError as e:
        raise GatewayRestartFailed(details={"exception_type": "FileNotFoundError"}) from e
    except Exception as e:  # noqa: BLE001
        raise GatewayRestartFailed(details={"exception_type": type(e).__name__}) from e

    if proc.returncode != 0:
        raise GatewayRestartFailed(details={"returncode": proc.returncode})


async def _restart_gateway(app: web.Application, req: GatewayRestartRequest) -> Literal["controller", "command"]:
    fn = _find_restart_callable(app)
    if fn is not None:
        await _invoke_restart_callable(fn, gateway=req.gateway, force=req.force)
        return "controller"

    cmd = _get_restart_command(app)
    if cmd is not None:
        await _run_restart_command(cmd)
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
        method = await _restart_gateway(request.app, req_model)

        payload: GatewayRestartSuccessResponse = {
            "ok": True,
            "gateway": req_model.gateway,
            "status": "restart_requested",
            "method": method,
            "message": "Gateway restart requested.",
        }
        return web.json_response(payload, status=200)
    except GatewayRestartError as e:
        return _error_response(e)
    except Exception as e:  # noqa: BLE001
        return _error_response(GatewayRestartFailed(details={"exception_type": type(e).__name__}))


@routes.get("/gateway/restart/schema")
async def gateway_restart_schema(_: web.Request) -> web.Response:
    return web.json_response(ROUTE_SCHEMA, status=200)


def setup_routes(app: web.Application) -> None:
    app.add_routes(routes)


ROUTES = routes
SetupRoutes = setup_routes
