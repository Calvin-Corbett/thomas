"""
P147 - Responses tool result mapping

Thomas-native mapping utility (plus optional aiohttp handler) that converts an internal
tool execution result into a Responses-style "tool output" envelope.

Design goals
- Pure mapping function used by other gateway endpoints (e.g., responses create).
- Deterministic validation errors (stable error codes).
- Optional HTTP endpoint helper:
    POST /gateway/responses/tool-result-map
    Body: {"tool_call_id": "...", "result": <any-json>, "is_error": false, ...}

Notes
- No OpenClaw naming reuse.
- The mapping shape is intentionally "compat-friendly": it includes both a structured
  `content` array and an `output` convenience field (some downstream code prefers one).
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast


class ToolResultMapRequest(TypedDict, total=False):
    """Request contract for mapping a tool result into a Responses-style tool output envelope."""

    tool_call_id: str
    tool_name: str
    is_error: bool
    error_code: str
    error_message: str
    result: Any


class ToolResultMapResponse(TypedDict):
    """Output contract for the mapped tool output object."""

    tool_output: dict[str, Any]


class DeterministicMappingError(ValueError):
    """A stable, machine-readable input error."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _require_object(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise DeterministicMappingError("invalid_input", "request must be a JSON object")
    return cast(dict[str, Any], v)


def _require_nonempty_str(field: str, v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise DeterministicMappingError("invalid_input", f"{field} must be a non-empty string")
    return v.strip()


def _ensure_optional_nonempty_str(field: str, v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise DeterministicMappingError(
            "invalid_input", f"{field} must be a non-empty string when provided"
        )
    return v.strip()


def _is_jsonable(v: Any) -> bool:
    try:
        json.dumps(v)
        return True
    except Exception:
        return False


def _coerce_jsonable(v: Any) -> Any:
    """Deterministically coerce non-JSONable values into a string."""
    if _is_jsonable(v):
        return v
    try:
        return str(v)
    except Exception:
        return "<unserializable>"


def map_tool_result_to_responses_tool_output(req: ToolResultMapRequest) -> ToolResultMapResponse:
    """Map a tool execution result into a Responses-style tool output envelope.

    Output shape (compat-friendly):
      {
        "tool_output": {
          "type": "tool_output",
          "tool_call_id": "...",
          "status": "completed"|"failed",
          "tool_name": "...",                  # optional
          "output": <json-or-text>,            # convenience
          "content": [{"type": "output_json"|"output_text", ...}],
          "error": {"code": "...", "message": "..."}   # only when failed
        }
      }
    """

    obj = _require_object(req)

    tool_call_id = _require_nonempty_str("tool_call_id", obj.get("tool_call_id"))
    tool_name = _ensure_optional_nonempty_str("tool_name", obj.get("tool_name"))

    is_error = bool(obj.get("is_error", False))

    if is_error:
        error_code = _require_nonempty_str("error_code", obj.get("error_code"))
        error_message = _require_nonempty_str("error_message", obj.get("error_message"))

        tool_output: dict[str, Any] = {
            "type": "tool_output",
            "tool_call_id": tool_call_id,
            "status": "failed",
            "error": {"code": error_code, "message": error_message},
            "output": error_message,
            "content": [{"type": "output_text", "text": error_message}],
        }
        if tool_name:
            tool_output["tool_name"] = tool_name
        return {"tool_output": tool_output}

    if "result" not in obj:
        raise DeterministicMappingError("invalid_input", "result is required when is_error is false")

    result = _coerce_jsonable(obj.get("result"))

    if isinstance(result, str):
        content_item = {"type": "output_text", "text": result}
        output_value: Any = result
    else:
        content_item = {"type": "output_json", "json": result}
        output_value = result

    tool_output = {
        "type": "tool_output",
        "tool_call_id": tool_call_id,
        "status": "completed",
        "output": output_value,
        "content": [content_item],
    }
    if tool_name:
        tool_output["tool_name"] = tool_name
    return {"tool_output": tool_output}


def _error_payload(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


async def handle_tool_result_map(request):
    """aiohttp handler: POST JSON -> mapped tool output JSON."""
    try:
        body = await request.json()
    except Exception:
        return _aiohttp_json(400, _error_payload("invalid_json", "request body must be valid JSON"))

    try:
        mapped = map_tool_result_to_responses_tool_output(cast(ToolResultMapRequest, body))
    except DeterministicMappingError as e:
        return _aiohttp_json(400, _error_payload(e.code, e.message))
    except Exception:
        return _aiohttp_json(500, _error_payload("internal_error", "unexpected error while mapping tool result"))

    payload: dict[str, Any] = {"ok": True}
    payload.update(mapped)
    return _aiohttp_json(200, payload)


def get_aiohttp_routes():
    """Returns a list of aiohttp routes, if aiohttp is available."""
    try:
        from aiohttp import web  # type: ignore
    except Exception:
        return []
    return [web.post("/gateway/responses/tool-result-map", handle_tool_result_map)]


def _aiohttp_json(status: int, payload: dict[str, Any]):
    from aiohttp import web  # type: ignore

    return web.json_response(payload, status=status)
