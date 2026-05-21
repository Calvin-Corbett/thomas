from __future__ import annotations

"""
Thomas Gateway – Responses create stream events (P146)

This module implements a deterministic subset of the OpenAI Responses API streaming
event protocol for Thomas' gateway layer.

Key behaviors:
- POST /v1/responses
  - stream=false (default): returns a JSON Response object.
  - stream=true: returns Server-Sent Events (SSE) with semantic event types.

Automation helpers:
- POST /v1/responses?format=json (with stream=true) returns {"events":[...]} instead of SSE.
- GET /v1/responses/streaming-events/schema returns JSON schemas for request + event envelopes.

Proxy support (optional):
- THOMAS_GATEWAY_RESPONSES_MODE=stub|proxy (default: stub)
- In proxy mode, the request is forwarded to <UPSTREAM>/v1/responses.
  Required: THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL
  Optional: THOMAS_GATEWAY_RESPONSES_API_KEY (Bearer)

Notes:
- This is intentionally "Thomas-native" and does not reuse any Reference CLI naming.
- The streaming event catalog is minimal but structurally compatible; expand as needed.
"""

import json
import os
import time
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from aiohttp import ClientSession, ClientTimeout, ContentTypeError, web

# -----------------------------
# Contracts
# -----------------------------


class CreateResponseRequestDict(TypedDict, total=False):
    model: str
    input: str | list[Any]
    stream: bool
    temperature: float
    max_output_tokens: int
    metadata: dict[str, Any]


class OpenAIStyleError(TypedDict, total=False):
    message: str
    type: str
    param: str | None
    code: str | None


StreamEvent = dict[str, Any]


@dataclass(frozen=True)
class ParsedCreateResponseRequest:
    model: str
    raw_input: str | list[Any]
    prompt_text: str
    stream: bool
    temperature: float
    max_output_tokens: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RuntimeConfig:
    mode: Literal["stub", "proxy"]
    upstream_url: str | None
    api_key: str | None


# -----------------------------
# Deterministic errors
# -----------------------------


class GatewayError(Exception):
    """Deterministic, machine-readable error used by this route."""

    def __init__(self, *, code: str, message: str, http_status: int, param: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.param = param

    def to_openai_error(self) -> dict[str, Any]:
        err: dict[str, Any] = {
            "message": self.message,
            "type": "invalid_request_error" if 400 <= self.http_status < 500 else "server_error",
            "param": self.param,
            "code": self.code,
        }
        return {"error": err}


# -----------------------------
# Helpers
# -----------------------------


def load_runtime_config_from_env() -> RuntimeConfig:
    mode = os.environ.get("THOMAS_GATEWAY_RESPONSES_MODE", "stub").strip().lower()
    if mode not in {"stub", "proxy"}:
        raise GatewayError(
            code="invalid_config",
            message="THOMAS_GATEWAY_RESPONSES_MODE must be 'stub' or 'proxy'.",
            http_status=500,
            param="THOMAS_GATEWAY_RESPONSES_MODE",
        )

    upstream_url = os.environ.get("THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL")
    api_key = os.environ.get("THOMAS_GATEWAY_RESPONSES_API_KEY")

    if mode == "proxy" and not upstream_url:
        raise GatewayError(
            code="missing_config",
            message="Proxy mode requires THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL.",
            http_status=500,
            param="THOMAS_GATEWAY_RESPONSES_UPSTREAM_URL",
        )

    return RuntimeConfig(mode=cast(Literal["stub", "proxy"], mode), upstream_url=upstream_url, api_key=api_key)


def _now_unix() -> int:
    return int(time.time())


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _extract_prompt_text(value: Any) -> str:
    """
    Best-effort extraction of user text from the Responses API `input` field.

    Supports:
    - input: "string"
    - input: [{"role": "...", "content": "..."}, ...]
    - content as list of parts: [{"type":"input_text","text":"..."}, ...]
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
                continue
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, str):
                        parts.append(c)
                    elif isinstance(c, dict):
                        if isinstance(c.get("text"), str):
                            parts.append(c["text"])
                        elif isinstance(c.get("input_text"), str):
                            parts.append(c["input_text"])
        return " ".join(p.strip() for p in parts if p and isinstance(p, str)).strip()

    return ""


def parse_create_response_request(payload: Mapping[str, Any]) -> ParsedCreateResponseRequest:
    if not isinstance(payload, Mapping):
        raise GatewayError(code="invalid_request", message="Request body must be a JSON object.", http_status=400)

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise GatewayError(
            code="invalid_request", message="Missing or invalid 'model'.", http_status=400, param="model"
        )

    raw_input = payload.get("input")
    if raw_input is None:
        raise GatewayError(code="invalid_request", message="Missing required 'input'.", http_status=400, param="input")
    if not isinstance(raw_input, (str, list)):
        raise GatewayError(
            code="invalid_request", message="'input' must be a string or an array.", http_status=400, param="input"
        )

    stream = bool(payload.get("stream", False))

    temperature = payload.get("temperature", 1.0)
    if temperature is None:
        temperature = 1.0
    if not isinstance(temperature, (int, float)):
        raise GatewayError(
            code="invalid_request", message="'temperature' must be a number.", http_status=400, param="temperature"
        )

    max_output_tokens = payload.get("max_output_tokens")
    if max_output_tokens is not None and not isinstance(max_output_tokens, int):
        raise GatewayError(
            code="invalid_request",
            message="'max_output_tokens' must be an integer.",
            http_status=400,
            param="max_output_tokens",
        )

    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise GatewayError(
            code="invalid_request", message="'metadata' must be an object.", http_status=400, param="metadata"
        )

    prompt_text = _extract_prompt_text(raw_input)

    return ParsedCreateResponseRequest(
        model=model.strip(),
        raw_input=cast(str | list[Any], raw_input),
        prompt_text=prompt_text,
        stream=stream,
        temperature=float(temperature),
        max_output_tokens=max_output_tokens,
        metadata=cast(dict[str, Any], metadata),
    )


def _chunk_text(text: str, *, chunk_size: int = 8) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _build_message_item(*, message_id: str, status: str, text: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "status": status,
        "content": [],
    }
    if text is not None:
        item["content"] = [{"type": "output_text", "text": text, "annotations": []}]
    return item


def _build_response_object(
    *,
    response_id: str,
    created_at: int,
    status: str,
    model: str,
    output: list[dict[str, Any]],
    completed_at: int | None,
    metadata: dict[str, Any],
    temperature: float,
    error: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "completed_at": completed_at,
        "error": error,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "store": False,
        "temperature": temperature,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1,
        "truncation": "disabled",
        "usage": usage,
        "user": None,
        "metadata": metadata,
    }


def _usage_from_text(input_text: str, output_text: str) -> dict[str, int]:
    input_tokens = max(1, len((input_text or "").split()))
    output_tokens = max(1, len((output_text or "").split()))
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens}


def iter_stream_events(
    req: ParsedCreateResponseRequest,
    *,
    response_id: str,
    message_id: str,
    created_at: int,
    completed_at: int,
) -> Iterator[StreamEvent]:
    """Yield a deterministic sequence of streaming events for a single output_text item."""

    # deterministic external failure simulation (used by tests)
    if req.model.strip().lower() in {"thomas-fail", "thomas_fail", "fail"}:
        raise GatewayError(code="upstream_failure", message="Upstream model failed.", http_status=502, param="model")

    output_text = f"Thomas: {req.prompt_text}".strip()
    if output_text == "Thomas:":
        output_text = "Thomas: (no input)"

    msg_in_progress = _build_message_item(message_id=message_id, status="in_progress")
    resp_in_progress = _build_response_object(
        response_id=response_id,
        created_at=created_at,
        status="in_progress",
        model=req.model,
        output=[],
        completed_at=None,
        metadata=req.metadata,
        temperature=req.temperature,
    )

    seq = 1

    def emit(ev: dict[str, Any]) -> StreamEvent:
        nonlocal seq
        ev["sequence_number"] = seq
        seq += 1
        return ev

    yield emit({"type": "response.created", "response": resp_in_progress})
    yield emit({"type": "response.output_item.added", "output_index": 0, "item": msg_in_progress})
    yield emit(
        {
            "type": "response.content_part.added",
            "item_id": message_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }
    )

    for chunk in _chunk_text(output_text):
        yield emit(
            {
                "type": "response.output_text.delta",
                "item_id": message_id,
                "output_index": 0,
                "content_index": 0,
                "delta": chunk,
            }
        )

    yield emit(
        {
            "type": "response.output_text.done",
            "item_id": message_id,
            "output_index": 0,
            "content_index": 0,
            "text": output_text,
        }
    )
    yield emit(
        {
            "type": "response.content_part.done",
            "item_id": message_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": output_text, "annotations": []},
        }
    )

    msg_done = _build_message_item(message_id=message_id, status="completed", text=output_text)
    yield emit({"type": "response.output_item.done", "output_index": 0, "item": msg_done})

    usage = _usage_from_text(req.prompt_text, output_text)
    resp_done = _build_response_object(
        response_id=response_id,
        created_at=created_at,
        status="completed",
        model=req.model,
        output=[msg_done],
        completed_at=completed_at,
        metadata=req.metadata,
        temperature=req.temperature,
        usage=usage,
    )
    yield emit({"type": "response.completed", "response": resp_done})


def build_stream_events(
    req: ParsedCreateResponseRequest,
    *,
    response_id: str,
    message_id: str,
    created_at: int,
    completed_at: int,
) -> list[StreamEvent]:
    """Convenience wrapper for tests/automation."""
    return list(
        iter_stream_events(
            req, response_id=response_id, message_id=message_id, created_at=created_at, completed_at=completed_at
        )
    )


def encode_sse_event(event_type: str, data_obj: dict[str, Any]) -> bytes:
    data = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_type}\ndata: {data}\n\n".encode()


def events_to_sse(events: Iterable[StreamEvent]) -> str:
    chunks: list[str] = []
    for ev in events:
        event_type = ev.get("type", "message")
        data = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
        chunks.append(f"event: {event_type}\n")
        chunks.append(f"data: {data}\n\n")
    return "".join(chunks)


async def _proxy_upstream(request: web.Request, payload: dict[str, Any]) -> web.StreamResponse:
    """
    Proxy the request to an upstream Responses endpoint.

    - If stream=true, streams the response bytes.
    - If stream=false, returns the upstream body as a normal response.
    """
    cfg = load_runtime_config_from_env()
    assert cfg.mode == "proxy"
    assert cfg.upstream_url

    upstream_url = cfg.upstream_url.rstrip("/") + "/v1/responses"
    headers: dict[str, str] = {}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    timeout = ClientTimeout(total=60)
    async with ClientSession(timeout=timeout) as session:
        try:
            async with session.post(upstream_url, json=payload, headers=headers) as upstream_resp:
                content_type = upstream_resp.headers.get("Content-Type", "application/json")

                if not bool(payload.get("stream", False)):
                    body = await upstream_resp.read()
                    return web.Response(status=upstream_resp.status, body=body, headers={"Content-Type": content_type})

                if upstream_resp.status >= 400:
                    raise GatewayError(
                        code="upstream_http_error",
                        message=f"Upstream returned HTTP {upstream_resp.status}.",
                        http_status=502,
                    )

                resp = web.StreamResponse(
                    status=200,
                    headers={
                        "Content-Type": content_type or "text/event-stream",
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                    },
                )
                await resp.prepare(request)

                async for chunk in upstream_resp.content.iter_chunked(4096):
                    await resp.write(chunk)

                await resp.write_eof()
                return resp

        except GatewayError:
            raise
        except Exception as e:
            raise GatewayError(code="upstream_unreachable", message=str(e), http_status=502) from e


# -----------------------------
# Route schemas
# -----------------------------

REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "input": {"oneOf": [{"type": "string"}, {"type": "array"}]},
        "stream": {"type": "boolean"},
        "temperature": {"type": "number"},
        "max_output_tokens": {"type": "integer"},
        "metadata": {"type": "object"},
    },
    "required": ["model", "input"],
    "additionalProperties": True,
}

EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "sequence_number": {"type": "integer"},
    },
    "required": ["type", "sequence_number"],
    "additionalProperties": True,
}


# -----------------------------
# aiohttp routes
# -----------------------------

routes = web.RouteTableDef()


@routes.get("/v1/responses/streaming-events/schema")
async def get_streaming_schema(request: web.Request) -> web.Response:
    return web.json_response({"request_schema": REQUEST_SCHEMA, "event_schema": EVENT_SCHEMA})


@routes.post("/v1/responses")
async def create_response(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except ContentTypeError:
        e = GatewayError(code="invalid_request", message="Content-Type must be application/json.", http_status=400)
        return web.json_response(e.to_openai_error(), status=e.http_status)
    except json.JSONDecodeError:
        e = GatewayError(code="invalid_request", message="Malformed JSON body.", http_status=400)
        return web.json_response(e.to_openai_error(), status=e.http_status)

    if not isinstance(payload, dict):
        e = GatewayError(code="invalid_request", message="Request body must be a JSON object.", http_status=400)
        return web.json_response(e.to_openai_error(), status=e.http_status)

    try:
        cfg = load_runtime_config_from_env()
    except GatewayError as e:
        return web.json_response(e.to_openai_error(), status=e.http_status)

    if cfg.mode == "proxy":
        try:
            return await _proxy_upstream(request, payload)
        except GatewayError as e:
            return web.json_response(e.to_openai_error(), status=e.http_status)

    try:
        parsed = parse_create_response_request(payload)
    except GatewayError as e:
        return web.json_response(e.to_openai_error(), status=e.http_status)

    created_at = _now_unix()
    completed_at = created_at
    response_id = _make_id("resp")
    message_id = _make_id("msg")

    if not parsed.stream:
        try:
            events = build_stream_events(
                parsed, response_id=response_id, message_id=message_id, created_at=created_at, completed_at=completed_at
            )
        except GatewayError as e:
            return web.json_response(e.to_openai_error(), status=e.http_status)
        final = next((ev["response"] for ev in reversed(events) if ev.get("type") == "response.completed"), None)
        return web.json_response(final or {}, status=200)

    if request.rel_url.query.get("format") == "json":
        try:
            events = build_stream_events(
                parsed, response_id=response_id, message_id=message_id, created_at=created_at, completed_at=completed_at
            )
        except GatewayError as e:
            return web.json_response(e.to_openai_error(), status=e.http_status)
        return web.json_response({"events": events}, status=200)

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await resp.prepare(request)

    try:
        for ev in iter_stream_events(
            parsed, response_id=response_id, message_id=message_id, created_at=created_at, completed_at=completed_at
        ):
            await resp.write(encode_sse_event(str(ev.get("type", "message")), ev))
    except GatewayError as e:
        err_event: dict[str, Any] = {"type": "error", "sequence_number": 1, "error": e.to_openai_error()["error"]}
        await resp.write(encode_sse_event("error", err_event))
    finally:
        await resp.write_eof()

    return resp


def register(app: web.Application) -> None:
    app.router.add_routes(routes)


ROUTES = routes
