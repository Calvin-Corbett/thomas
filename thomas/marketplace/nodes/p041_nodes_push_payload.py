"""Push a JSON payload to one or more Thomas nodes.

This module is designed to be usable from both:

* CLI commands (``thomas.cli.commands.*``)
* HTTP routes / automations (e.g. aiohttp handlers)

The implementation intentionally stays *Thomas-native* and avoids any external tools
terminology.

Contracts
---------

Input
  ``NodesPushPayloadRequest``
    nodes:
      list of node identifiers. Each entry may be:

      * an absolute http(s) URL
        - if the URL's path is root ("/" or empty), ``endpoint_path`` is appended.
        - if the URL already includes a non-root path, it is treated as the full
          target URL.

      * a node ID (any string that is not a URL)
        - IDs require ``node_endpoints`` mapping for resolution.

    payload:
      any JSON-serializable value.

Output
  ``NodesPushPayloadResponse``

Deterministic error handling
----------------------------

* Invalid input raises ``NodesPushPayloadError`` with a stable ``code``.
* Missing/invalid config (e.g. node IDs without a resolver map) raises
  ``NodesPushPayloadError`` with a stable ``code``.
* External failures (timeouts, connection issues, non-2xx HTTP responses) are
  captured *per node* in the response.

Machine-readable mode
---------------------

The functions ``push_payload_to_nodes_from_dict`` and
``push_payload_to_nodes_from_dict_sync`` provide dict-in/dict-out operation.
JSON Schemas for route integration are available via ``REQUEST_JSON_SCHEMA`` and
``RESPONSE_JSON_SCHEMA``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, TypedDict
from urllib.parse import urlparse, urlunparse

import aiohttp

__all__ = [
    "NodesPushPayloadError",
    "NodesPushPayloadRequestDict",
    "NodesPushPayloadResponseDict",
    "NodesPushPayloadRequest",
    "NodePushPayloadResult",
    "NodesPushPayloadResponse",
    "REQUEST_JSON_SCHEMA",
    "RESPONSE_JSON_SCHEMA",
    "request_from_dict",
    "push_payload_to_nodes",
    "push_payload_to_nodes_sync",
    "push_payload_to_nodes_from_dict",
    "push_payload_to_nodes_from_dict_sync",
    "OPERATION_ID",
    "OPERATION_NAME",
    "INPUT_JSON_SCHEMA",
    "OUTPUT_JSON_SCHEMA",
    "execute",
    "execute_sync",
    "execute_from_dict",
    "execute_from_dict_sync",
]


class NodesPushPayloadError(Exception):
    """Base exception with deterministic error codes."""

    code: str
    details: dict[str, Any]

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class NodesPushPayloadRequestDict(TypedDict, total=False):
    nodes: list[str]
    payload: Any
    endpoint_path: str
    timeout_s: float
    concurrency: int
    headers: dict[str, str]
    node_endpoints: dict[str, str]


class NodesPushPayloadResponseDict(TypedDict):
    ok: bool
    total: int
    pushed: int
    failed: int
    results: list[dict[str, Any]]


REQUEST_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["nodes", "payload"],
    "properties": {
        "nodes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "payload": {},
        "endpoint_path": {"type": "string", "default": "/payload"},
        "timeout_s": {"type": "number", "default": 10.0, "minimum": 0.001},
        "concurrency": {"type": "integer", "default": 10, "minimum": 1, "maximum": 1000},
        "headers": {"type": "object", "additionalProperties": {"type": "string"}},
        "node_endpoints": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}

RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "total", "pushed", "failed", "results"],
    "properties": {
        "ok": {"type": "boolean"},
        "total": {"type": "integer"},
        "pushed": {"type": "integer"},
        "failed": {"type": "integer"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["node", "url", "ok", "status", "response_json", "error_code", "error"],
                "properties": {
                    "node": {"type": "string"},
                    "url": {"type": "string"},
                    "ok": {"type": "boolean"},
                    "status": {"type": ["integer", "null"]},
                    "response_json": {},
                    "error_code": {"type": ["string", "null"]},
                    "error": {"type": ["string", "null"]},
                },
            },
        },
    },
}

# Operation identifiers (handy for registry/discovery layers)
OPERATION_ID = "p041_nodes_push_payload"
OPERATION_NAME = "nodes_push_payload"

# Schema aliases (some layers prefer generic names)
INPUT_JSON_SCHEMA = REQUEST_JSON_SCHEMA
OUTPUT_JSON_SCHEMA = RESPONSE_JSON_SCHEMA


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except (json.JSONDecodeError, ValueError, KeyError):
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_json_serializable(payload: Any) -> None:
    try:
        json.dumps(payload)
    except TypeError as e:
        raise NodesPushPayloadError(
            "invalid_input",
            "payload must be JSON-serializable",
            details={"reason": str(e)},
        ) from e


def _normalize_endpoint_path(endpoint_path: str) -> str:
    if not isinstance(endpoint_path, str) or not endpoint_path.strip():
        raise NodesPushPayloadError("invalid_input", "endpoint_path must be a non-empty string")
    endpoint_path = endpoint_path.strip()
    if not endpoint_path.startswith("/"):
        endpoint_path = "/" + endpoint_path
    return endpoint_path


def _append_path(url: str, endpoint_path: str) -> str:
    """Append endpoint_path to url when url has root/empty path.

    Preserves scheme/host/query/fragment and produces deterministic output.
    """

    parsed = urlparse(url)
    base_path = parsed.path or ""
    if base_path and base_path != "/":
        # Non-root path means caller already gave a full target URL.
        return url

    new_path = endpoint_path
    return urlunparse(parsed._replace(path=new_path))


def _resolve_target_url(
    node: str,
    *,
    endpoint_path: str,
    node_endpoints: Mapping[str, str] | None,
) -> str:
    """Resolve a node identifier to a concrete URL."""

    if _is_http_url(node):
        return _append_path(node, endpoint_path)

    if not node_endpoints or node not in node_endpoints:
        raise NodesPushPayloadError(
            "missing_config",
            "node endpoint mapping is required for non-URL node identifiers",
            details={"node": node},
        )

    base = str(node_endpoints[node]).strip()
    if not _is_http_url(base):
        raise NodesPushPayloadError(
            "invalid_config",
            "node endpoint mapping must contain absolute http(s) URLs",
            details={"node": node, "endpoint": base},
        )

    return _append_path(base, endpoint_path)


def _truncate_text(value: str | None, *, limit: int = 4096) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "…(truncated)"


@dataclass(frozen=True)
class NodesPushPayloadRequest:
    nodes: list[str]
    payload: Any

    endpoint_path: str = "/payload"
    timeout_s: float = 10.0
    concurrency: int = 10
    headers: Mapping[str, str] | None = None
    node_endpoints: Mapping[str, str] | None = None


@dataclass(frozen=True)
class NodePushPayloadResult:
    node: str
    url: str
    ok: bool
    status: int | None = None
    response_json: Any = None
    error_code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "url": self.url,
            "ok": self.ok,
            "status": self.status,
            "response_json": self.response_json,
            "error_code": self.error_code,
            "error": self.error,
        }


@dataclass(frozen=True)
class NodesPushPayloadResponse:
    results: list[NodePushPayloadResult] = field(default_factory=list)

    def to_dict(self) -> NodesPushPayloadResponseDict:
        total = len(self.results)
        pushed = sum(1 for r in self.results if r.ok)
        failed = total - pushed
        return {
            "ok": failed == 0,
            "total": total,
            "pushed": pushed,
            "failed": failed,
            "results": [r.to_dict() for r in self.results],
        }


def request_from_dict(data: Mapping[str, Any]) -> NodesPushPayloadRequest:
    """Create a request object from a mapping."""

    if not isinstance(data, Mapping):
        raise NodesPushPayloadError("invalid_input", "request must be an object")

    nodes_raw = data.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise NodesPushPayloadError("invalid_input", "nodes must be a non-empty list")

    nodes: list[str] = []
    for n in nodes_raw:
        if not isinstance(n, str) or not n.strip():
            raise NodesPushPayloadError(
                "invalid_input",
                "nodes entries must be non-empty strings",
                details={"node": n},
            )
        nodes.append(n.strip())

    if "payload" not in data:
        raise NodesPushPayloadError("invalid_input", "payload is required")
    payload = data.get("payload")

    endpoint_path = data.get("endpoint_path", "/payload")
    if not isinstance(endpoint_path, str):
        raise NodesPushPayloadError("invalid_input", "endpoint_path must be a string")

    timeout_s = data.get("timeout_s", 10.0)
    try:
        timeout_s_f = float(timeout_s)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise NodesPushPayloadError("invalid_input", "timeout_s must be a number") from e

    concurrency = data.get("concurrency", 10)
    try:
        concurrency_i = int(concurrency)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        raise NodesPushPayloadError("invalid_input", "concurrency must be an integer") from e

    headers_raw = data.get("headers")
    headers: dict[str, str] | None = None
    if headers_raw is not None:
        if not isinstance(headers_raw, dict):
            raise NodesPushPayloadError("invalid_input", "headers must be an object")
        headers = {str(k): str(v) for k, v in headers_raw.items()}

    node_endpoints_raw = data.get("node_endpoints")
    node_endpoints: dict[str, str] | None = None
    if node_endpoints_raw is not None:
        if not isinstance(node_endpoints_raw, dict):
            raise NodesPushPayloadError("invalid_input", "node_endpoints must be an object")
        node_endpoints = {str(k): str(v) for k, v in node_endpoints_raw.items()}

    return NodesPushPayloadRequest(
        nodes=nodes,
        payload=payload,
        endpoint_path=endpoint_path,
        timeout_s=timeout_s_f,
        concurrency=concurrency_i,
        headers=headers,
        node_endpoints=node_endpoints,
    )


async def push_payload_to_nodes_from_dict(data: Mapping[str, Any]) -> NodesPushPayloadResponseDict:
    resp = await push_payload_to_nodes(request_from_dict(data))
    return resp.to_dict()


def push_payload_to_nodes_from_dict_sync(data: Mapping[str, Any]) -> NodesPushPayloadResponseDict:
    resp = push_payload_to_nodes_sync(request_from_dict(data))
    return resp.to_dict()


async def push_payload_to_nodes(req: NodesPushPayloadRequest) -> NodesPushPayloadResponse:
    """Push payload to nodes.

    Raises:
        NodesPushPayloadError: for invalid input or missing/invalid configuration.
    """

    if not isinstance(req.nodes, list) or not req.nodes:
        raise NodesPushPayloadError("invalid_input", "nodes must be a non-empty list")

    if req.timeout_s <= 0:
        raise NodesPushPayloadError("invalid_input", "timeout_s must be > 0")

    if req.concurrency <= 0:
        raise NodesPushPayloadError("invalid_input", "concurrency must be > 0")

    if req.concurrency > 1000:
        raise NodesPushPayloadError("invalid_input", "concurrency is unreasonably large")

    endpoint_path = _normalize_endpoint_path(req.endpoint_path)
    _validate_json_serializable(req.payload)

    headers: MutableMapping[str, str] = {}
    if req.headers:
        headers.update({str(k): str(v) for k, v in req.headers.items()})

    # Resolve targets up-front to make config errors deterministic and avoid
    # partial execution.
    targets = [
        (node, _resolve_target_url(node, endpoint_path=endpoint_path, node_endpoints=req.node_endpoints))
        for node in req.nodes
    ]

    timeout = aiohttp.ClientTimeout(total=req.timeout_s)
    semaphore = asyncio.Semaphore(req.concurrency)

    async def _push_one(node: str, url: str, session: aiohttp.ClientSession) -> NodePushPayloadResult:
        async with semaphore:
            try:
                async with session.post(url, json=req.payload) as resp:
                    status = resp.status

                    response_json: Any = None
                    try:
                        response_json = await resp.json(content_type=None)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        response_json = None

                    if 200 <= status < 300:
                        return NodePushPayloadResult(
                            node=node,
                            url=url,
                            ok=True,
                            status=status,
                            response_json=response_json,
                        )

                    err_text: str | None
                    try:
                        err_text = await resp.text()
                    except (json.JSONDecodeError, ValueError, KeyError):
                        err_text = None

                    return NodePushPayloadResult(
                        node=node,
                        url=url,
                        ok=False,
                        status=status,
                        response_json=response_json,
                        error_code="remote_error",
                        error=_truncate_text(err_text) or f"HTTP {status}",
                    )

            except asyncio.TimeoutError:
                return NodePushPayloadResult(
                    node=node,
                    url=url,
                    ok=False,
                    error_code="timeout",
                    error="request timed out",
                )
            except aiohttp.ClientError as e:
                return NodePushPayloadResult(
                    node=node,
                    url=url,
                    ok=False,
                    error_code="transport_error",
                    error=_truncate_text(f"{type(e).__name__}: {e}"),
                )
            except (json.JSONDecodeError, ValueError, KeyError) as e:  # pragma: no cover
                return NodePushPayloadResult(
                    node=node,
                    url=url,
                    ok=False,
                    error_code="unexpected_error",
                    error=_truncate_text(f"{type(e).__name__}: {e}"),
                )

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        results = list(await asyncio.gather(*[_push_one(node, url, session) for node, url in targets]))

    return NodesPushPayloadResponse(results=results)


def push_payload_to_nodes_sync(req: NodesPushPayloadRequest) -> NodesPushPayloadResponse:
    """Synchronous wrapper.

    Note: This cannot be called from within an already-running asyncio loop.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise NodesPushPayloadError(
            "invalid_state",
            "push_payload_to_nodes_sync cannot be called from a running event loop",
        )

    return asyncio.run(push_payload_to_nodes(req))


async def execute(req: NodesPushPayloadRequest) -> NodesPushPayloadResponse:
    """Alias for :func:`push_payload_to_nodes` (registry-friendly)."""

    return await push_payload_to_nodes(req)


def execute_sync(req: NodesPushPayloadRequest) -> NodesPushPayloadResponse:
    """Alias for :func:`push_payload_to_nodes_sync` (registry-friendly)."""

    return push_payload_to_nodes_sync(req)


async def execute_from_dict(data: Mapping[str, Any]) -> NodesPushPayloadResponseDict:
    """Alias for :func:`push_payload_to_nodes_from_dict` (dict-in/dict-out)."""

    return await push_payload_to_nodes_from_dict(data)


def execute_from_dict_sync(data: Mapping[str, Any]) -> NodesPushPayloadResponseDict:
    """Alias for :func:`push_payload_to_nodes_from_dict_sync` (dict-in/dict-out)."""

    return push_payload_to_nodes_from_dict_sync(data)
