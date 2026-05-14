from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, Union, cast
from urllib.parse import urlparse

from aiohttp import ClientError, ClientSession, ClientTimeout, web

PROMPT_ID = "p140"
PROMPT_NAME = "openai_chat_completions_non_stream"

# OpenAI-compatible endpoint this prompt implements.
OPENAI_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

# Thomas-specific alias path kept stable for automation / prompt-pack parity.
THOMAS_GATEWAY_ALIAS_PATH = "/gateway/p140/openai/chat-completions-non-stream"

# Schema endpoint for automation.
THOMAS_SCHEMA_PATH = "/gateway/p140/openai/chat-completions-non-stream/schema"


# ----------------------------
# Contracts
# ----------------------------

OpenAIChatRole = Literal["system", "user", "assistant", "tool", "developer"]


class OpenAIChatMessage(TypedDict, total=False):
    role: OpenAIChatRole
    # OpenAI allows string or structured content; we accept any JSON value.
    content: Any
    name: str
    tool_call_id: str


class OpenAIChatCompletionsRequest(TypedDict, total=False):
    model: str
    messages: list[OpenAIChatMessage]
    stream: bool

    # Common optional parameters (we pass through unknown keys too).
    temperature: float
    top_p: float
    max_tokens: int
    n: int
    stop: Union[str, list[str]]
    presence_penalty: float
    frequency_penalty: float
    user: str


class OpenAIErrorObject(TypedDict, total=False):
    message: str
    type: str
    param: str | None
    code: str | None


class OpenAIErrorResponse(TypedDict):
    error: OpenAIErrorObject


# JSON Schemas (machine-readable contracts) for automation.
REQUEST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["model", "messages"],
    "properties": {
        "model": {"type": "string", "minLength": 1},
        "messages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["role"],
                "properties": {
                    "role": {"type": "string"},
                    "content": {},
                    "name": {"type": "string"},
                    "tool_call_id": {"type": "string"},
                },
                "additionalProperties": True,
            },
        },
        "stream": {"type": "boolean", "enum": [False]},
    },
    "additionalProperties": True,
}

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "oneOf": [
        # Success response is OpenAI-defined; we don't over-constrain it.
        {"type": "object", "additionalProperties": True},
        # Error response matches OpenAI error envelope.
        {
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
                    "additionalProperties": True,
                }
            },
            "additionalProperties": True,
        },
    ]
}


# ----------------------------
# Config
# ----------------------------


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    base_url: str
    timeout_s: float = 30.0
    organization: str | None = None


def _get_env(name: str) -> str | None:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _coalesce(*values: str | None) -> str | None:
    for v in values:
        if v:
            return v
    return None


def _extract_dict(d: Any) -> dict[str, Any]:
    if isinstance(d, dict):
        return cast(dict[str, Any], d)
    return {}


def resolve_openai_config(app: web.Application | None = None) -> Union[OpenAIConfig, OpenAIErrorResponse]:
    """
    Resolve OpenAI client config.

    Deterministic precedence:
    1) Env vars (OPENAI_*, THOMAS_OPENAI_*)
    2) app["config"]/ ["settings"]/ ["cfg"] dict (optionally nested under "openai")
    """

    cfg: dict[str, Any] = {}
    if app is not None:
        for key in ("config", "settings", "cfg"):
            if key in app:
                cfg = _extract_dict(app.get(key))
                if cfg:
                    break
        openai_cfg = cfg.get("openai")
        if isinstance(openai_cfg, dict):
            cfg = cast(dict[str, Any], openai_cfg)

    api_key = _coalesce(
        _get_env("OPENAI_API_KEY"),
        _get_env("THOMAS_OPENAI_API_KEY"),
        cast(str | None, cfg.get("api_key")),
        cast(str | None, cfg.get("openai_api_key")),
        cast(str | None, cfg.get("OPENAI_API_KEY")),
    )

    base_url = _coalesce(
        _get_env("OPENAI_BASE_URL"),
        _get_env("OPENAI_API_BASE"),
        _get_env("THOMAS_OPENAI_BASE_URL"),
        cast(str | None, cfg.get("base_url")),
        cast(str | None, cfg.get("openai_base_url")),
        cast(str | None, cfg.get("OPENAI_BASE_URL")),
    ) or "https://api.openai.com/v1"

    timeout_s_raw = _coalesce(
        _get_env("OPENAI_TIMEOUT_S"),
        _get_env("THOMAS_OPENAI_TIMEOUT_S"),
        cast(str | None, cfg.get("timeout_s")),
        cast(str | None, cfg.get("timeout_seconds")),
    )

    organization = _coalesce(
        _get_env("OPENAI_ORG_ID"),
        _get_env("OPENAI_ORGANIZATION"),
        cast(str | None, cfg.get("organization")),
        cast(str | None, cfg.get("org_id")),
    )

    timeout_s: float = 30.0
    if timeout_s_raw is not None:
        try:
            timeout_s = float(timeout_s_raw)
        except ValueError:
            timeout_s = 30.0

    if not api_key:
        return _error(
            message="OpenAI API key is not configured on this server.",
            error_type="server_error",
            code="missing_openai_api_key",
            param=None,
        )

    try:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("invalid scheme")
        if not parsed.netloc:
            raise ValueError("missing host")
    except Exception:
        return _error(
            message="OpenAI base URL is invalid or misconfigured.",
            error_type="server_error",
            code="invalid_openai_base_url",
            param=None,
        )

    return OpenAIConfig(api_key=api_key, base_url=base_url, timeout_s=timeout_s, organization=organization)


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


# ----------------------------
# Error helpers (OpenAI-shaped)
# ----------------------------


def _error(
    *,
    message: str,
    error_type: str,
    code: str | None = None,
    param: str | None = None,
) -> OpenAIErrorResponse:
    return {
        "error": {
            "message": message,
            "type": error_type,
            "param": param,
            "code": code,
        }
    }


def _json_error_response(err: OpenAIErrorResponse, *, status: int) -> web.Response:
    return web.json_response(err, status=status)


# ----------------------------
# Input validation
# ----------------------------


def validate_request(payload: Any) -> Union[OpenAIChatCompletionsRequest, OpenAIErrorResponse]:
    if not isinstance(payload, dict):
        return _error(
            message="Request body must be a JSON object.",
            error_type="invalid_request_error",
            code="invalid_json",
        )

    obj = cast(dict[str, Any], payload)

    model = obj.get("model")
    if not isinstance(model, str) or not model.strip():
        return _error(
            message="Missing required field: 'model'.",
            error_type="invalid_request_error",
            code="missing_required_field",
            param="model",
        )

    messages = obj.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error(
            message="Missing required field: 'messages' (must be a non-empty array).",
            error_type="invalid_request_error",
            code="missing_required_field",
            param="messages",
        )

    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            return _error(
                message=f"messages[{i}] must be an object.",
                error_type="invalid_request_error",
                code="invalid_message",
                param="messages",
            )
        role = m.get("role")
        if not isinstance(role, str) or not role.strip():
            return _error(
                message=f"messages[{i}].role is required.",
                error_type="invalid_request_error",
                code="invalid_message",
                param="messages",
            )

    stream = obj.get("stream")
    if stream is True:
        return _error(
            message="This endpoint supports non-stream responses only. Set 'stream' to false or omit it.",
            error_type="invalid_request_error",
            code="stream_not_supported",
            param="stream",
        )

    normalized = dict(obj)
    normalized["stream"] = False
    return cast(OpenAIChatCompletionsRequest, normalized)


# ----------------------------
# Outbound call
# ----------------------------


async def _call_openai_chat_completions(
    *,
    req: OpenAIChatCompletionsRequest,
    cfg: OpenAIConfig,
) -> web.Response:
    url = _chat_completions_url(cfg.base_url)
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if cfg.organization:
        headers["OpenAI-Organization"] = cfg.organization

    timeout = ClientTimeout(total=cfg.timeout_s)

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.post(url, json=req, headers=headers) as resp:
                raw = await resp.read()
                content_type = (resp.headers.get("Content-Type") or "").lower()

                looks_like_json = (
                    "application/json" in content_type
                    or raw.lstrip().startswith(b"{")
                    or raw.lstrip().startswith(b"[")
                )

                if looks_like_json:
                    try:
                        parsed = json.loads(raw.decode("utf-8"))
                        return web.json_response(parsed, status=resp.status)
                    except Exception:
                        err = _error(
                            message="Upstream OpenAI returned invalid JSON.",
                            error_type="upstream_error",
                            code="upstream_invalid_json",
                        )
                        return _json_error_response(err, status=502)

                if resp.status >= 400:
                    err = _error(
                        message="Upstream OpenAI error returned a non-JSON response.",
                        error_type="upstream_error",
                        code="upstream_non_json_error",
                    )
                    return _json_error_response(err, status=502)

                err = _error(
                    message="Upstream OpenAI returned a non-JSON response.",
                    error_type="upstream_error",
                    code="upstream_non_json_success",
                )
                return _json_error_response(err, status=502)

    except asyncio.TimeoutError:
        err = _error(
            message="Upstream OpenAI request timed out.",
            error_type="upstream_error",
            code="upstream_timeout",
        )
        return _json_error_response(err, status=504)
    except ClientError:
        err = _error(
            message="Failed to reach upstream OpenAI service.",
            error_type="upstream_error",
            code="upstream_unreachable",
        )
        return _json_error_response(err, status=502)


# ----------------------------
# Routes
# ----------------------------

routes = web.RouteTableDef()


@routes.get(THOMAS_SCHEMA_PATH)
async def p140_schema(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "prompt_id": PROMPT_ID,
            "name": PROMPT_NAME,
            "paths": {
                "openai": OPENAI_CHAT_COMPLETIONS_PATH,
                "alias": THOMAS_GATEWAY_ALIAS_PATH,
                "schema": THOMAS_SCHEMA_PATH,
            },
            "request_schema": REQUEST_JSON_SCHEMA,
            "response_schema": RESPONSE_JSON_SCHEMA,
        }
    )


@routes.post(OPENAI_CHAT_COMPLETIONS_PATH)
async def openai_chat_completions_non_stream(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except Exception:
        err = _error(
            message="Request body must be valid JSON.",
            error_type="invalid_request_error",
            code="invalid_json",
        )
        return _json_error_response(err, status=400)

    validated = validate_request(payload)
    if isinstance(validated, dict) and "error" in validated:
        return _json_error_response(cast(OpenAIErrorResponse, validated), status=400)

    cfg_or_err = resolve_openai_config(request.app)
    if isinstance(cfg_or_err, dict) and "error" in cfg_or_err:
        return _json_error_response(cast(OpenAIErrorResponse, cfg_or_err), status=500)

    cfg = cast(OpenAIConfig, cfg_or_err)
    req_obj = cast(OpenAIChatCompletionsRequest, validated)
    return await _call_openai_chat_completions(req=req_obj, cfg=cfg)


@routes.post(THOMAS_GATEWAY_ALIAS_PATH)
async def p140_alias(request: web.Request) -> web.StreamResponse:
    return await openai_chat_completions_non_stream(request)


# Alternate export styles for route discovery across the codebase.
ROUTES = routes
ROUTE_DEFS = [
    web.get(THOMAS_SCHEMA_PATH, p140_schema),
    web.post(OPENAI_CHAT_COMPLETIONS_PATH, openai_chat_completions_non_stream),
    web.post(THOMAS_GATEWAY_ALIAS_PATH, p140_alias),
]


def register(app: web.Application) -> None:
    """Register routes on an aiohttp Application."""
    app.add_routes(routes)


def setup(app: web.Application) -> None:
    """Alias for register()."""
    register(app)
