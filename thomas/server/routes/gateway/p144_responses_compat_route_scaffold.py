"""
Responses-compatibility route scaffold (gateway).

This module provides an OpenAI-style `/v1/responses` endpoint as a compatibility
surface for clients. It is deliberately Thomas-native (no reuse of external
project naming), but mirrors the high-level HTTP shapes for interop.

Key goals:
- Deterministic validation and error envelopes.
- Two execution modes:
  - stub: local deterministic echo implementation (default when no upstream).
  - proxy: forward to an upstream base URL at `{base}/v1/responses`.
- Machine-readable schema for automation: `GET /v1/responses/schema`.

Environment variables:
- THOMAS_RESPONSES_COMPAT_MODE: auto|stub|proxy
- THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL: http(s)://host:port (no trailing /)
- THOMAS_RESPONSES_COMPAT_TIMEOUT_S: float seconds (default 30)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Literal, TypedDict, Union, cast

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout, web

# -----------------------------
# Contracts (minimal subset)
# -----------------------------


class ResponsesCompatTextInput(TypedDict, total=False):
    type: Literal["input_text"]
    text: str


class ResponsesCompatMessageInput(TypedDict, total=False):
    role: Literal["user", "system", "assistant", "developer"]
    content: str | Sequence[ResponsesCompatTextInput]


ResponsesCompatInput = Union[str, Sequence[ResponsesCompatTextInput | ResponsesCompatMessageInput]]


class ResponsesCompatCreateRequest(TypedDict, total=False):
    model: str
    input: ResponsesCompatInput
    stream: bool
    metadata: Mapping[str, Any]


class ResponsesCompatOutputText(TypedDict):
    type: Literal["output_text"]
    text: str


class ResponsesCompatOutputMessage(TypedDict):
    id: str
    type: Literal["message"]
    role: Literal["assistant"]
    content: list[ResponsesCompatOutputText]


class ResponsesCompatUsage(TypedDict, total=False):
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ResponsesCompatCreateResponse:
    id: str
    object: Literal["response"]
    created_at: int
    model: str
    status: Literal["completed"]
    output: list[ResponsesCompatOutputMessage]
    usage: ResponsesCompatUsage
    metadata: Mapping[str, Any] | None = None


class ErrorObject(TypedDict, total=False):
    message: str
    type: str
    param: str | None
    code: str | None


class ErrorEnvelope(TypedDict):
    error: ErrorObject


class GatewayError(Exception):
    """Deterministic HTTP error for this route."""

    def __init__(
        self,
        *,
        status: int,
        message: str,
        error_type: str = "invalid_request_error",
        param: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.error_type = error_type
        self.param = param
        self.code = code


# -----------------------------
# Configuration helpers
# -----------------------------


_ENV_MODE = "THOMAS_RESPONSES_COMPAT_MODE"
_ENV_UPSTREAM = "THOMAS_RESPONSES_COMPAT_UPSTREAM_BASE_URL"
_ENV_TIMEOUT_S = "THOMAS_RESPONSES_COMPAT_TIMEOUT_S"

# Shared env-var fallbacks (common in gateways).
_FALLBACK_UPSTREAM_ENV_VARS: tuple[str, ...] = (
    "THOMAS_GATEWAY_UPSTREAM_BASE_URL",
    "THOMAS_UPSTREAM_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
)

_FALLBACK_API_KEY_ENV_VARS: tuple[str, ...] = (
    "THOMAS_GATEWAY_API_KEY",
    "OPENAI_API_KEY",
)


def _get_mode(app: web.Application) -> str:
    mode = os.getenv(_ENV_MODE) or cast(str | None, app.get("responses_compat_mode"))
    if mode:
        m = str(mode).strip().lower()
        if m in ("auto", "stub", "proxy"):
            return m
        # Keep deterministic behavior for bad config.
        return "auto"
    return "auto"


def _resolve_upstream_base_url(app: web.Application) -> str | None:
    val = os.getenv(_ENV_UPSTREAM) or cast(str | None, app.get("responses_compat_upstream_base_url"))
    if val:
        return str(val).rstrip("/")

    for name in _FALLBACK_UPSTREAM_ENV_VARS:
        v = os.getenv(name)
        if v:
            return str(v).rstrip("/")

    config = app.get("config") or app.get("settings")
    if config is None:
        return None

    candidates: Sequence[tuple[str, ...]] = (
        ("gateway", "upstream_base_url"),
        ("gateway", "base_url"),
        ("openai", "base_url"),
        ("upstream_base_url",),
        ("base_url",),
    )

    def _dig(obj: Any, path: tuple[str, ...]) -> Any | None:
        cur = obj
        for key in path:
            if cur is None:
                return None
            if isinstance(cur, Mapping) and key in cur:
                cur = cur[key]
                continue
            if hasattr(cur, key):
                cur = getattr(cur, key)
                continue
            return None
        return cur

    for path in candidates:
        found = _dig(config, path)
        if found:
            return str(found).rstrip("/")
    return None


def _resolve_api_key(app: web.Application, request: web.Request) -> str | None:
    # Client-supplied auth takes priority.
    auth = request.headers.get("Authorization")
    if auth:
        return auth

    # App-level stored token.
    key_val = cast(str | None, app.get("gateway_api_key") or app.get("api_key"))
    if key_val:
        v = str(key_val)
        return v if v.lower().startswith("bearer ") else f"Bearer {v}"

    # Environment fallbacks.
    for name in _FALLBACK_API_KEY_ENV_VARS:
        v = os.getenv(name)
        if v:
            return v if v.lower().startswith("bearer ") else f"Bearer {v}"
    return None


def _resolve_timeout_s() -> float:
    raw = os.getenv(_ENV_TIMEOUT_S)
    if not raw:
        return 30.0
    try:
        val = float(raw)
    except ValueError:
        return 30.0
    return max(0.5, min(val, 300.0))


# -----------------------------
# JSON schema (machine-readable)
# -----------------------------


def get_json_schema() -> dict[str, Any]:
    request_schema: dict[str, Any] = {
        "type": "object",
        "required": ["model", "input"],
        "properties": {
            "model": {"type": "string", "minLength": 1},
            "input": {"anyOf": [{"type": "string"}, {"type": "array"}]},
            "stream": {"type": "boolean"},
            "metadata": {"type": "object"},
        },
        "additionalProperties": True,
    }
    response_schema: dict[str, Any] = {
        "type": "object",
        "required": ["id", "object", "created_at", "model", "status", "output"],
        "properties": {
            "id": {"type": "string"},
            "object": {"const": "response"},
            "created_at": {"type": "integer"},
            "model": {"type": "string"},
            "status": {"type": "string"},
            "output": {"type": "array"},
            "usage": {"type": "object"},
            "metadata": {"type": ["object", "null"]},
        },
        "additionalProperties": True,
    }
    error_schema: dict[str, Any] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["message", "type"],
                "properties": {
                    "message": {"type": "string"},
                    "type": {"type": "string"},
                    "param": {"type": ["string", "null"]},
                    "code": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            }
        },
        "additionalProperties": False,
    }
    return {
        "name": "responses_compat",
        "routes": [
            {"method": "POST", "path": "/v1/responses"},
            {"method": "GET", "path": "/v1/responses/schema"},
        ],
        "request_schema": request_schema,
        "response_schema": response_schema,
        "error_schema": error_schema,
        "modes": ["auto", "stub", "proxy"],
        "env": {"mode": _ENV_MODE, "upstream_base_url": _ENV_UPSTREAM, "timeout_s": _ENV_TIMEOUT_S},
    }


# -----------------------------
# Helpers
# -----------------------------


def _error_payload(exc: GatewayError) -> ErrorEnvelope:
    err: ErrorObject = {"message": exc.message, "type": exc.error_type, "param": exc.param, "code": exc.code}
    return {"error": err}


def _json_response(payload: Any, *, status: int = 200) -> web.Response:
    return web.json_response(
        payload, status=status, dumps=lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False)
    )


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raise GatewayError(status=400, message="Request body must be valid JSON.", code="invalid_json")
    except Exception:
        raise GatewayError(status=400, message="Request body must be JSON.", code="invalid_json")
    if not isinstance(data, dict):
        raise GatewayError(status=400, message="Request JSON body must be an object.", code="invalid_body")
    return cast(dict[str, Any], data)


def _validate_input_items(inp: Any) -> None:
    if isinstance(inp, str):
        return
    if not isinstance(inp, list):
        raise GatewayError(
            status=400, message="Field 'input' must be a string or array.", param="input", code="invalid_field"
        )
    for idx, item in enumerate(inp):
        if not isinstance(item, dict):
            raise GatewayError(
                status=400,
                message=f"Invalid input item at index {idx}: must be an object.",
                param="input",
                code="invalid_input_item",
            )
        # Two supported shapes: {type:"input_text",text:"..."} or {role:"user",content:...}
        if "type" in item:
            if item.get("type") != "input_text":
                raise GatewayError(
                    status=400,
                    message=f"Invalid input item at index {idx}: unsupported type.",
                    param="input",
                    code="invalid_input_item",
                )
            if not isinstance(item.get("text"), str):
                raise GatewayError(
                    status=400,
                    message=f"Invalid input item at index {idx}: 'text' must be a string.",
                    param="input",
                    code="invalid_input_item",
                )
        elif "role" in item:
            role = item.get("role")
            if role not in ("user", "system", "assistant", "developer"):
                raise GatewayError(
                    status=400,
                    message=f"Invalid message input at index {idx}: unsupported role.",
                    param="input",
                    code="invalid_input_item",
                )
            if "content" not in item:
                raise GatewayError(
                    status=400,
                    message=f"Invalid message input at index {idx}: missing content.",
                    param="input",
                    code="invalid_input_item",
                )
            content = item.get("content")
            if isinstance(content, str):
                continue
            if isinstance(content, list):
                for cidx, c in enumerate(content):
                    if not isinstance(c, dict) or c.get("type") != "input_text" or not isinstance(c.get("text"), str):
                        raise GatewayError(
                            status=400,
                            message=f"Invalid message content at index {idx}.{cidx}.",
                            param="input",
                            code="invalid_input_item",
                        )
            else:
                raise GatewayError(
                    status=400,
                    message=f"Invalid message content at index {idx}: must be string or array.",
                    param="input",
                    code="invalid_input_item",
                )
        else:
            raise GatewayError(
                status=400,
                message=f"Invalid input item at index {idx}: missing 'type' or 'role'.",
                param="input",
                code="invalid_input_item",
            )


def _validate_create_request(data: dict[str, Any]) -> ResponsesCompatCreateRequest:
    if "model" not in data:
        raise GatewayError(status=400, message="Missing required field: model", param="model", code="missing_field")
    if not isinstance(data["model"], str) or not data["model"].strip():
        raise GatewayError(
            status=400, message="Field 'model' must be a non-empty string.", param="model", code="invalid_field"
        )

    if "input" not in data:
        raise GatewayError(status=400, message="Missing required field: input", param="input", code="missing_field")
    _validate_input_items(data["input"])

    if "stream" in data and not isinstance(data["stream"], bool):
        raise GatewayError(
            status=400, message="Field 'stream' must be a boolean.", param="stream", code="invalid_field"
        )

    if "metadata" in data and not isinstance(data["metadata"], Mapping):
        raise GatewayError(
            status=400, message="Field 'metadata' must be an object.", param="metadata", code="invalid_field"
        )

    return cast(ResponsesCompatCreateRequest, data)


def _extract_plain_text(inp: ResponsesCompatInput) -> str:
    if isinstance(inp, str):
        return inp
    if not inp:
        return ""
    for item in inp:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "input_text" and isinstance(item.get("text"), str):
            return cast(str, item["text"])
        if "content" in item:
            content = item.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "input_text" and isinstance(c.get("text"), str):
                        return cast(str, c["text"])
    return ""


def _build_stub_response(req: ResponsesCompatCreateRequest) -> ResponsesCompatCreateResponse:
    now = int(time.time())
    resp_id = f"resp_{uuid.uuid4().hex}"
    msg_id = f"msg_{uuid.uuid4().hex}"
    text = _extract_plain_text(req["input"])
    output: ResponsesCompatOutputMessage = {
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }
    usage: ResponsesCompatUsage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    metadata = req.get("metadata")
    return ResponsesCompatCreateResponse(
        id=resp_id,
        object="response",
        created_at=now,
        model=req["model"],
        status="completed",
        output=[output],
        usage=usage,
        metadata=metadata if metadata is not None else None,
    )


async def _read_upstream_json(resp: ClientResponse) -> Mapping[str, Any]:
    try:
        data = await resp.json()
    except Exception:
        await resp.text()
        raise GatewayError(
            status=502,
            message=f"Upstream returned non-JSON response (status={resp.status}).",
            error_type="upstream_error",
            code="upstream_non_json",
        ) from None
    if not isinstance(data, dict):
        raise GatewayError(
            status=502,
            message=f"Upstream returned invalid JSON object (status={resp.status}).",
            error_type="upstream_error",
            code="upstream_invalid_json",
        )
    return cast(Mapping[str, Any], data)


async def _proxy_to_upstream(
    *, request: web.Request, upstream_base_url: str, payload: dict[str, Any]
) -> tuple[int, Mapping[str, Any]]:
    url = f"{upstream_base_url}/v1/responses"
    timeout = ClientTimeout(total=_resolve_timeout_s())

    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    auth = _resolve_api_key(request.app, request)
    if auth:
        headers["Authorization"] = auth

    session = request.app.get("http_session")
    close_session = False
    if isinstance(session, ClientSession) and not session.closed:
        client = session
    else:
        client = ClientSession(timeout=timeout)
        close_session = True

    try:
        async with client.post(url, json=payload, headers=headers) as resp:
            status = resp.status
            data = await _read_upstream_json(resp)
            return status, data
    except ClientError as e:
        raise GatewayError(
            status=502,
            message=f"Upstream request failed: {e.__class__.__name__}",
            error_type="upstream_error",
            code="upstream_request_failed",
        )
    finally:
        if close_session:
            await client.close()


# -----------------------------
# HTTP handlers
# -----------------------------


async def handle_schema(request: web.Request) -> web.Response:
    return _json_response(get_json_schema())


async def handle_create(request: web.Request) -> web.Response:
    try:
        data = await _read_json_object(request)
        req = _validate_create_request(data)

        if req.get("stream") is True:
            # Streaming can be added later (SSE). For now, keep behavior deterministic.
            raise GatewayError(
                status=400,
                message="Streaming is not supported by this endpoint scaffold.",
                param="stream",
                code="not_supported",
            )

        mode = _get_mode(request.app)
        upstream_base_url = _resolve_upstream_base_url(request.app)

        should_proxy = (mode == "proxy") or (mode == "auto" and bool(upstream_base_url))
        if should_proxy:
            if not upstream_base_url:
                raise GatewayError(
                    status=500,
                    message="Upstream base URL is not configured for responses proxying.",
                    error_type="configuration_error",
                    code="missing_config",
                )
            status, upstream_json = await _proxy_to_upstream(
                request=request,
                upstream_base_url=upstream_base_url,
                payload=data,
            )
            # If upstream returns OpenAI-style errors, pass through.
            if status >= 400 and "error" not in upstream_json:
                raise GatewayError(
                    status=502,
                    message=f"Upstream returned error status={status} without an error body.",
                    error_type="upstream_error",
                    code="upstream_http_error",
                )
            return _json_response(dict(upstream_json), status=status)

        # Default stub behavior.
        stub = _build_stub_response(req)
        return _json_response(asdict(stub))

    except GatewayError as exc:
        return _json_response(_error_payload(exc), status=exc.status)


# -----------------------------
# Route registration
# -----------------------------


ROUTES: list[web.RouteDef] = [
    web.post("/v1/responses", handle_create),
    web.get("/v1/responses/schema", handle_schema),
]

ROUTE_SPECS: list[tuple[str, str, Any]] = [
    ("POST", "/v1/responses", handle_create),
    ("GET", "/v1/responses/schema", handle_schema),
]


def routes() -> list[web.RouteDef]:
    return ROUTES


def register(app: web.Application) -> None:
    app.router.add_routes(ROUTES)


register_routes = register
get_routes = routes
