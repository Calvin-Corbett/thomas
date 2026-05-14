"""Gateway health detailed payload (P133).

Provides:
- Async helper: `fetch_gateway_health_detailed(...)`
- Routes: `GET|POST /gateway/health/detailed` (and `/v1/...` alias)

This module is intentionally *Thomas-native* and focuses on:
- Deterministic, machine-readable results
- Minimal WebSocket RPC client (connect -> health)
- Reasonable defaults + explicit override support

Config resolution:
- Gateway URL: from request override OR server config/env
  - THOMAS_GATEWAY_URL (fallback)
- Auth: from request override OR server config/env (optional)
  - THOMAS_GATEWAY_TOKEN / THOMAS_GATEWAY_PASSWORD (fallback)
  - If both present, token is preferred deterministically.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping, Optional

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

SCHEMA_VERSION = 1

DEFAULT_TIMEOUT_MS = 10_000
DEFAULT_PROTOCOL_VERSION = 3

ENV_GATEWAY_URL = "THOMAS_GATEWAY_URL"
ENV_GATEWAY_TOKEN = "THOMAS_GATEWAY_TOKEN"
ENV_GATEWAY_PASSWORD = "THOMAS_GATEWAY_PASSWORD"


@dataclass(frozen=True, slots=True)
class GatewayHealthDetailedRequest:
    url: str | None = None
    token: str | None = None
    password: str | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    def validate(self) -> None:
        if self.timeout_ms <= 0 or self.timeout_ms > 120_000:
            raise GatewayHealthInputError(
                code="invalid_timeout",
                message="timeout_ms must be in the range 1..120000",
                details={"timeout_ms": self.timeout_ms},
            )
        if self.url is not None and not (self.url.startswith("ws://") or self.url.startswith("wss://")):
            raise GatewayHealthInputError(
                code="invalid_url",
                message="url must start with ws:// or wss://",
                details={"url": self.url},
            )
        if self.token and self.password:
            raise GatewayHealthInputError(
                code="ambiguous_auth",
                message="Provide only one of token or password",
                details={},
            )


@dataclass(frozen=True, slots=True)
class GatewayHealthDetailedResult:
    gateway_url: str
    duration_ms: int
    protocol_version: int | None
    snapshot: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "service": {
                "name": "thomas",
                "version": os.getenv("THOMAS_VERSION", "0"),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "pid": os.getpid(),
            },
            "gateway": {"url": self.gateway_url, "protocol": self.protocol_version},
            "duration_ms": self.duration_ms,
            "snapshot": self.snapshot,
        }


class GatewayHealthError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        http_status: int,
        error_type: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.error_type = error_type
        self.details = dict(details or {})

    def to_error_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "schema_version": SCHEMA_VERSION,
            "error": {
                "type": self.error_type,
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class GatewayHealthInputError(GatewayHealthError):
    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, http_status=400, error_type="invalid_request", details=details)


class GatewayHealthConfigError(GatewayHealthError):
    def __init__(self, *, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(code=code, message=message, http_status=500, error_type="configuration_error", details=details)


class GatewayHealthExternalError(GatewayHealthError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
        http_status: int = 502,
    ) -> None:
        super().__init__(code=code, message=message, http_status=http_status, error_type="gateway_error", details=details)


@dataclass(frozen=True, slots=True)
class _GatewayConn:
    url: str
    token: str | None = None
    password: str | None = None


def _app_cfg(app: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not app:
        return {}
    cfg = app.get("config")
    if isinstance(cfg, Mapping):
        return cfg
    settings = app.get("settings")
    if isinstance(settings, Mapping):
        return settings
    return app


def _cfg_get(cfg: Mapping[str, Any], dotted_key: str) -> Any:
    cur: Any = cfg
    for part in dotted_key.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _first_str(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _resolve_gateway_connection(*, overrides: GatewayHealthDetailedRequest, app: Mapping[str, Any] | None) -> _GatewayConn:
    cfg = _app_cfg(app)

    url = _first_str(
        overrides.url,
        _cfg_get(cfg, "gateway.url"),
        _cfg_get(cfg, "gateway_url"),
        os.getenv(ENV_GATEWAY_URL),
    )
    if not url:
        raise GatewayHealthConfigError(
            code="gateway_not_configured",
            message=f"Gateway URL is not configured. Set {ENV_GATEWAY_URL} or configure it in the server config.",
            details={},
        )

    # Overrides take precedence, but allow falling back to env/config for convenience.
    token = _first_str(
        overrides.token,
        _cfg_get(cfg, "gateway.token"),
        _cfg_get(cfg, "gateway_token"),
        os.getenv(ENV_GATEWAY_TOKEN),
    )
    password = _first_str(
        overrides.password,
        _cfg_get(cfg, "gateway.password"),
        _cfg_get(cfg, "gateway_password"),
        os.getenv(ENV_GATEWAY_PASSWORD),
    )

    # Deterministic precedence if both exist.
    if token and password:
        password = None

    return _GatewayConn(url=url, token=token, password=password)


async def fetch_gateway_health_detailed(
    request: GatewayHealthDetailedRequest,
    *,
    app: Mapping[str, Any] | None = None,
) -> GatewayHealthDetailedResult:
    request.validate()
    conn = _resolve_gateway_connection(overrides=request, app=app)

    timeout_s = request.timeout_ms / 1000.0
    start = time.perf_counter()

    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout_s)) as session:
            async with session.ws_connect(conn.url) as ws:
                # Some gateways emit a challenge before we send connect.
                nonce, ts = await _collect_challenge_events(ws, budget_s=min(timeout_s, 0.5))

                connect_id = uuid.uuid4().hex
                await ws.send_str(
                    json.dumps(
                        {
                            "type": "req",
                            "id": connect_id,
                            "method": "connect",
                            "params": _connect_params(nonce=nonce, ts=ts, token=conn.token, password=conn.password),
                        }
                    )
                )
                connect_res = await _wait_for_res(ws, connect_id, timeout_s=timeout_s)
                if not connect_res.get("ok"):
                    raise GatewayHealthExternalError(
                        code="connect_failed",
                        message="Gateway rejected connect request.",
                        details={"error": connect_res.get("error")},
                        http_status=401,
                    )

                protocol: int | None = None
                payload = connect_res.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("protocol"), int):
                    protocol = payload["protocol"]

                health_id = uuid.uuid4().hex
                await ws.send_str(json.dumps({"type": "req", "id": health_id, "method": "health", "params": {}}))
                health_res = await _wait_for_res(ws, health_id, timeout_s=timeout_s)
                if not health_res.get("ok"):
                    raise GatewayHealthExternalError(
                        code="gateway_health_failed",
                        message="Gateway health probe failed.",
                        details={"error": health_res.get("error")},
                    )
                snapshot = health_res.get("payload")

    except GatewayHealthError:
        raise
    except asyncio.TimeoutError as e:
        raise GatewayHealthExternalError(
            code="timeout",
            message="Timed out while probing gateway health.",
            details={"url": conn.url, "timeout_ms": request.timeout_ms},
            http_status=504,
        ) from e
    except Exception as e:
        # Keep this deterministic and automation-friendly: do not dump full repr(e).
        raise GatewayHealthExternalError(
            code="gateway_unreachable",
            message="Failed to connect to gateway",
            details={"exception_type": type(e).__name__},
        ) from e

    duration_ms = int(round((time.perf_counter() - start) * 1000))
    return GatewayHealthDetailedResult(conn.url, duration_ms, protocol, snapshot)


async def _collect_challenge_events(ws: Any, *, budget_s: float) -> tuple[str | None, int | None]:
    nonce: str | None = None
    ts: int | None = None
    deadline = time.perf_counter() + max(0.0, budget_s)

    # Attempt to read a few messages quickly without blocking too long.
    while time.perf_counter() < deadline:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=min(0.05, max(0.0, deadline - time.perf_counter())))
        except asyncio.TimeoutError:
            break
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            frame = json.loads(msg.data)
        except Exception:
            continue
        if (
            isinstance(frame, dict)
            and frame.get("type") == "event"
            and frame.get("event") == "connect.challenge"
            and isinstance(frame.get("payload"), dict)
        ):
            payload = frame["payload"]
            v_nonce = payload.get("nonce")
            v_ts = payload.get("ts")
            if isinstance(v_nonce, str):
                nonce = v_nonce
            if isinstance(v_ts, int):
                ts = v_ts
            # Keep reading briefly; some gateways send multiple events.
            continue
        # Ignore other pre-connect events; do not attempt to buffer them.
        continue

    return nonce, ts


def _connect_params(*, nonce: str | None, ts: int | None, token: str | None, password: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "minProtocol": DEFAULT_PROTOCOL_VERSION,
        "maxProtocol": DEFAULT_PROTOCOL_VERSION,
        "client": {
            "id": "thomas",
            "version": os.getenv("THOMAS_VERSION", "0"),
            "platform": platform.system().lower(),
            "mode": "operator",
        },
        "role": "operator",
        "scopes": ["operator.read"],
        "caps": [],
        "commands": [],
        "permissions": {},
        "locale": "en-US",
        "userAgent": "thomas",
    }
    if token:
        params["auth"] = {"token": token}
    elif password:
        params["auth"] = {"password": password}
    if nonce is not None and ts is not None:
        params["device"] = {"id": f"thomas-{platform.node()}", "nonce": nonce, "signedAt": ts}
    return params


async def _wait_for_res(ws: Any, req_id: str, *, timeout_s: float) -> MutableMapping[str, Any]:
    deadline = time.perf_counter() + timeout_s
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
        if msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSE, WSMsgType.ERROR):
            raise GatewayHealthExternalError(
                code="socket_closed",
                message="Gateway closed the WebSocket connection unexpectedly.",
                details={"req_id": req_id},
            )
        if msg.type != WSMsgType.TEXT:
            continue
        try:
            frame = json.loads(msg.data)
        except Exception:
            continue
        if not isinstance(frame, dict):
            continue
        if frame.get("type") == "event":
            continue
        if frame.get("type") == "res" and frame.get("id") == req_id:
            return frame


routes = web.RouteTableDef()


async def _read_json_body(request: web.Request) -> MutableMapping[str, Any]:
    if not request.can_read_body or request.content_length in (None, 0):
        return {}
    # Only parse JSON content-types.
    if "json" not in (request.content_type or ""):
        return {}
    try:
        data = await request.json()
    except Exception as e:
        raise GatewayHealthInputError(code="invalid_json", message="Request body is not valid JSON.", details={}) from e
    if isinstance(data, dict):
        return dict(data)
    raise GatewayHealthInputError(
        code="invalid_json",
        message="Request body JSON must be an object.",
        details={"type": type(data).__name__},
    )


def _parse_int(value: Any, *, field: str) -> int:
    try:
        return int(value)
    except Exception as e:
        raise GatewayHealthInputError(code="invalid_integer", message=f"{field} must be an integer", details={field: value}) from e


@routes.get("/gateway/health/detailed")
@routes.post("/gateway/health/detailed")
@routes.get("/v1/gateway/health/detailed")
@routes.post("/v1/gateway/health/detailed")
async def gateway_health_detailed_route(request: web.Request) -> web.Response:
    try:
        body = await _read_json_body(request)

        # Query params take precedence over body for deterministic override semantics.
        url = request.query.get("url") or body.get("url")
        token = request.query.get("token") or body.get("token")
        password = request.query.get("password") or body.get("password")
        timeout_raw = request.query.get("timeout_ms") or body.get("timeout_ms")
        timeout_ms = _parse_int(timeout_raw, field="timeout_ms") if timeout_raw is not None else DEFAULT_TIMEOUT_MS

        result = await fetch_gateway_health_detailed(
            GatewayHealthDetailedRequest(url=url, token=token, password=password, timeout_ms=timeout_ms),
            app=request.app,
        )
        return web.json_response(result.to_dict(), status=200)
    except GatewayHealthError as e:
        return web.json_response(e.to_error_dict(), status=e.http_status)


ROUTES = routes


def register(app: web.Application) -> None:
    app.add_routes(routes)
