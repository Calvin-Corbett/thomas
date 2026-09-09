"""Thomas Gateway probe endpoint.

This module provides a **probe** endpoint that checks reachability of a configured
Gateway target via a simple HTTP request.

Design goals:
- No I/O at import time.
- Deterministic, machine-readable errors.
- Easy integration with varying Thomas route-loader conventions.

Request JSON schema (all fields optional):
  - target: str        Gateway base URL to probe (overrides config/env)
  - timeout_s: float   Total timeout in seconds (default 3.0, max 120)
  - path: str          Path to request on the gateway (default "/")

Response JSON schema:
  - ok: bool
  - target: str
  - latency_ms: int | null
  - status_code: int | null
  - error: {code: str, message: str} | null
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from aiohttp import ClientError, ClientSession, ClientTimeout, web
from yarl import URL


class ErrorPayload(TypedDict):
    code: str
    message: str


@dataclass(frozen=True)
class GatewayProbeRequest:
    """Input contract for a gateway probe."""

    target: str | None = None
    timeout_s: float = 3.0
    path: str = "/"


@dataclass(frozen=True)
class GatewayProbeResponse:
    """Output contract for a gateway probe."""

    ok: bool
    target: str
    latency_ms: int | None = None
    status_code: int | None = None
    error: ErrorPayload | None = None


class GatewayProbeException(Exception):
    """Deterministic, user-facing probe error."""

    def __init__(self, code: str, message: str, *, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def to_payload(self) -> ErrorPayload:
        return {"code": self.code, "message": self.message}


def _coerce_float(value: Any, *, field: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError) as e:
        raise GatewayProbeException("invalid_input", f"Field '{field}' must be a number.", http_status=400) from e
    if not (f > 0):
        raise GatewayProbeException("invalid_input", f"Field '{field}' must be > 0.", http_status=400)
    if f > 120:
        raise GatewayProbeException("invalid_input", f"Field '{field}' must be <= 120.", http_status=400)
    return f


def _coerce_str(value: Any, *, field: str) -> str:
    if value is None:
        raise GatewayProbeException("invalid_input", f"Field '{field}' is required.")
    if not isinstance(value, str):
        raise GatewayProbeException("invalid_input", f"Field '{field}' must be a string.", http_status=400)
    s = value.strip()
    if not s:
        raise GatewayProbeException("invalid_input", f"Field '{field}' must not be empty.", http_status=400)
    return s


def _get_nested(mapping: Mapping[str, Any], dotted_key: str) -> Any:
    cur: Any = mapping
    for part in dotted_key.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _try_load_config() -> Mapping[str, Any]:
    """Best-effort config loader.

    Thomas may expose config through different modules. We try common hooks and
    fall back to an empty mapping. This function never raises.
    """

    cfg_json = os.environ.get("THOMAS_CONFIG_JSON")
    if cfg_json:
        try:
            loaded = json.loads(cfg_json)
            if isinstance(loaded, Mapping):
                return loaded
        except Exception:
            return {}

    candidates = [
        ("thomas.config", "load"),
        ("thomas.config", "load_config"),
        ("thomas.config", "get_config"),
        ("thomas.settings", "load_settings"),
        ("thomas.settings", "get_settings"),
        ("thomas.server.config", "load_config"),
        ("thomas.server.config", "get_config"),
    ]
    for mod_name, func_name in candidates:
        try:
            mod = importlib.import_module(mod_name)
            func = getattr(mod, func_name, None)
            if callable(func):
                cfg = func()
                if isinstance(cfg, Mapping):
                    return cfg
        except Exception:
            continue
    return {}


def resolve_gateway_target(
    *,
    explicit_target: str | None = None,
    app_config: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve the gateway target URL.

    Precedence:
      1) explicit_target
      2) environment variables: THOMAS_GATEWAY_URL, THOMAS_GATEWAY_TARGET, THOMAS_GATEWAY
      3) app_config (if provided)
      4) global config loader (best effort)

    Raises:
      GatewayProbeException: on missing/invalid target.
    """

    if explicit_target is not None and str(explicit_target).strip():
        target = str(explicit_target).strip()
    else:
        env = dict(environ or os.environ)
        target = (
            env.get("THOMAS_GATEWAY_URL") or env.get("THOMAS_GATEWAY_TARGET") or env.get("THOMAS_GATEWAY") or ""
        ).strip()

        if not target:
            cfg = app_config or _try_load_config()
            if cfg:
                for key in (
                    "gateway_url",
                    "gateway.target",
                    "gateway.url",
                    "gateway.endpoint",
                    "gateway.base_url",
                ):
                    value = cfg.get(key) if key in cfg else _get_nested(cfg, key)
                    if isinstance(value, str) and value.strip():
                        target = value.strip()
                        break

    if not target:
        raise GatewayProbeException(
            "missing_config",
            "No gateway target configured. Provide 'target' or set THOMAS_GATEWAY_URL.",
            http_status=400,
        )

    try:
        url = URL(target)
    except Exception as e:
        raise GatewayProbeException("invalid_target", "Gateway target must be a valid URL.", http_status=400) from e

    if not url.scheme or not url.host:
        raise GatewayProbeException(
            "invalid_target",
            "Gateway target must include scheme and host (e.g. http://127.0.0.1:18789).",
            http_status=400,
        )

    return str(url)


async def probe_gateway(*, target: str, timeout_s: float = 3.0, path: str = "/") -> GatewayProbeResponse:
    """Probe a gateway target by performing an HTTP GET."""

    timeout_s = _coerce_float(timeout_s, field="timeout_s")

    try:
        base = URL(target)
    except Exception as e:
        raise GatewayProbeException("invalid_target", "Gateway target must be a valid URL.", http_status=400) from e

    probe_path = path if isinstance(path, str) else "/"
    probe_path = probe_path.strip() or "/"
    if not probe_path.startswith("/"):
        probe_path = "/" + probe_path

    url = str(base.with_path(probe_path))

    started = time.monotonic()
    status_code: int | None = None
    try:
        timeout = ClientTimeout(total=timeout_s)
        async with ClientSession(timeout=timeout) as session, session.get(url) as resp:
            status_code = resp.status
            await resp.read()

        latency_ms = int(round((time.monotonic() - started) * 1000))
        if status_code >= 400:
            return GatewayProbeResponse(
                ok=False,
                target=str(base),
                latency_ms=latency_ms,
                status_code=status_code,
                error={"code": "bad_status", "message": f"Gateway responded with HTTP {status_code}."},
            )

        return GatewayProbeResponse(
            ok=True,
            target=str(base),
            latency_ms=latency_ms,
            status_code=status_code,
            error=None,
        )

    except asyncio.TimeoutError:
        latency_ms = int(round((time.monotonic() - started) * 1000))
        return GatewayProbeResponse(
            ok=False,
            target=str(base),
            latency_ms=latency_ms,
            status_code=status_code,
            error={"code": "timeout", "message": "Gateway probe timed out."},
        )
    except ClientError:
        latency_ms = int(round((time.monotonic() - started) * 1000))
        return GatewayProbeResponse(
            ok=False,
            target=str(base),
            latency_ms=latency_ms,
            status_code=status_code,
            error={"code": "unreachable", "message": "Gateway target is unreachable."},
        )


def _parse_request_payload(payload: Any) -> GatewayProbeRequest:
    if payload is None:
        return GatewayProbeRequest()
    if not isinstance(payload, Mapping):
        raise GatewayProbeException("invalid_input", "Request body must be a JSON object.", http_status=400)

    target = payload.get("target")
    timeout_s = payload.get("timeout_s", 3.0)
    path = payload.get("path", "/")

    return GatewayProbeRequest(
        target=str(target).strip() if isinstance(target, str) else None,
        timeout_s=_coerce_float(timeout_s, field="timeout_s"),
        path=_coerce_str(path, field="path") if path is not None else "/",
    )


routes = web.RouteTableDef()


@routes.post("/probe")
async def gateway_probe(request: web.Request) -> web.Response:
    """HTTP handler for probing the configured gateway target."""

    req = GatewayProbeRequest()
    try:
        payload: Any = None
        if request.can_read_body:
            try:
                payload = await request.json()
            except json.JSONDecodeError as e:
                raise GatewayProbeException("invalid_input", "Request body must be valid JSON.", http_status=400) from e
            except Exception:
                payload = None

        req = _parse_request_payload(payload)

        app_cfg = None
        for key in ("config", "settings"):
            if key in request.app and isinstance(request.app[key], Mapping):
                app_cfg = request.app[key]
                break

        target = resolve_gateway_target(explicit_target=req.target, app_config=app_cfg)
        result = await probe_gateway(target=target, timeout_s=req.timeout_s, path=req.path)

        status = 200 if result.ok else 502
        return web.json_response(asdict(result), status=status)

    except GatewayProbeException as e:
        err = GatewayProbeResponse(ok=False, target=req.target or "", error=e.to_payload())
        return web.json_response(asdict(err), status=e.http_status)
    except Exception:
        err = GatewayProbeResponse(
            ok=False,
            target=req.target or "",
            error={"code": "internal_error", "message": "Internal server error."},
        )
        return web.json_response(asdict(err), status=500)


# Compatibility aliases for different Thomas route-loader conventions.
ROUTES = routes


def get_routes() -> web.RouteTableDef:
    return routes
