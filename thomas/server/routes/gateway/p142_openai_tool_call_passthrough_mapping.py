from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union, cast
from collections.abc import Mapping, Sequence

from aiohttp import web

JSONPrimitive = Union[None, bool, int, float, str]
JSONValue = Union[JSONPrimitive, list["JSONValue"], dict[str, "JSONValue"]]


class OpenAIToolFunction(TypedDict, total=False):
    name: str
    arguments: str


class OpenAIToolCall(TypedDict, total=False):
    id: str
    type: str
    function: OpenAIToolFunction


class OpenAIChatMessage(TypedDict, total=False):
    role: str
    content: Any
    tool_calls: list[OpenAIToolCall]
    tool_call_id: str
    name: str


class ToolCallIdPassthroughMapStats(TypedDict):
    total_tool_calls: int
    remapped_tool_calls: int
    total_tool_results: int
    remapped_tool_results: int


class ToolCallIdPassthroughMapResponse(TypedDict):
    messages: list[OpenAIChatMessage]
    tool_call_id_map: dict[str, str]
    changed: bool
    stats: ToolCallIdPassthroughMapStats


class ErrorResponse(TypedDict):
    code: str
    message: str
    details: dict[str, JSONValue]


@dataclass(frozen=True)
class ToolCallIdMapResult:
    messages: list[OpenAIChatMessage]
    tool_call_id_map: dict[str, str]
    changed: bool
    stats: ToolCallIdPassthroughMapStats

    def to_dict(self) -> ToolCallIdPassthroughMapResponse:
        return {
            "messages": self.messages,
            "tool_call_id_map": self.tool_call_id_map,
            "changed": self.changed,
            "stats": self.stats,
        }


class ToolCallIdMapError(Exception):
    """Deterministic, machine-readable failures for tool-call ID mapping."""

    code: str
    http_status: int
    details: dict[str, JSONValue]

    def __init__(
        self,
        *,
        code: str,
        message: str,
        http_status: int = 400,
        details: dict[str, JSONValue] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.details = details or {}

    def to_error(self) -> ErrorResponse:
        return {"code": self.code, "message": str(self), "details": self.details}


STRICT_TOOL_CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_MAX_ID_LEN = 64


def _stable_hash(text: str, length: int = 8) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _sanitize_tool_call_id(raw_id: str, *, max_len: int = DEFAULT_MAX_ID_LEN) -> str:
    canonical = raw_id.strip()
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", canonical)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = "tool_call"
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")
        if not cleaned:
            cleaned = "tool_call"
    return cleaned


def _is_strict_id(value: str) -> bool:
    return STRICT_TOOL_CALL_ID_RE.fullmatch(value) is not None


def build_openai_tool_call_passthrough_mapping(
    messages: Sequence[Mapping[str, Any]],
    *,
    policy: Literal["strict"] = "strict",
) -> ToolCallIdMapResult:
    """Normalize OpenAI Chat Completions tool-call IDs for replay/passthrough.

    This remaps:
    - assistant.tool_calls[].id
    - tool.tool_call_id (matching the above)

    Policy:
    - "strict" maps IDs to `^[A-Za-z0-9_-]+$` (common strict-provider requirement).

    Determinism:
    - Sanitization is purely functional.
    - Collisions are resolved by appending a stable hash suffix and then a numeric suffix if needed.
    """
    if policy != "strict":
        raise ToolCallIdMapError(
            code="invalid_policy",
            message=f"Unsupported policy: {policy!r}",
            http_status=400,
            details={"supported": ["strict"]},
        )

    copied: list[OpenAIChatMessage] = cast(list[OpenAIChatMessage], copy.deepcopy(list(messages)))

    id_map: dict[str, str] = {}
    used_ids: dict[str, str] = {}  # mapped_id -> canonical_source_id

    total_tool_calls = 0
    remapped_tool_calls = 0
    total_tool_results = 0
    remapped_tool_results = 0

    def register_mapping(source_id: str) -> str:
        canonical = source_id.strip()
        if _is_strict_id(canonical):
            mapped = canonical
        else:
            mapped = _sanitize_tool_call_id(canonical)

        owner = used_ids.get(mapped)
        if owner is None:
            used_ids[mapped] = canonical
        elif owner != canonical:
            suffix = _stable_hash(canonical)
            candidate = f"{mapped}_{suffix}"
            if len(candidate) > DEFAULT_MAX_ID_LEN:
                trim = DEFAULT_MAX_ID_LEN - (len(suffix) + 1)
                candidate = f"{mapped[:max(1, trim)]}_{suffix}"
            mapped = candidate
            if mapped in used_ids and used_ids[mapped] != canonical:
                i = 2
                while f"{mapped}_{i}" in used_ids and used_ids.get(f"{mapped}_{i}") != canonical:
                    i += 1
                mapped = f"{mapped}_{i}"
            used_ids[mapped] = canonical

        # Map raw and canonical and mapped-to-self for later tool_result lookups.
        id_map.setdefault(source_id, mapped)
        if canonical != source_id:
            id_map.setdefault(canonical, mapped)
        id_map.setdefault(mapped, mapped)
        return mapped

    # Pass 1: assistant tool calls
    for msg in copied:
        if msg.get("role") != "assistant":
            continue

        tool_calls = msg.get("tool_calls")
        if tool_calls is None:
            continue
        if not isinstance(tool_calls, list):
            raise ToolCallIdMapError(
                code="invalid_request",
                message="assistant.tool_calls must be a list",
                http_status=400,
                details={"path": "messages[].tool_calls"},
            )

        for tc in tool_calls:
            if not isinstance(tc, dict):
                raise ToolCallIdMapError(
                    code="invalid_request",
                    message="tool_calls items must be objects",
                    http_status=400,
                    details={"path": "messages[].tool_calls[]"},
                )

            total_tool_calls += 1
            raw_id = tc.get("id")
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise ToolCallIdMapError(
                    code="invalid_request",
                    message="tool_calls[].id must be a non-empty string",
                    http_status=400,
                    details={"path": "messages[].tool_calls[].id"},
                )

            mapped = register_mapping(raw_id)
            if tc.get("id") != mapped:
                tc["id"] = mapped
                remapped_tool_calls += 1

    # Pass 2: tool result messages
    for msg in copied:
        if msg.get("role") != "tool":
            continue

        total_tool_results += 1
        raw_ref = msg.get("tool_call_id")
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            raise ToolCallIdMapError(
                code="invalid_request",
                message="tool.tool_call_id must be a non-empty string",
                http_status=400,
                details={"path": "messages[].tool_call_id"},
            )

        canonical_ref = raw_ref.strip()
        mapped = id_map.get(raw_ref) or id_map.get(canonical_ref)
        if mapped is None:
            raise ToolCallIdMapError(
                code="unknown_tool_call_id",
                message=f"tool_call_id {raw_ref!r} does not match any prior assistant tool_calls[].id",
                http_status=400,
                details={"tool_call_id": raw_ref},
            )

        if msg.get("tool_call_id") != mapped:
            msg["tool_call_id"] = mapped
            remapped_tool_results += 1

    changed = remapped_tool_calls > 0 or remapped_tool_results > 0
    stats: ToolCallIdPassthroughMapStats = {
        "total_tool_calls": total_tool_calls,
        "remapped_tool_calls": remapped_tool_calls,
        "total_tool_results": total_tool_results,
        "remapped_tool_results": remapped_tool_results,
    }
    return ToolCallIdMapResult(messages=copied, tool_call_id_map=id_map, changed=changed, stats=stats)


def get_json_schema() -> dict[str, Any]:
    """Minimal schema for automation tooling (validates only what this module cares about)."""
    return {
        "request": {
            "type": "object",
            "required": ["messages"],
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}},
                "policy": {"type": "string", "enum": ["strict"], "default": "strict"},
            },
            "additionalProperties": False,
        },
        "response": {
            "type": "object",
            "required": ["ok"],
            "properties": {
                "ok": {"type": "boolean"},
                "result": {"type": "object"},
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object"},
                    },
                    "required": ["code", "message", "details"],
                },
            },
        },
    }


routes = web.RouteTableDef()

_SCHEMA_PATHS = (
    "/gateway/p142_openai_tool_call_passthrough_mapping/schema",
    "/v1/gateway/p142_openai_tool_call_passthrough_mapping/schema",
)

_MAP_PATHS = (
    "/gateway/p142_openai_tool_call_passthrough_mapping",
    "/v1/gateway/p142_openai_tool_call_passthrough_mapping",
)


async def _schema_handler(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "schema": get_json_schema()})


async def _map_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        err = ToolCallIdMapError(code="invalid_json", message="Request body must be valid JSON", http_status=400)
        return web.json_response({"ok": False, "error": err.to_error()}, status=err.http_status)

    try:
        if isinstance(payload, list):
            messages = payload
            policy = "strict"
        elif isinstance(payload, dict):
            messages = payload.get("messages")
            policy = payload.get("policy", "strict")
        else:
            raise ToolCallIdMapError(
                code="invalid_request",
                message="Request body must be an object or an array of messages",
                http_status=400,
            )

        if not isinstance(messages, list):
            raise ToolCallIdMapError(
                code="invalid_request",
                message="messages must be a list",
                http_status=400,
                details={"path": "messages"},
            )

        result = build_openai_tool_call_passthrough_mapping(messages, policy=cast(Literal["strict"], policy))
        return web.json_response({"ok": True, "result": result.to_dict()})
    except ToolCallIdMapError as e:
        return web.json_response({"ok": False, "error": e.to_error()}, status=e.http_status)


for p in _SCHEMA_PATHS:
    routes.get(p)(_schema_handler)

for p in _MAP_PATHS:
    routes.post(p)(_map_handler)


def add_routes(app: web.Application) -> None:
    app.add_routes(routes)


register = add_routes
