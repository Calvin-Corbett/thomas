from __future__ import annotations

"""
Nodes camera action (P042).

This module provides a Thomas-native "camera action" primitive that can be called
from the CLI layer and (optionally) server routes.

Key properties:
- Clear, typed request/response contracts.
- Deterministic, machine-readable errors.
- Standard-library HTTP client (urllib) to avoid extra runtime deps.

The actual camera work is delegated to a configured Nodes service endpoint.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodesCameraActionErrorCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_CONFIG = "MISSING_CONFIG"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    REMOTE_ERROR = "REMOTE_ERROR"


@dataclass(frozen=True)
class NodesCameraActionError(Exception):
    """
    Deterministic error used by Nodes camera action.

    Attributes:
        code: Machine-readable category.
        message: Human-readable message.
        details: Additional structured info with stable keys.
    """

    code: NodesCameraActionErrorCode
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }


# Canonical Thomas-native action vocabulary.
_ALLOWED_ACTIONS: set[str] = {
    "capture",
    "start_recording",
    "stop_recording",
    "start_stream",
    "stop_stream",
}

# Friendly aliases accepted at input, but normalized to canonical actions above.
_ACTION_ALIASES: dict[str, str] = {
    "photo": "capture",
    "snapshot": "capture",
    "take_photo": "capture",
    "take_picture": "capture",
    "takepicture": "capture",
    "record_start": "start_recording",
    "recordstop": "stop_recording",
    "record_stop": "stop_recording",
    "stream_start": "start_stream",
    "stream_stop": "stop_stream",
}


@dataclass(frozen=True)
class NodesCameraActionRequest:
    """Input contract for a camera action."""

    node_id: str
    action: str
    camera: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = 10.0


@dataclass(frozen=True)
class NodesCameraActionResponse:
    """Output contract for a camera action."""

    ok: bool
    node_id: str
    action: str
    camera: int | None = None
    artifact: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "node_id": self.node_id,
            "action": self.action,
            "camera": self.camera,
            "artifact": self.artifact,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    text: str
    json_data: Mapping[str, Any] | None = None


def _truncate(text: str, limit: int = 700) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _normalize_action(action: str) -> str:
    action_norm = action.strip()
    if not action_norm:
        return action_norm
    lowered = action_norm.lower().replace(" ", "_").replace("-", "_")
    while "__" in lowered:
        lowered = lowered.replace("__", "_")
    return _ACTION_ALIASES.get(lowered, lowered)


def _require_non_empty_str(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message=f"{field} is required and must be a non-empty string.",
            details={"field": field},
        )
    return value.strip()


def _validate_camera(camera: Any) -> int | None:
    if camera is None:
        return None
    if isinstance(camera, bool):
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="camera must be an integer if provided.",
            details={"field": "camera"},
        )
    if isinstance(camera, int):
        if camera < 0:
            raise NodesCameraActionError(
                code=NodesCameraActionErrorCode.INVALID_INPUT,
                message="camera must be >= 0.",
                details={"field": "camera"},
            )
        return camera
    raise NodesCameraActionError(
        code=NodesCameraActionErrorCode.INVALID_INPUT,
        message="camera must be an integer if provided.",
        details={"field": "camera"},
    )


def _validate_timeout(timeout_s: Any) -> float:
    try:
        timeout_val = float(timeout_s)
    except (RuntimeError, ValueError, KeyError, AttributeError, TypeError):
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="timeout_s must be a number if provided.",
            details={"field": "timeout_s"},
        )
    if timeout_val <= 0:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="timeout_s must be > 0.",
            details={"field": "timeout_s"},
        )
    return timeout_val


def parse_nodes_camera_action_request(data: Mapping[str, Any]) -> NodesCameraActionRequest:
    """
    Parse/validate a JSON-like mapping into a typed request object.

    Accepted keys:
      - node_id (required) : str   (also accepts node / id / nodeId)
      - action  (required) : str
      - camera  (optional) : int
      - options (optional) : object/dict
      - timeout_s (optional): float
    """
    node_id = data.get("node_id") or data.get("node") or data.get("id") or data.get("nodeId")
    node_id_str = _require_non_empty_str(node_id, field="node_id")

    raw_action = data.get("action")
    raw_action_str = _require_non_empty_str(raw_action, field="action")
    action = _normalize_action(raw_action_str)
    if action not in _ALLOWED_ACTIONS:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="Unsupported camera action.",
            details={"field": "action", "action": action, "allowed": sorted(_ALLOWED_ACTIONS)},
        )

    camera_int = _validate_camera(data.get("camera"))

    options = data.get("options", {})
    if options is None:
        options_dict: dict[str, Any] = {}
    elif isinstance(options, Mapping):
        options_dict = dict(options)
    else:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="options must be an object/dict if provided.",
            details={"field": "options"},
        )

    timeout_val = _validate_timeout(data.get("timeout_s", 10.0))

    return NodesCameraActionRequest(
        node_id=node_id_str,
        action=action,
        camera=camera_int,
        options=options_dict,
        timeout_s=timeout_val,
    )


def _maybe_resolve_from_thomas_config() -> str | None:
    """
    Best-effort lookup of a nodes base URL from a Thomas config module.

    This function is intentionally defensive: different Thomas deployments may
    expose configuration in different shapes. If we can't find something
    plausible, we return None.
    """
    try:
        import importlib

        cfg = importlib.import_module("thomas.config")
    except (ImportError, AttributeError, RuntimeError):
        return None

    candidates: list[Any] = []
    for attr in ("settings", "config", "CONFIG", "SETTINGS"):
        if hasattr(cfg, attr):
            candidates.append(getattr(cfg, attr))

    def dig(obj: Any, path: list[str]) -> Any | None:
        cur = obj
        for key in path:
            if cur is None:
                return None
            if isinstance(cur, Mapping):
                cur = cur.get(key)
            else:
                cur = getattr(cur, key, None)
        return cur

    for cand in candidates:
        for path in (
            ["nodes_url"],
            ["nodes", "url"],
            ["nodes", "base_url"],
            ["nodes", "endpoint"],
            ["nodes_service_url"],
        ):
            val = dig(cand, path)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return None


def _validate_base_url(url: str, *, source: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.MISSING_CONFIG
            if source != "explicit"
            else NodesCameraActionErrorCode.INVALID_INPUT,
            message="Nodes service base URL is invalid.",
            details={"base_url": url, "source": source},
        )
    return url.rstrip("/")


def resolve_nodes_base_url(explicit_base_url: str | None = None) -> str:
    """
    Determine the Nodes service base URL.

    Resolution order:
      1) explicit_base_url argument
      2) environment variables
      3) thomas.config best-effort lookup
    """
    if explicit_base_url and explicit_base_url.strip():
        return _validate_base_url(explicit_base_url.strip(), source="explicit")

    for key in (
        "THOMAS_NODES_URL",
        "THOMAS_NODES_BASE_URL",
        "THOMAS_NODE_SERVICE_URL",
        "NODES_URL",
        "NODES_BASE_URL",
    ):
        val = os.environ.get(key)
        if val and val.strip():
            return _validate_base_url(val.strip(), source=f"env:{key}")

    cfg_val = _maybe_resolve_from_thomas_config()
    if cfg_val:
        return _validate_base_url(cfg_val, source="thomas.config")

    raise NodesCameraActionError(
        code=NodesCameraActionErrorCode.MISSING_CONFIG,
        message="Nodes service base URL is not configured.",
        details={
            "expected": [
                "THOMAS_NODES_URL",
                "THOMAS_NODES_BASE_URL",
                "THOMAS_NODE_SERVICE_URL",
            ]
        },
    )


def _resolve_auth_token(explicit_token: str | None = None) -> str | None:
    if explicit_token and explicit_token.strip():
        return explicit_token.strip()
    for key in ("THOMAS_NODES_TOKEN", "THOMAS_NODE_SERVICE_TOKEN", "NODES_TOKEN"):
        val = os.environ.get(key)
        if val and val.strip():
            return val.strip()
    return None


def build_camera_action_url(base_url: str, node_id: str) -> str:
    """
    Build the camera action URL.

    Default template is: <base_url>/nodes/<node_id>/camera/action

    The template can be overridden via THOMAS_NODES_CAMERA_ACTION_TEMPLATE.
    """
    template = os.environ.get("THOMAS_NODES_CAMERA_ACTION_TEMPLATE", "/nodes/{node_id}/camera/action")
    template = template.strip() or "/nodes/{node_id}/camera/action"
    if not template.startswith("/"):
        template = "/" + template

    safe_node_id = urllib.parse.quote(node_id, safe="")
    if "{node_id}" in template:
        path = template.format(node_id=safe_node_id)
    else:
        if not template.endswith("/"):
            template += "/"
        path = template + safe_node_id

    return base_url.rstrip("/") + path


def _http_post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    headers: Mapping[str, str],
    timeout_s: float,
) -> HttpResponse:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")

    merged_headers = {"User-Agent": "Thomas/NodesCameraAction", **dict(headers)}
    for k, v in merged_headers.items():
        req.add_header(k, v)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", resp.getcode())
            text = resp.read().decode("utf-8", errors="replace")
            resp_headers = {k: v for k, v in getattr(resp, "headers", {}).items()}
    except urllib.error.HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        try:
            text = e.read().decode("utf-8", errors="replace")
        except (json.JSONDecodeError, ValueError, KeyError):
            text = ""
        resp_headers = {k: v for k, v in (e.headers.items() if e.headers else [])}
    except urllib.error.URLError as e:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.EXTERNAL_FAILURE,
            message="Failed to reach Nodes service.",
            details={"url": url, "reason": str(getattr(e, "reason", e))},
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.EXTERNAL_FAILURE,
            message="Unexpected failure while contacting Nodes service.",
            details={"url": url, "error": type(e).__name__},
        )

    json_data: Mapping[str, Any] | None = None
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, Mapping):
                json_data = parsed
        except (json.JSONDecodeError, ValueError, KeyError):
            json_data = None

    return HttpResponse(status=int(status), headers=resp_headers, text=text, json_data=json_data)


def execute_nodes_camera_action(
    request: NodesCameraActionRequest,
    *,
    base_url: str | None = None,
    auth_token: str | None = None,
    http_post: Callable[..., HttpResponse] | None = None,
) -> NodesCameraActionResponse:
    """
    Execute the camera action against the configured Nodes service.
    """
    node_id = _require_non_empty_str(request.node_id, field="node_id")
    action = _normalize_action(_require_non_empty_str(request.action, field="action"))
    if action not in _ALLOWED_ACTIONS:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.INVALID_INPUT,
            message="Unsupported camera action.",
            details={"field": "action", "action": action, "allowed": sorted(_ALLOWED_ACTIONS)},
        )

    camera = _validate_camera(request.camera)
    timeout_val = _validate_timeout(request.timeout_s)
    options = request.options if isinstance(request.options, dict) else dict(request.options)

    resolved_base_url = resolve_nodes_base_url(base_url)
    url = build_camera_action_url(resolved_base_url, node_id)

    token = _resolve_auth_token(auth_token)
    headers: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload: dict[str, Any] = {"node_id": node_id, "action": action, "options": options}
    if camera is not None:
        payload["camera"] = camera

    post_impl = http_post or _http_post_json

    try:
        resp = post_impl(url, payload, headers=headers, timeout_s=timeout_val)  # type: ignore[arg-type]
    except TypeError:
        resp = post_impl(url, payload)  # type: ignore[misc]

    if not isinstance(resp, HttpResponse):
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.EXTERNAL_FAILURE,
            message="Nodes HTTP client returned an invalid response object.",
            details={"type": type(resp).__name__},
        )

    if resp.status < 200 or resp.status >= 300:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.REMOTE_ERROR,
            message="Nodes service returned an error.",
            details={
                "url": url,
                "status": resp.status,
                "body": _truncate(resp.text),
                "response_json": dict(resp.json_data) if resp.json_data else None,
            },
        )

    if not resp.json_data:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.REMOTE_ERROR,
            message="Nodes service returned a non-JSON response.",
            details={"url": url, "status": resp.status, "body": _truncate(resp.text)},
        )

    payload_dict = dict(resp.json_data)

    if isinstance(payload_dict.get("ok"), bool) and payload_dict.get("ok") is False:
        raise NodesCameraActionError(
            code=NodesCameraActionErrorCode.REMOTE_ERROR,
            message="Nodes service indicated failure.",
            details={
                "url": url,
                "status": resp.status,
                "remote_error": payload_dict.get("error") if isinstance(payload_dict.get("error"), Mapping) else None,
                "body": _truncate(resp.text),
            },
        )

    artifact = (
        payload_dict.get("artifact")
        or payload_dict.get("artifact_url")
        or payload_dict.get("image_url")
        or payload_dict.get("video_url")
        or payload_dict.get("stream_url")
        or payload_dict.get("image_b64")
        or payload_dict.get("path")
    )
    artifact_str = artifact if isinstance(artifact, str) else None

    return NodesCameraActionResponse(
        ok=True,
        node_id=node_id,
        action=action,
        camera=camera,
        artifact=artifact_str,
        payload=payload_dict,
    )


def run_nodes_camera_action(payload: Mapping[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    """
    Convenience wrapper suitable for route handlers: takes a JSON-like mapping
    and returns a JSON-serializable dict.
    """
    req = parse_nodes_camera_action_request(payload)
    resp = execute_nodes_camera_action(req, base_url=base_url)
    return {"ok": True, "data": resp.to_dict()}


def run_nodes_camera_action_safe(payload: Mapping[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    """
    Safe wrapper that never raises: returns either {"ok": True, "data": ...}
    or {"ok": False, "error": ...}.
    """
    try:
        return run_nodes_camera_action(payload, base_url=base_url)
    except NodesCameraActionError as e:
        return {"ok": False, "error": e.to_dict()}


NODES_CAMERA_ACTION_INPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["node_id", "action"],
    "properties": {
        "node_id": {"type": "string", "minLength": 1},
        "action": {"type": "string", "enum": sorted(_ALLOWED_ACTIONS)},
        "camera": {"type": ["integer", "null"], "minimum": 0},
        "options": {"type": "object"},
        "timeout_s": {"type": "number", "exclusiveMinimum": 0},
    },
    "additionalProperties": False,
}

NODES_CAMERA_ACTION_OUTPUT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "required": ["ok", "data"],
    "properties": {
        "ok": {"type": "boolean"},
        "data": {
            "type": "object",
            "required": ["ok", "node_id", "action", "camera", "artifact", "payload"],
            "properties": {
                "ok": {"type": "boolean"},
                "node_id": {"type": "string"},
                "action": {"type": "string"},
                "camera": {"type": ["integer", "null"]},
                "artifact": {"type": ["string", "null"]},
                "payload": {"type": "object"},
            },
        },
    },
}

# Framework-friendly aliases (some Thomas components may look for these names).
run = run_nodes_camera_action
execute = execute_nodes_camera_action
parse_request = parse_nodes_camera_action_request
INPUT_SCHEMA = NODES_CAMERA_ACTION_INPUT_SCHEMA
OUTPUT_SCHEMA = NODES_CAMERA_ACTION_OUTPUT_SCHEMA

__all__ = [
    "NodesCameraActionErrorCode",
    "NodesCameraActionError",
    "NodesCameraActionRequest",
    "NodesCameraActionResponse",
    "HttpResponse",
    "parse_nodes_camera_action_request",
    "resolve_nodes_base_url",
    "build_camera_action_url",
    "execute_nodes_camera_action",
    "run_nodes_camera_action",
    "run_nodes_camera_action_safe",
    "NODES_CAMERA_ACTION_INPUT_SCHEMA",
    "NODES_CAMERA_ACTION_OUTPUT_SCHEMA",
    "run",
    "execute",
    "parse_request",
    "INPUT_SCHEMA",
    "OUTPUT_SCHEMA",
]
