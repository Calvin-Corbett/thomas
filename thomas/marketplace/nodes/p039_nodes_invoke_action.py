"""Node action invocation (Thomas-native).

This module provides a small, well-typed contract for invoking a **named action** on a
configured **node**.

It is intentionally self-contained so it can be reused from:
- the Thomas CLI (sync, via ``requests``)
- the Thomas HTTP server (async, via an aiohttp route handler)

The surrounding Thomas codebase decides *how* nodes are addressed and authenticated.
This module provides deterministic error taxonomy, minimal configuration helpers,
and machine-readable success/error payloads.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlparse

import requests

DEFAULT_INVOKE_PATH = "/actions/invoke"
DEFAULT_REGISTRY_HOME_PATH = Path.home() / ".thomas" / "nodes.json"


class NodeInvokeActionError(RuntimeError):
    """Base error for node action invocation.

    ``code`` is intended for machine consumption.
    ``http_status`` is the suggested HTTP status if surfaced via an API.
    """

    code = "node_invoke_action_error"
    http_status = 500

    def __init__(self, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.details: dict[str, Any] = dict(details or {})

    def to_error_payload(self) -> ErrorPayload:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details or None,
        }


class InvalidInvokeActionInput(NodeInvokeActionError):
    code = "invalid_input"
    http_status = 400


class MissingNodeConfig(NodeInvokeActionError):
    code = "missing_config"
    http_status = 404


class TransportFailure(NodeInvokeActionError):
    code = "transport_failure"
    http_status = 503


class RemoteFailure(NodeInvokeActionError):
    code = "remote_failure"
    http_status = 502


class InvalidRemoteResponse(NodeInvokeActionError):
    code = "invalid_remote_response"
    http_status = 502


class ErrorPayload(TypedDict, total=False):
    code: str
    message: str
    details: Mapping[str, Any] | None


class InvokeActionResponsePayload(TypedDict, total=False):
    ok: bool
    node: str
    action: str
    status_code: int
    result: Any
    error: ErrorPayload


@dataclass(frozen=True)
class InvokeActionRequest:
    """Input contract for invoking an action on a node."""

    node: str
    action: str
    payload: Mapping[str, Any] | None = None
    timeout_s: float = 30.0
    request_id: str | None = None


@dataclass(frozen=True)
class InvokeActionResponse:
    """Output contract for invoking an action on a node."""

    ok: bool
    node: str
    action: str
    status_code: int
    result: Any | None = None


def _looks_like_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except (json.JSONDecodeError, ValueError, KeyError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _coerce_registry_mapping(raw: Any) -> dict[str, str]:
    """Coerce various JSON shapes into a {node_id: base_url} mapping."""

    if raw is None:
        return {}

    if isinstance(raw, dict):
        out: dict[str, str] = {}
        for k, v in raw.items():
            if isinstance(v, str):
                out[str(k)] = v
            elif isinstance(v, dict) and isinstance(v.get("url"), str):
                out[str(k)] = v["url"]
        return out

    raise ValueError("node registry must be a JSON object")


def load_node_registry() -> dict[str, str]:
    """Load the node registry mapping.

    Precedence (highest first):
      1) THOMAS_NODE_REGISTRY (JSON mapping)
      2) THOMAS_NODE_REGISTRY_FILE (JSON file)
      3) ~/.thomas/nodes.json (JSON file)

    Registry values may be either a URL string or an object containing a "url" field.
    """

    env_inline = os.environ.get("THOMAS_NODE_REGISTRY")
    if env_inline:
        try:
            return _coerce_registry_mapping(json.loads(env_inline))
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            raise MissingNodeConfig(
                "Invalid THOMAS_NODE_REGISTRY JSON",
                details={"source": "env", "error": exc.__class__.__name__},
            ) from exc

    candidates: list[Path] = []
    env_file = os.environ.get("THOMAS_NODE_REGISTRY_FILE")
    if env_file:
        candidates.append(Path(env_file))
    candidates.append(DEFAULT_REGISTRY_HOME_PATH)

    for path in candidates:
        try:
            if not path.exists():
                continue
            raw = path.read_text(encoding="utf-8")
            return _coerce_registry_mapping(json.loads(raw))
        except FileNotFoundError:
            continue
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            raise MissingNodeConfig(
                "Invalid node registry file",
                details={
                    "source": "file",
                    "path": str(path),
                    "error": exc.__class__.__name__,
                },
            ) from exc

    return {}


def resolve_node_base_url(node: str, *, registry: Mapping[str, str] | None = None) -> str:
    """Resolve a node identifier to a base URL."""

    node = (node or "").strip()
    if not node:
        raise InvalidInvokeActionInput("node is required")

    if _looks_like_url(node):
        return node.rstrip("/")

    reg: dict[str, str] = dict(registry or load_node_registry())
    base = reg.get(node)
    if not base:
        raise MissingNodeConfig("Unknown node; no endpoint configured", details={"node": node})

    if not _looks_like_url(base):
        raise MissingNodeConfig(
            "Node endpoint is not a valid http(s) URL",
            details={"node": node, "endpoint": base},
        )

    return base.rstrip("/")


def build_invoke_url(base_url: str) -> str:
    """Build the URL used to invoke an action on a node."""

    base_url = (base_url or "").rstrip("/")
    if not base_url:
        raise InvalidInvokeActionInput("base_url is required")

    path = os.environ.get("THOMAS_NODE_INVOKE_PATH", DEFAULT_INVOKE_PATH)
    if not path.startswith("/"):
        path = "/" + path

    return base_url + path


def _auth_headers() -> dict[str, str]:
    """Optional auth header injection.

    If THOMAS_NODE_AUTH_TOKEN is set, send an auth header.

    - THOMAS_NODE_AUTH_HEADER (default: Authorization)
    - THOMAS_NODE_AUTH_SCHEME (default: Bearer)

    If scheme is set to empty string, the token will be sent as-is.
    """

    token = os.environ.get("THOMAS_NODE_AUTH_TOKEN")
    if not token:
        return {}

    header = os.environ.get("THOMAS_NODE_AUTH_HEADER", "Authorization")
    scheme = os.environ.get("THOMAS_NODE_AUTH_SCHEME", "Bearer")

    value = (f"{scheme} {token}".strip() if scheme else token).strip()
    return {header: value}


def invoke_action(
    req: InvokeActionRequest,
    *,
    registry: Mapping[str, str] | None = None,
    session: requests.Session | None = None,
) -> InvokeActionResponse:
    """Invoke an action on a node and return the parsed response.

    Raises:
        InvalidInvokeActionInput
        MissingNodeConfig
        TransportFailure
        RemoteFailure
        InvalidRemoteResponse
    """

    node = (req.node or "").strip()
    action = (req.action or "").strip()

    if not node:
        raise InvalidInvokeActionInput("node is required")
    if not action:
        raise InvalidInvokeActionInput("action is required")

    try:
        timeout_s = float(req.timeout_s)
    except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as exc:
        raise InvalidInvokeActionInput("timeout_s must be a number") from exc
    if timeout_s <= 0:
        raise InvalidInvokeActionInput("timeout_s must be > 0")

    if req.payload is None:
        payload_obj: Mapping[str, Any] = {}
    elif isinstance(req.payload, Mapping):
        payload_obj = req.payload
    else:
        raise InvalidInvokeActionInput("payload must be a JSON object")

    base_url = resolve_node_base_url(node, registry=registry)
    url = build_invoke_url(base_url)

    body: dict[str, Any] = {"action": action, "payload": payload_obj}
    if req.request_id:
        body["request_id"] = req.request_id

    http = session or requests

    headers: dict[str, str] = {"Accept": "application/json"}
    headers.update(_auth_headers())

    try:
        resp = http.post(url, json=body, timeout=timeout_s, headers=headers)
    except requests.RequestException as exc:
        raise TransportFailure(
            "Failed to reach node endpoint",
            details={
                "node": node,
                "action": action,
                "endpoint": base_url,
                "url": url,
                "error": exc.__class__.__name__,
            },
        ) from exc

    status = int(getattr(resp, "status_code", 0) or 0)

    def _safe_text() -> str:
        try:
            return str(getattr(resp, "text", ""))
        except (ImportError, AttributeError, RuntimeError):
            return ""

    def _safe_json() -> Any:
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError, KeyError):
            return _safe_text() or None

    if status < 200 or status >= 300:
        raise RemoteFailure(
            "Node returned a non-success status",
            details={"node": node, "action": action, "status_code": status, "body": _safe_json()},
        )

    parsed = _safe_json()

    # Some nodes may return HTTP 200 with an error payload. Treat this as failure.
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        raise RemoteFailure(
            "Node reported failure",
            details={
                "node": node,
                "action": action,
                "status_code": status,
                "error": parsed.get("error") or parsed,
            },
        )

    # Normalise common shapes.
    if isinstance(parsed, dict):
        if "result" in parsed:
            result: Any = parsed.get("result")
        elif "data" in parsed:
            result = parsed.get("data")
        else:
            result = parsed
    else:
        result = parsed

    return InvokeActionResponse(ok=True, node=node, action=action, status_code=status, result=result)


def response_to_payload(resp: InvokeActionResponse) -> InvokeActionResponsePayload:
    return {
        "ok": bool(resp.ok),
        "node": resp.node,
        "action": resp.action,
        "status_code": int(resp.status_code),
        "result": resp.result,
    }


def error_to_payload(
    exc: NodeInvokeActionError,
    *,
    node: str | None = None,
    action: str | None = None,
) -> InvokeActionResponsePayload:
    return {
        "ok": False,
        "node": (node or ""),
        "action": (action or ""),
        "status_code": int(exc.http_status),
        "error": exc.to_error_payload(),
    }


def invoke_action_payload(
    req: InvokeActionRequest,
    *,
    registry: Mapping[str, str] | None = None,
    session: requests.Session | None = None,
) -> InvokeActionResponsePayload:
    """Invoke an action, returning a machine-friendly payload instead of raising."""

    try:
        resp = invoke_action(req, registry=registry, session=session)
        return response_to_payload(resp)
    except NodeInvokeActionError as exc:
        return error_to_payload(exc, node=req.node, action=req.action)


# Optional aiohttp integration -------------------------------------------------

try:  # pragma: no cover
    from aiohttp import web  # type: ignore
except (json.JSONDecodeError, ValueError, KeyError):  # pragma: no cover
    web = None  # type: ignore


if web is not None:  # pragma: no cover
    routes = web.RouteTableDef()

    @routes.post("/nodes/invoke-action")
    async def handle_nodes_invoke_action(request: web.Request) -> web.StreamResponse:
        """HTTP route: POST /nodes/invoke-action

        Expected JSON body:
          {"node": "node-1", "action": "ping", "payload": {...}, "timeout_s": 30}

        Response:
          200: {"ok": true, ...}
          4xx/5xx: {"ok": false, "error": {"code": ..., "message": ...}}
        """

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError, KeyError):
            err = InvalidInvokeActionInput("body must be valid JSON")
            return web.json_response(error_to_payload(err), status=err.http_status)

        node = str(body.get("node", "") or "")
        action = str(body.get("action", "") or "")
        payload_any = body.get("payload", None)

        payload: Mapping[str, Any] | None
        if payload_any is None:
            payload = None
        elif isinstance(payload_any, Mapping):
            payload = payload_any
        else:
            err = InvalidInvokeActionInput("payload must be a JSON object")
            return web.json_response(error_to_payload(err, node=node, action=action), status=err.http_status)

        try:
            timeout_s = float(body.get("timeout_s", 30.0))
        except (json.JSONDecodeError, ValueError, KeyError):
            err = InvalidInvokeActionInput("timeout_s must be a number")
            return web.json_response(error_to_payload(err, node=node, action=action), status=err.http_status)

        request_id = body.get("request_id")
        if request_id is not None:
            request_id = str(request_id)

        req_obj = InvokeActionRequest(
            node=node,
            action=action,
            payload=payload,
            timeout_s=timeout_s,
            request_id=request_id,
        )

        # invoke_action uses requests (blocking), so run it off the event loop.
        try:
            to_thread = getattr(asyncio, "to_thread", None)
            if callable(to_thread):
                payload_out = await to_thread(invoke_action_payload, req_obj)
            else:
                loop = asyncio.get_event_loop()
                payload_out = await loop.run_in_executor(None, invoke_action_payload, req_obj)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            err = TransportFailure(
                "Failed to invoke node action",
                details={"node": node, "action": action, "error": exc.__class__.__name__},
            )
            payload_out = error_to_payload(err, node=node, action=action)

        status = 200 if payload_out.get("ok") else int(payload_out.get("status_code") or 500)
        return web.json_response(payload_out, status=status)
