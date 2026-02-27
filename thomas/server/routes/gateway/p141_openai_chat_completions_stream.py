"""Gateway route: OpenAI Chat Completions with streaming support.

This implements a Thomas-native gateway endpoint that proxies the upstream
OpenAI Chat Completions streaming API (SSE).

Key behaviors:
- Validates minimal request contract (model + messages).
- Resolves config from app config (if present) or env vars.
- Deterministic JSON errors on invalid input / missing config / upstream failure.
- Streams SSE from upstream to the client with minimal transformation.

Note: The upstream streaming format is the OpenAI SSE shape.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, TypedDict

from aiohttp import ClientConnectorError, ClientResponse, ClientSession, ClientTimeout, web

# ----------------------------
# Contracts
# ----------------------------


class OpenAIChatMessage(TypedDict, total=False):
    role: str
    content: Any
    name: str
    tool_call_id: str


class OpenAIChatCompletionsRequest(TypedDict, total=False):
    """Subset of OpenAI Chat Completions request fields.

    We validate and require:
      - model: str
      - messages: list[OpenAIChatMessage]

    Any additional keys are forwarded to the upstream API.
    """

    model: str
    messages: list[OpenAIChatMessage]
    stream: bool


class ThomasGatewayErrorPayload(TypedDict):
    ok: bool
    error: dict[str, Any]


@dataclass(frozen=True)
class _OpenAIConfig:
    api_key: str
    base_url: str
    timeout_s: float


# ----------------------------
# Errors
# ----------------------------


@dataclass(frozen=True)
class _GatewayError(Exception):
    status: int
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_payload(self) -> ThomasGatewayErrorPayload:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"ok": False, "error": err}


def _json_error(err: _GatewayError) -> web.Response:
    return web.json_response(err.to_payload(), status=err.status)


# ----------------------------
# Config
# ----------------------------


def _maybe_get_mapping(obj: Any) -> Mapping[str, Any] | None:
    return obj if isinstance(obj, Mapping) else None


def _resolve_openai_config(request: web.Request) -> _OpenAIConfig:
    """Resolve OpenAI config with a predictable precedence.

    Precedence:
    1) request.app['config'] (common in aiohttp apps) for keys:
       - openai.api_key / openai.base_url / openai.timeout_s
       - or OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_TIMEOUT_S (string keys)
    2) Environment variables: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_TIMEOUT_S

    This indirection keeps the route compatible across Thomas config shapes.
    """

    app_cfg = _maybe_get_mapping(request.app.get("config")) or {}
    openai_cfg = _maybe_get_mapping(app_cfg.get("openai")) or {}

    api_key = (
        openai_cfg.get("api_key")
        or openai_cfg.get("apiKey")
        or app_cfg.get("OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )

    base_url = (
        openai_cfg.get("base_url")
        or openai_cfg.get("baseUrl")
        or app_cfg.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )

    timeout_raw = (
        openai_cfg.get("timeout_s")
        or openai_cfg.get("timeout")
        or app_cfg.get("OPENAI_TIMEOUT_S")
        or os.environ.get("OPENAI_TIMEOUT_S")
        or 60
    )

    try:
        timeout_s = float(timeout_raw)
    except (TypeError, ValueError):
        timeout_s = 60.0

    if not api_key:
        raise _GatewayError(
            status=500,
            code="missing_config",
            message="Missing OpenAI API key (set OPENAI_API_KEY or app config openai.api_key).",
        )

    return _OpenAIConfig(api_key=str(api_key), base_url=str(base_url), timeout_s=timeout_s)


def _openai_chat_completions_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


# ----------------------------
# Request parsing
# ----------------------------


async def _read_json(request: web.Request) -> Any:
    try:
        return await request.json()
    except json.JSONDecodeError as e:
        raise _GatewayError(status=400, code="invalid_json", message="Body must be valid JSON.") from e
    except Exception as e:  # pragma: no cover
        # aiohttp may raise ContentTypeError etc.
        raise _GatewayError(status=400, code="invalid_json", message="Body must be JSON.") from e


def _validate_request_payload(payload: Any) -> tuple[OpenAIChatCompletionsRequest, bool]:
    if not isinstance(payload, MutableMapping):
        raise _GatewayError(status=400, code="invalid_request", message="Request JSON must be an object.")

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise _GatewayError(status=400, code="invalid_request", message="Missing required field: model (string).")

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise _GatewayError(
            status=400,
            code="invalid_request",
            message="Missing required field: messages (non-empty list).",
        )

    # Soft validation of each message shape.
    for i, msg in enumerate(messages):
        if not isinstance(msg, Mapping):
            raise _GatewayError(status=400, code="invalid_request", message=f"messages[{i}] must be an object.")
        role = msg.get("role")
        if role is None or not isinstance(role, str) or not role.strip():
            raise _GatewayError(status=400, code="invalid_request", message=f"messages[{i}].role is required.")
        # content can be str or structured (multimodal), but must exist
        if "content" not in msg:
            raise _GatewayError(status=400, code="invalid_request", message=f"messages[{i}].content is required.")

    stream = payload.get("stream")
    if stream is None:
        stream_bool = True
    elif isinstance(stream, bool):
        stream_bool = stream
    else:
        raise _GatewayError(status=400, code="invalid_request", message="stream must be a boolean when provided.")

    return payload, stream_bool


# ----------------------------
# Streaming proxy
# ----------------------------


async def _iter_sse_bytes(upstream: ClientResponse) -> AsyncIterator[bytes]:
    """Stream upstream bytes as-is (SSE passthrough)."""

    async for chunk in upstream.content.iter_any():
        yield chunk


def _make_sse_response() -> web.StreamResponse:
    return web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Helpful when behind nginx.
            "X-Accel-Buffering": "no",
        },
    )


async def _proxy_stream(*, request: web.Request, upstream: ClientResponse) -> web.StreamResponse:
    resp = _make_sse_response()
    await resp.prepare(request)

    try:
        async for chunk in _iter_sse_bytes(upstream):
            # Stop early if the client disconnected.
            if request.transport is None or request.transport.is_closing():
                break
            try:
                await resp.write(chunk)
            except ConnectionResetError:
                break
            # Yield occasionally to avoid starving the loop on tiny chunks.
            await asyncio.sleep(0)
    finally:
        try:
            await resp.write_eof()
        except ConnectionResetError:
            pass

    return resp


async def _call_openai(
    *, cfg: _OpenAIConfig, payload: Mapping[str, Any], stream: bool
) -> tuple[ClientSession, ClientResponse]:
    timeout = ClientTimeout(total=cfg.timeout_s)
    session = ClientSession(timeout=timeout)

    # Force stream setting based on requested mode.
    upstream_payload: dict[str, Any] = dict(payload)
    upstream_payload["stream"] = bool(stream)

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }

    url = _openai_chat_completions_url(cfg.base_url)

    try:
        resp = await session.post(url, headers=headers, json=upstream_payload)
    except asyncio.TimeoutError as e:
        await session.close()
        raise _GatewayError(status=504, code="upstream_timeout", message="Timed out calling upstream OpenAI.") from e
    except ClientConnectorError as e:
        await session.close()
        raise _GatewayError(
            status=502,
            code="upstream_unreachable",
            message="Failed to connect to upstream OpenAI.",
        ) from e
    except Exception as e:  # pragma: no cover
        await session.close()
        raise _GatewayError(status=502, code="upstream_error", message="Upstream OpenAI request failed.") from e

    return session, resp


# ----------------------------
# Routes
# ----------------------------


routes = web.RouteTableDef()


@routes.post("/gateway/p141/openai_chat_completions_stream")
@routes.post("/gateway/p141/openai-chat-completions-stream")
@routes.post("/gateway/openai/chat_completions/stream")
@routes.post("/gateway/openai/chat-completions/stream")
@routes.post("/gateway/openai/chat/completions/stream")
async def openai_chat_completions_stream(request: web.Request) -> web.StreamResponse:
    """Proxy OpenAI Chat Completions.

    If `stream` is true (default), proxies SSE to the client.
    If `stream` is false, returns the upstream JSON payload.
    """

    try:
        cfg = _resolve_openai_config(request)
        raw_payload = await _read_json(request)
        payload, stream = _validate_request_payload(raw_payload)

        session, upstream = await _call_openai(cfg=cfg, payload=payload, stream=stream)

        try:
            if not stream:
                try:
                    data = await upstream.json(content_type=None)
                except Exception as e:
                    raise _GatewayError(
                        status=502,
                        code="upstream_error",
                        message="Failed to parse upstream OpenAI JSON response.",
                        details={"error": str(e)},
                    ) from e
                if upstream.status >= 400:
                    raise _GatewayError(
                        status=502,
                        code="upstream_error",
                        message="Upstream OpenAI returned an error.",
                        details={"status": upstream.status, "body": data},
                    )
                return web.json_response(data, status=200)

            if upstream.status >= 400:
                try:
                    text = await upstream.text()
                except Exception as e:
                    raise _GatewayError(
                        status=502,
                        code="upstream_error",
                        message="Failed to read upstream OpenAI error response.",
                        details={"error": str(e)},
                    ) from e
                raise _GatewayError(
                    status=502,
                    code="upstream_error",
                    message="Upstream OpenAI returned an error.",
                    details={"status": upstream.status, "body": text},
                )

            return await _proxy_stream(request=request, upstream=upstream)

        finally:
            # Ensure upstream response and session are closed.
            try:
                await upstream.close()
            finally:
                await session.close()

    except _GatewayError as e:
        return _json_error(e)


def register(app: web.Application) -> None:
    """Optional registration hook.

    Some Thomas route loaders may look for a `register(app)` function.
    """

    app.add_routes(routes)
