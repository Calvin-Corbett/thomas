"""Thomas Gateway: Responses create (non-stream).

Implements a non-streaming variant of a "responses.create" style endpoint:
one request in, one JSON response out.

Integration surfaces (for differing loader styles in the Thomas server):
- `routes`: aiohttp RouteTableDef
- `ROUTES`: alias to `routes`
- `get_routes()`: list[RouteDef]
- `register_routes(app)`: imperative registration (duplicate-tolerant)

The core logic is exposed as `create_non_stream_response(...)` for unit tests.
"""

from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional, TypedDict
from collections.abc import Mapping, MutableMapping, Sequence

from aiohttp import web

JsonObject = MutableMapping[str, Any]


class ErrorDetails(TypedDict, total=False):
    message: str
    type: str
    code: str
    param: str | None


class ErrorEnvelope(TypedDict):
    error: ErrorDetails


@dataclass(frozen=True)
class ResponsesCreateNonStreamRequest:
    """Validated input contract for /v1/responses non-stream create."""

    model: str
    input: Any
    instructions: str | None = None
    metadata: Mapping[str, Any] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class ResponsesCreateNonStreamResult:
    """Output contract: exact JSON payload returned to the client."""

    payload: Mapping[str, Any]


@dataclass(frozen=True)
class GatewayError(Exception):
    """Deterministic error container used for HTTP responses."""

    status: int
    code: str
    message: str
    error_type: str = "gateway_error"
    param: str | None = None


ROUTE_PATH: str = "/v1/responses"

routes = web.RouteTableDef()
ROUTES = routes  # compatibility alias


def _json_error(
    *,
    status: int,
    code: str,
    message: str,
    error_type: str,
    param: str | None = None,
) -> web.Response:
    body: ErrorEnvelope = {
        "error": {
            "message": message,
            "type": error_type,
            "code": code,
            "param": param,
        }
    }
    return web.json_response(body, status=status)


def _as_gateway_error(exc: Exception) -> GatewayError:
    """Convert arbitrary exceptions into deterministic GatewayError."""
    if isinstance(exc, GatewayError):
        return exc
    # Deterministic: do not leak exception strings or stack details.
    return GatewayError(status=502, code="upstream_failure", message="Upstream request failed.")


def _validate_request_payload(payload: Any) -> ResponsesCreateNonStreamRequest:
    if not isinstance(payload, dict):
        raise GatewayError(
            status=400,
            code="invalid_json",
            message="Request body must be a JSON object.",
            error_type="invalid_request_error",
        )

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise GatewayError(
            status=400,
            code="missing_model",
            message="Field 'model' is required and must be a non-empty string.",
            error_type="invalid_request_error",
            param="model",
        )

    # This prompt is explicitly non-stream.
    if payload.get("stream") is True:
        raise GatewayError(
            status=400,
            code="stream_not_supported",
            message="Streaming is not supported on this endpoint.",
            error_type="invalid_request_error",
            param="stream",
        )

    # Compat: accept `messages` in place of `input`.
    input_value = payload.get("input", payload.get("messages"))
    if input_value is None:
        raise GatewayError(
            status=400,
            code="missing_input",
            message="Field 'input' (or 'messages') is required.",
            error_type="invalid_request_error",
            param="input",
        )

    instructions = payload.get("instructions")
    if instructions is not None and not isinstance(instructions, str):
        raise GatewayError(
            status=400,
            code="invalid_instructions",
            message="Field 'instructions' must be a string when provided.",
            error_type="invalid_request_error",
            param="instructions",
        )

    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise GatewayError(
            status=400,
            code="invalid_metadata",
            message="Field 'metadata' must be an object when provided.",
            error_type="invalid_request_error",
            param="metadata",
        )

    temperature = payload.get("temperature")
    if temperature is not None and not isinstance(temperature, (int, float)):
        raise GatewayError(
            status=400,
            code="invalid_temperature",
            message="Field 'temperature' must be a number when provided.",
            error_type="invalid_request_error",
            param="temperature",
        )

    # Alias: allow max_tokens for callers that still use completions-style naming.
    max_output_tokens = payload.get("max_output_tokens", payload.get("max_tokens"))
    if max_output_tokens is not None and not isinstance(max_output_tokens, int):
        raise GatewayError(
            status=400,
            code="invalid_max_output_tokens",
            message="Field 'max_output_tokens' must be an integer when provided.",
            error_type="invalid_request_error",
            param="max_output_tokens",
        )

    return ResponsesCreateNonStreamRequest(
        model=model.strip(),
        input=input_value,
        instructions=instructions,
        metadata=metadata,
        temperature=float(temperature) if isinstance(temperature, (int, float)) else None,
        max_output_tokens=max_output_tokens,
    )


def _approx_tokens_from_text(text: str) -> int:
    txt = text.strip()
    if not txt:
        return 0
    return len(txt.split())


def _approx_tokens(value: Any) -> int:
    """Rough, deterministic token approximation for usage fields."""
    if isinstance(value, str):
        return _approx_tokens_from_text(value)
    return 0


def _build_response_payload(req: ResponsesCreateNonStreamRequest, *, output_text: str) -> Mapping[str, Any]:
    now = int(time.time())
    resp_id = f"resp_{uuid.uuid4().hex}"
    msg_id = f"msg_{uuid.uuid4().hex}"

    input_tokens = _approx_tokens(req.input)
    output_tokens = _approx_tokens(output_text)

    return {
        "id": resp_id,
        "object": "response",
        "created_at": now,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": req.instructions,
        "metadata": dict(req.metadata) if req.metadata else {},
        "model": req.model,
        "output": [
            {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": output_text}],
            }
        ],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _invoke_backend(backend: Any, req: ResponsesCreateNonStreamRequest) -> Any:
    """Best-effort backend invocation against likely Thomas interfaces."""

    # Most specific first.
    if hasattr(backend, "responses_create_non_stream"):
        return await _maybe_await(backend.responses_create_non_stream(req))

    if hasattr(backend, "responses_create"):
        payload = {"model": req.model, "input": req.input, "stream": False}
        try:
            return await _maybe_await(backend.responses_create(payload, stream=False))
        except TypeError:
            try:
                return await _maybe_await(backend.responses_create(payload))
            except TypeError:
                return await _maybe_await(backend.responses_create(req))

    if hasattr(backend, "create_response"):
        payload = {"model": req.model, "input": req.input, "stream": False}
        try:
            return await _maybe_await(backend.create_response(payload))
        except TypeError:
            return await _maybe_await(backend.create_response(req))

    if callable(backend):
        return await _maybe_await(backend(req))

    raise GatewayError(
        status=500,
        code="missing_backend",
        message="Server is missing a responses backend configuration.",
        error_type="configuration_error",
    )


def _extract_text_from_backend_result(result: Any) -> str | None:
    """Extract assistant text from common backend response shapes."""
    if result is None:
        return None
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        # If backend already returns a full Responses payload, caller should passthrough.
        if result.get("object") == "response":
            return None

        # Chat Completions shape.
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            choice0 = choices[0]
            if isinstance(choice0, dict):
                msg = choice0.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                text = choice0.get("text")
                if isinstance(text, str):
                    return text

        # Responses-ish shape without top-level object.
        out = result.get("output")
        if isinstance(out, list) and out:
            out0 = out[0]
            if isinstance(out0, dict):
                content = out0.get("content")
                if isinstance(content, list) and content:
                    content0 = content[0]
                    if isinstance(content0, dict):
                        text = content0.get("text")
                        if isinstance(text, str):
                            return text

        for key in ("output_text", "text", "content"):
            val = result.get(key)
            if isinstance(val, str):
                return val

    return None


async def create_non_stream_response(payload: Any, *, backend: Any) -> ResponsesCreateNonStreamResult:
    """Core implementation: validate, invoke backend, and shape output."""

    req = _validate_request_payload(payload)

    try:
        backend_result = await _invoke_backend(backend, req)
    except Exception as exc:  # noqa: BLE001
        raise _as_gateway_error(exc) from None

    # Passthrough full Responses payloads.
    if isinstance(backend_result, dict) and backend_result.get("object") == "response":
        return ResponsesCreateNonStreamResult(payload=backend_result)

    output_text = _extract_text_from_backend_result(backend_result)
    if output_text is None:
        raise GatewayError(
            status=502,
            code="invalid_backend_response",
            message="Backend returned an unsupported response shape.",
            error_type="upstream_error",
        )

    return ResponsesCreateNonStreamResult(payload=_build_response_payload(req, output_text=output_text))


def _resolve_backend_from_app(app: Mapping[str, Any]) -> Any:
    """Resolve a backend object from typical Thomas app state layouts."""
    for key in (
        "responses_backend",
        "responses_client",
        "gateway_backend",
        "gateway_client",
        "runtime",
        "thomas_runtime",
        "agent_runtime",
        "gateway",
        "backend",
        "provider",
        "llm",
        "engine",
        "client",
        "model_client",
        "ai_client",
    ):
        if key in app:
            return app[key]

    state = app.get("state")
    if state is not None:
        for attr in (
            "responses_backend",
            "responses_client",
            "gateway_backend",
            "gateway_client",
            "runtime",
            "thomas_runtime",
            "agent_runtime",
            "gateway",
            "backend",
            "provider",
            "llm",
            "engine",
            "client",
            "model_client",
            "ai_client",
        ):
            if hasattr(state, attr):
                return getattr(state, attr)

    return None


@routes.post(ROUTE_PATH)
async def handle_responses_create_non_stream(request: web.Request) -> web.Response:
    """aiohttp handler for non-stream /v1/responses."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error(
            status=400,
            code="invalid_json",
            message="Request body must be valid JSON.",
            error_type="invalid_request_error",
        )

    backend = _resolve_backend_from_app(request.app)
    if backend is None:
        return _json_error(
            status=500,
            code="missing_backend",
            message="Server is missing a responses backend configuration.",
            error_type="configuration_error",
        )

    try:
        result = await create_non_stream_response(payload, backend=backend)
    except GatewayError as ge:
        return _json_error(status=ge.status, code=ge.code, message=ge.message, error_type=ge.error_type, param=ge.param)

    return web.json_response(result.payload)


def get_routes() -> Sequence[web.RouteDef]:
    return list(routes)


def register_routes(app: web.Application) -> None:
    """Imperatively register routes onto an aiohttp application.

    Duplicate-tolerant to keep startup deterministic when multiple loader
    strategies are used.
    """
    for route_def in get_routes():
        try:
            app.router.add_route(route_def.method, route_def.path, route_def.handler)
        except RuntimeError:
            # Duplicate route or frozen router; ignore for deterministic startup.
            continue


# Compatibility aliases (different route loaders use different names).
add_routes = register_routes
register = register_routes
