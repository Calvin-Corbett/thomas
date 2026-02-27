"""Gateway: OpenAI-compatible proxy scaffold (Thomas-native).

This module provides a minimal OpenAI-compatible surface inside Thomas, intended
to be mounted under the Gateway API. It is explicitly a scaffold:
- deterministic OpenAI-style error envelopes
- a machine-readable schema endpoint for automation
- a proxy for /v1/chat/completions (JSON + SSE pass-through)

Mounting / paths
---------------
The route paths in this module are *relative* (base "/openai-compat"). If the
Thomas server mounts gateway routes under "/gateway" (common), the effective
external paths become:

  /gateway/openai-compat/schema
  /gateway/openai-compat/health
  /gateway/openai-compat/v1/chat/completions

If mounted at root, paths are:

  /openai-compat/schema
  /openai-compat/health
  /openai-compat/v1/chat/completions

Configuration
-------------
Config sources (first match wins):
1) request.app["gateway_openai_compat"] mapping, if present
2) request.app["config"] / request.app["settings"] mapping (best effort)
3) environment variables

Environment variables:
  - THOMAS_GATEWAY_OPENAI_BASE_URL or THOMAS_OPENAI_BASE_URL (required)
  - THOMAS_GATEWAY_OPENAI_API_KEY or THOMAS_OPENAI_API_KEY (required unless allow-no-key)
  - THOMAS_GATEWAY_OPENAI_TIMEOUT_S or THOMAS_OPENAI_TIMEOUT_S (optional; default 30)
  - THOMAS_GATEWAY_OPENAI_ALLOW_NO_KEY or THOMAS_OPENAI_ALLOW_NO_KEY (optional; default false)

Notes
-----
- We reuse a shared aiohttp ClientSession stored on the app to avoid per-request
  session creation overhead.
- We preserve upstream OpenAI-style error bodies if upstream already returns
  {"error": {...}}.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from typing import Any, TypedDict, cast

# NotRequired was added in Python 3.11, use typing_extensions for earlier versions
if sys.version_info >= (3, 11):
    from typing import NotRequired
else:
    from typing_extensions import NotRequired

from aiohttp import ClientError, ClientSession, ClientTimeout, web

# -----------------------------
# Contracts
# -----------------------------


class OpenAICompatError(TypedDict):
    message: str
    type: str
    param: str | None
    code: str


class OpenAICompatErrorResponse(TypedDict):
    error: OpenAICompatError


class ChatCompletionMessage(TypedDict, total=False):
    role: str
    content: Any
    name: NotRequired[str]
    tool_call_id: NotRequired[str]


class OpenAIChatCompletionsRequest(TypedDict, total=False):
    model: str
    messages: list[ChatCompletionMessage]
    stream: bool
    temperature: float
    max_tokens: int


class OpenAICompatRouteSchema(TypedDict):
    id: str
    title: str
    description: str
    routes: list[dict[str, Any]]
    config: dict[str, Any]


@dataclass(frozen=True)
class OpenAICompatConfig:
    base_url: str
    api_key: str | None = None
    timeout_s: float = 30.0
    allow_no_key: bool = False


# -----------------------------
# Route table
# -----------------------------

routes = web.RouteTableDef()
ROUTES = routes  # alias for loaders that expect upper-case
ROUTE_TABLE = routes

# Internal base path. If gateway is mounted under "/gateway", external path is "/gateway" + BASE_PATH.
BASE_PATH = "/openai-compat"

# Common external base path we advertise in schema/docs (works if mounted under /gateway).
GATEWAY_BASE_PATH = "/gateway/openai-compat"

_SESSION_KEY = web.AppKey("p139_openai_compat_client_session", dict)


# -----------------------------
# Helpers
# -----------------------------


def _first_env(*names: str) -> str | None:
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return None


def _truthy(val: Any) -> bool:
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in {"1", "true", "yes", "y", "on"}


def _as_mapping(obj: Any) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return cast(Mapping[str, Any], obj)
    return None


def _get_app_cfg(request: web.Request) -> Mapping[str, Any]:
    for key in ("gateway_openai_compat", "openai_compat", "config", "settings"):
        val = request.app.get(key)
        m = _as_mapping(val)
        if m is not None:
            return m
    return {}


class _RouteProblem(Exception):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        message: str,
        type_: str,
        param: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.type_ = type_
        self.param = param


def _error_response(problem: _RouteProblem) -> web.Response:
    payload: OpenAICompatErrorResponse = {
        "error": {
            "message": problem.message,
            "type": problem.type_,
            "param": problem.param,
            "code": problem.code,
        }
    }
    return web.json_response(payload, status=problem.status)


def _join_upstream(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    # If base_url already ends in /v1, avoid double /v1.
    if base.endswith("/v1") and path.startswith("/v1/"):
        return base + path[len("/v1") :]
    return base + path


def _load_config(request: web.Request) -> OpenAICompatConfig:
    app_cfg = _get_app_cfg(request)

    base_url = (
        app_cfg.get("base_url")
        or app_cfg.get("openai_base_url")
        or _first_env("THOMAS_GATEWAY_OPENAI_BASE_URL", "THOMAS_OPENAI_BASE_URL")
    )
    api_key = (
        app_cfg.get("api_key")
        or app_cfg.get("openai_api_key")
        or _first_env("THOMAS_GATEWAY_OPENAI_API_KEY", "THOMAS_OPENAI_API_KEY")
    )

    allow_no_key = app_cfg.get("allow_no_key")
    if allow_no_key is None:
        allow_no_key = _first_env(
            "THOMAS_GATEWAY_OPENAI_ALLOW_NO_KEY",
            "THOMAS_OPENAI_ALLOW_NO_KEY",
        )
    allow_no_key_bool = _truthy(allow_no_key)

    timeout_s_val = (
        app_cfg.get("timeout_s")
        or app_cfg.get("timeout")
        or _first_env("THOMAS_GATEWAY_OPENAI_TIMEOUT_S", "THOMAS_OPENAI_TIMEOUT_S")
    )
    timeout_s = 30.0
    if timeout_s_val is not None:
        try:
            timeout_s = float(timeout_s_val)
        except (TypeError, ValueError):
            # Bad timeout config is normalized to default deterministically.
            timeout_s = 30.0

    # Allow per-request Authorization header to supply the key if config is absent.
    auth_hdr = request.headers.get("Authorization")
    if not api_key and auth_hdr and auth_hdr.lower().startswith("bearer "):
        api_key = auth_hdr.split(" ", 1)[1].strip() or None

    if not base_url or not isinstance(base_url, str):
        raise _RouteProblem(
            status=503,
            code="thomas_missing_openai_base_url",
            message="Missing upstream base URL for OpenAI-compatible proxy.",
            type_="configuration_error",
        )

    base_url = base_url.strip()
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise _RouteProblem(
            status=400,
            code="thomas_invalid_openai_base_url",
            message="Upstream base URL must start with http:// or https://",
            type_="invalid_request_error",
            param="base_url",
        )

    if not api_key and not allow_no_key_bool:
        raise _RouteProblem(
            status=503,
            code="thomas_missing_openai_api_key",
            message=(
                "Missing API key for OpenAI-compatible proxy. Set THOMAS_GATEWAY_OPENAI_API_KEY "
                "or supply an Authorization: Bearer ... header."
            ),
            type_="configuration_error",
        )

    return OpenAICompatConfig(
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        allow_no_key=allow_no_key_bool,
    )


async def _read_json(request: web.Request) -> Mapping[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise _RouteProblem(
            status=400,
            code="thomas_invalid_json",
            message="Request body must be valid JSON.",
            type_="invalid_request_error",
        )
    except Exception:
        raise _RouteProblem(
            status=400,
            code="thomas_invalid_json",
            message="Request body must be JSON.",
            type_="invalid_request_error",
        )

    if not isinstance(body, Mapping):
        raise _RouteProblem(
            status=400,
            code="thomas_invalid_request",
            message="JSON body must be an object.",
            type_="invalid_request_error",
        )
    return cast(Mapping[str, Any], body)


def _get_or_create_session(app: web.Application, timeout_s: float) -> ClientSession:
    holder = app.get(_SESSION_KEY)
    if isinstance(holder, dict):
        sess = holder.get("session")
        if isinstance(sess, ClientSession) and not sess.closed:
            return sess
        timeout = ClientTimeout(total=timeout_s)
        sess = ClientSession(timeout=timeout)
        holder["session"] = sess
        return sess
    if isinstance(holder, ClientSession) and not holder.closed:
        return holder
    # Fallback for unexpected app state: return a one-off session.
    return ClientSession(timeout=ClientTimeout(total=timeout_s))


async def _close_session(app: web.Application) -> None:
    holder = app.get(_SESSION_KEY)
    if isinstance(holder, dict):
        sess = holder.get("session")
        if isinstance(sess, ClientSession) and not sess.closed:
            await sess.close()
        holder["session"] = None
        return
    if isinstance(holder, ClientSession) and not holder.closed:
        await holder.close()


def get_route_schema() -> OpenAICompatRouteSchema:
    """Return machine-readable schema/introspection for automation."""
    return {
        "id": "gateway.openai_compat",
        "title": "OpenAI-compatible gateway proxy",
        "description": (
            "Thin compatibility layer that proxies OpenAI-style endpoints to an upstream "
            "OpenAI-compatible provider. Includes deterministic error envelopes and a schema endpoint."
        ),
        "routes": [
            {
                "method": "GET",
                "path": f"{GATEWAY_BASE_PATH}/schema",
                "alt_paths": [f"{BASE_PATH}/schema"],
                "description": "Return this schema document.",
            },
            {
                "method": "GET",
                "path": f"{GATEWAY_BASE_PATH}/health",
                "alt_paths": [f"{BASE_PATH}/health"],
                "description": "Return basic readiness info (does not call upstream).",
            },
            {
                "method": "POST",
                "path": f"{GATEWAY_BASE_PATH}/v1/chat/completions",
                "alt_paths": [f"{BASE_PATH}/v1/chat/completions"],
                "description": "Proxy to upstream /v1/chat/completions (JSON + SSE).",
                "request": {
                    "type": "object",
                    "required": ["model", "messages"],
                    "properties": {
                        "model": {"type": "string"},
                        "messages": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["role"],
                                "properties": {"role": {"type": "string"}, "content": {}},
                                "additionalProperties": True,
                            },
                        },
                        "stream": {"type": "boolean"},
                    },
                    "additionalProperties": True,
                },
                "response": {"type": "object", "description": "Upstream OpenAI-compatible response body."},
                "errors": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "required": ["message", "type", "code"],
                            "properties": {
                                "message": {"type": "string"},
                                "type": {"type": "string"},
                                "param": {"type": ["string", "null"]},
                                "code": {"type": "string"},
                            },
                        }
                    },
                },
            },
        ],
        "config": {
            "sources": [
                "app[gateway_openai_compat] mapping",
                "app[config]/app[settings] mapping (best-effort)",
                "environment variables",
            ],
            "env": {
                "THOMAS_GATEWAY_OPENAI_BASE_URL": {
                    "required": True,
                    "description": "Upstream base URL, e.g. https://api.openai.com",
                },
                "THOMAS_GATEWAY_OPENAI_API_KEY": {
                    "required": False,
                    "description": "API key; can also be supplied via Authorization header.",
                },
                "THOMAS_GATEWAY_OPENAI_TIMEOUT_S": {
                    "required": False,
                    "default": 30,
                    "description": "Upstream request timeout in seconds.",
                },
                "THOMAS_GATEWAY_OPENAI_ALLOW_NO_KEY": {
                    "required": False,
                    "default": 0,
                    "description": "Set to 1/true to allow missing API key.",
                },
            },
        },
    }


def get_config_for_cli() -> dict[str, Any]:
    cfg = OpenAICompatConfig(
        base_url=_first_env("THOMAS_GATEWAY_OPENAI_BASE_URL", "THOMAS_OPENAI_BASE_URL") or "",
        api_key=_first_env("THOMAS_GATEWAY_OPENAI_API_KEY", "THOMAS_OPENAI_API_KEY"),
        timeout_s=float(_first_env("THOMAS_GATEWAY_OPENAI_TIMEOUT_S", "THOMAS_OPENAI_TIMEOUT_S") or 30),
        allow_no_key=_truthy(_first_env("THOMAS_GATEWAY_OPENAI_ALLOW_NO_KEY", "THOMAS_OPENAI_ALLOW_NO_KEY")),
    )
    return asdict(cfg)


# -----------------------------
# Routes
# -----------------------------


@routes.get(f"{BASE_PATH}/schema")
async def schema_handler(request: web.Request) -> web.Response:
    return web.json_response(get_route_schema())


@routes.get(f"{BASE_PATH}/health")
async def health_handler(request: web.Request) -> web.Response:
    """Basic readiness info (no upstream call)."""
    try:
        cfg = _load_config(request)
    except _RouteProblem as p:
        return _error_response(p)

    return web.json_response(
        {
            "ok": True,
            "upstream_base_url": cfg.base_url,
            "has_api_key": bool(cfg.api_key),
            "timeout_s": cfg.timeout_s,
            "allow_no_key": cfg.allow_no_key,
        }
    )


@routes.post(f"{BASE_PATH}/v1/chat/completions")
async def chat_completions_handler(request: web.Request) -> web.StreamResponse:
    try:
        cfg = _load_config(request)
        body = await _read_json(request)

        # Minimal request validation.
        if "model" not in body or not isinstance(body.get("model"), str) or not body.get("model"):
            raise _RouteProblem(
                status=400,
                code="thomas_missing_model",
                message="Missing required field 'model'.",
                type_="invalid_request_error",
                param="model",
            )
        messages = body.get("messages")
        if not isinstance(messages, list):
            raise _RouteProblem(
                status=400,
                code="thomas_missing_messages",
                message="Missing required field 'messages'.",
                type_="invalid_request_error",
                param="messages",
            )

        upstream_url = _join_upstream(cfg.base_url, "/v1/chat/completions")

        # Forward headers except hop-by-hop. Rebuild Authorization if we have a key.
        fwd_headers: MutableMapping[str, str] = {}
        for k, v in request.headers.items():
            lk = k.lower()
            if lk in {"host", "content-length", "transfer-encoding", "connection"}:
                continue
            if lk == "authorization":
                # We'll set below if cfg.api_key exists; otherwise preserve original header.
                continue
            fwd_headers[k] = v

        if cfg.api_key:
            fwd_headers["Authorization"] = f"Bearer {cfg.api_key}"
        else:
            auth_hdr = request.headers.get("Authorization")
            if auth_hdr:
                fwd_headers["Authorization"] = auth_hdr

        session = _get_or_create_session(request.app, cfg.timeout_s)
        async with session.post(upstream_url, json=dict(body), headers=fwd_headers) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")

            # SSE stream pass-through
            if content_type.startswith("text/event-stream"):
                stream_resp = web.StreamResponse(status=status)
                stream_resp.headers["Content-Type"] = content_type
                await stream_resp.prepare(request)
                async for chunk in resp.content.iter_chunked(8192):
                    await stream_resp.write(chunk)
                await stream_resp.write_eof()
                return stream_resp

            # JSON response
            try:
                data = await resp.json()
            except Exception:
                text = await resp.text()
                raise _RouteProblem(
                    status=502,
                    code="thomas_upstream_invalid_response",
                    message=("Upstream returned a non-JSON response (status " f"{status}). Body: {text[:200]}"),
                    type_="upstream_error",
                )

            if status >= 400:
                if isinstance(data, Mapping) and "error" in data:
                    return web.json_response(data, status=status)
                raise _RouteProblem(
                    status=502,
                    code="thomas_upstream_error",
                    message=f"Upstream error (status {status}).",
                    type_="upstream_error",
                )

            return web.json_response(data, status=status)

    except _RouteProblem as p:
        return _error_response(p)
    except (asyncio.TimeoutError, ClientError) as e:
        return _error_response(
            _RouteProblem(
                status=502,
                code="thomas_upstream_unreachable",
                message=f"Upstream request failed: {e.__class__.__name__}.",
                type_="upstream_error",
            )
        )


# -----------------------------
# Registration helpers
# -----------------------------


def register(app: web.Application) -> None:
    """Register routes + cleanup hook onto an aiohttp app."""
    if app.get(_SESSION_KEY) is None:
        app[_SESSION_KEY] = {"session": None}
    elif isinstance(app.get(_SESSION_KEY), ClientSession):
        app[_SESSION_KEY] = {"session": app.get(_SESSION_KEY)}
    app.add_routes(routes)

    # Ensure we clean up any shared session.
    async def _cleanup_ctx(app_: web.Application):
        yield
        await _close_session(app_)

    app.cleanup_ctx.append(_cleanup_ctx)
