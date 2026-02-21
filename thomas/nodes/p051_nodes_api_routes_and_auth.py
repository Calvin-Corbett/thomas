"""
Nodes HTTP API: routes + auth.

This module provides an aiohttp route table for Nodes endpoints plus a small,
deterministic authentication layer.

Design goals
- Thomas-native behavior (no upstream naming reuse).
- Deterministic failures: stable JSON envelopes with explicit error codes.
- Automation-friendly: a JSON schema endpoint describes routes and auth.

Public surface
- routes: aiohttp.web.RouteTableDef
- register(app_or_router, prefix="/api") -> None
- get_nodes_api_schema(prefix="/api") -> NodesApiSchema
- require_nodes_api_auth(request) -> None  (raises NodesApiError)
- InMemoryNodeStore: small store for tests and dev
"""

from __future__ import annotations

from dataclasses import dataclass, field
import asyncio
import hmac
import os
import re
from typing import Any, Iterable, Mapping, MutableMapping, Protocol, Sequence, TypedDict, cast, runtime_checkable

from aiohttp import web


# -----------------------------
# Contracts
# -----------------------------

class ErrorBody(TypedDict):
    code: str
    message: str
    details: dict[str, Any]


class ErrorEnvelope(TypedDict):
    ok: bool
    error: ErrorBody


class NodesApiAuthSpec(TypedDict):
    """Machine-readable auth requirements for the Nodes API."""
    type: str  # e.g. "bearer"
    header: str  # e.g. "Authorization"
    scheme: str  # e.g. "Bearer"
    token_env_vars: list[str]
    app_config_keys: list[str]
    alt_headers: list[str]


class NodesApiRouteSpec(TypedDict):
    """Machine-readable description of a single API route."""
    method: str
    path: str
    name: str
    summary: str
    auth_required: bool


class NodesApiSchema(TypedDict):
    """Machine-readable schema describing the Nodes API surface."""
    name: str
    version: str
    base_prefix: str
    auth: NodesApiAuthSpec
    routes: list[NodesApiRouteSpec]
    envelopes: dict[str, Any]


class NodeView(TypedDict, total=False):
    """A JSON-safe view of a node."""
    id: str
    label: str
    status: str


@dataclass(frozen=True)
class NodeRecord:
    """Simple node record used by the default in-memory store."""
    id: str
    label: str | None = None
    status: str = "unknown"

    def to_view(self) -> NodeView:
        out: NodeView = {"id": self.id, "status": self.status}
        if self.label is not None:
            out["label"] = self.label
        return out


@runtime_checkable
class NodeStore(Protocol):
    """Abstract node storage interface expected by the API handlers."""
    async def list_nodes(self) -> Sequence[NodeRecord | Mapping[str, Any]]:
        ...

    async def get_node(self, node_id: str) -> NodeRecord | Mapping[str, Any] | None:
        ...


class InMemoryNodeStore:
    """Trivial node store suitable for tests and local dev."""
    def __init__(self, nodes: Iterable[NodeRecord] | None = None) -> None:
        self._nodes: dict[str, NodeRecord] = {n.id: n for n in (nodes or [])}

    async def list_nodes(self) -> Sequence[NodeRecord]:
        return list(self._nodes.values())

    async def get_node(self, node_id: str) -> NodeRecord | None:
        return self._nodes.get(node_id)


# -----------------------------
# Errors
# -----------------------------

@dataclass(frozen=True)
class NodesApiError(Exception):
    code: str
    message: str
    http_status: int
    details: Mapping[str, Any] = field(default_factory=dict)

    def envelope(self) -> ErrorEnvelope:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": dict(self.details),
            },
        }


def _json_error(err: NodesApiError) -> web.Response:
    headers: dict[str, str] = {}
    if err.http_status == 401:
        # Conventional for bearer token auth; also helps clients debug.
        headers["WWW-Authenticate"] = "Bearer"
    return web.json_response(err.envelope(), status=err.http_status, headers=headers)


def _json_ok(payload: Mapping[str, Any], *, status: int = 200) -> web.Response:
    body = {"ok": True, **dict(payload)}
    return web.json_response(body, status=status)


def _err_invalid_input(message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code="invalid_input", message=message, http_status=400, details=details or {})


def _err_unauthorized(code: str, message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code=code, message=message, http_status=401, details=details or {})


def _err_missing_config(message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code="auth_not_configured", message=message, http_status=500, details=details or {})


def _err_external_failure(message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code="external_failure", message=message, http_status=502, details=details or {})


def _err_not_found(message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code="not_found", message=message, http_status=404, details=details or {})


def _err_internal(message: str, *, details: Mapping[str, Any] | None = None) -> NodesApiError:
    return NodesApiError(code="internal_error", message=message, http_status=500, details=details or {})


# -----------------------------
# Auth
# -----------------------------

DEFAULT_TOKEN_ENV_VARS: tuple[str, ...] = (
    "THOMAS_NODES_API_TOKEN",
    "THOMAS_API_TOKEN",
)

DEFAULT_APP_TOKEN_KEYS: tuple[str, ...] = (
    "nodes_api_token",
    "api_token",
    "auth_token",
    "token",
)

DEFAULT_ALT_TOKEN_HEADERS: tuple[str, ...] = (
    "X-Thomas-Token",
    "X-Api-Key",
    "X-API-Key",
    "X-Auth-Token",
)

_PARENT_APP_KEYS: tuple[str, ...] = (
    # Most likely names
    "root_app",
    "parent_app",
    # Defensive/private-ish
    "_root_app",
    "_parent_app",
)


def _iter_app_candidates(app: MutableMapping[str, Any]) -> Iterable[MutableMapping[str, Any]]:
    """
    Yield app, then any configured parent/root apps.

    This supports aiohttp subapps where request.app points at the subapp, while
    configuration/state might live on the root app.
    """
    seen: set[int] = set()
    cur: MutableMapping[str, Any] | None = app
    for _ in range(4):
        if cur is None:
            break
        cur_id = id(cur)
        if cur_id in seen:
            break
        seen.add(cur_id)
        yield cur

        nxt: Any = None
        for k in _PARENT_APP_KEYS:
            if isinstance(cur, Mapping) and k in cur:
                nxt = cur.get(k)
                break
        if isinstance(nxt, MutableMapping):
            cur = cast(MutableMapping[str, Any], nxt)
        else:
            cur = None


def _resolve_expected_token(app: MutableMapping[str, Any]) -> str | None:
    # Direct keys on the app mapping
    for key in DEFAULT_APP_TOKEN_KEYS:
        value = app.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # Nested config object, if present
    cfg = app.get("config") or app.get("settings") or app.get("cfg")
    if cfg is not None:
        if isinstance(cfg, Mapping):
            for key in DEFAULT_APP_TOKEN_KEYS:
                value = cfg.get(key)  # type: ignore[arg-type]
                if isinstance(value, str) and value.strip():
                    return value.strip()
        else:
            for key in DEFAULT_APP_TOKEN_KEYS:
                value = getattr(cfg, key, None)
                if isinstance(value, str) and value.strip():
                    return value.strip()

    # Environment
    for env_key in DEFAULT_TOKEN_ENV_VARS:
        value = os.environ.get(env_key)
        if value and value.strip():
            return value.strip()

    return None


def _extract_provided_token(headers: Mapping[str, str]) -> str | None:
    # Standard bearer token
    auth_header = headers.get("Authorization") or headers.get("authorization")
    if auth_header:
        parts = auth_header.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            return token or None

    # Alternative headers
    for key in DEFAULT_ALT_TOKEN_HEADERS:
        val = headers.get(key)
        if val and val.strip():
            return val.strip()

    return None


def require_nodes_api_auth(request: web.Request) -> None:
    """
    Enforce bearer-token authentication for Nodes API routes.

    Expected token sources (first match wins):
    - request.app[<token key>]
    - request.app['config'|'settings'|'cfg'][<token key>] (mapping) or attribute (object)
    - environment variables: THOMAS_NODES_API_TOKEN, THOMAS_API_TOKEN

    Provided token sources:
    - Authorization: Bearer <token>
    - X-Thomas-Token / X-Api-Key / X-Auth-Token
    """
    app = cast(MutableMapping[str, Any], request.app)
    expected: str | None = None
    for candidate in _iter_app_candidates(app):
        expected = _resolve_expected_token(candidate)
        if expected is not None:
            break

    if expected is None:
        raise _err_missing_config(
            "Nodes API auth token is not configured.",
            details={
                "token_env_vars": list(DEFAULT_TOKEN_ENV_VARS),
                "app_config_keys": list(DEFAULT_APP_TOKEN_KEYS),
            },
        )

    provided = _extract_provided_token(request.headers)
    if provided is None:
        raise _err_unauthorized(
            "missing_token",
            "Missing API token. Provide Authorization: Bearer <token>.",
            details={"header": "Authorization", "scheme": "Bearer"},
        )

    if not hmac.compare_digest(provided, expected):
        raise _err_unauthorized("invalid_token", "Invalid API token.")


# -----------------------------
# Nodes helpers
# -----------------------------

_NODE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_node_id(node_id: str) -> str:
    if not _NODE_ID_RE.match(node_id):
        raise _err_invalid_input(
            "Invalid node id.",
            details={"node_id": node_id, "pattern": _NODE_ID_RE.pattern},
        )
    return node_id


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _normalize_node(obj: NodeRecord | Mapping[str, Any]) -> NodeView:
    if isinstance(obj, NodeRecord):
        return obj.to_view()

    node_id = obj.get("id") or obj.get("node_id") or obj.get("name")
    if not isinstance(node_id, str) or not node_id:
        node_id = "unknown"

    out: NodeView = {"id": node_id}

    label = obj.get("label") or obj.get("display_name") or obj.get("title")
    if isinstance(label, str) and label:
        out["label"] = label

    status = obj.get("status")
    out["status"] = status if isinstance(status, str) and status else "unknown"
    return out


def _resolve_store(app: MutableMapping[str, Any]) -> NodeStore | None:
    store = (
        app.get("node_store")
        or app.get("nodes_store")
        or app.get("nodes")
        or app.get("node_manager")
    )
    if store is None:
        return None
    return cast(NodeStore, store)


def _get_store_from_request(request: web.Request) -> NodeStore | None:
    app = cast(MutableMapping[str, Any], request.app)
    for candidate in _iter_app_candidates(app):
        store = _resolve_store(candidate)
        if store is not None:
            return store
    return None


# -----------------------------
# Route schema
# -----------------------------

API_NAME = "nodes"
API_VERSION = "1.0"

_ROUTE_DEFS: list[NodesApiRouteSpec] = [
    {
        "method": "GET",
        "path": "/nodes",
        "name": "nodes.list",
        "summary": "List known nodes.",
        "auth_required": True,
    },
    {
        "method": "GET",
        "path": "/nodes/{node_id}",
        "name": "nodes.get",
        "summary": "Fetch a single node by id.",
        "auth_required": True,
    },
    {
        "method": "GET",
        "path": "/nodes/schema",
        "name": "nodes.schema",
        "summary": "Return a machine-readable schema for this API.",
        "auth_required": True,
    },
]


def get_nodes_api_schema(*, prefix: str = "/api") -> NodesApiSchema:
    prefix_norm = prefix.rstrip("/") if prefix and prefix != "/" else ""
    routes_out: list[NodesApiRouteSpec] = []
    for r in _ROUTE_DEFS:
        routes_out.append({**r, "path": f"{prefix_norm}{r['path']}"})

    return {
        "name": API_NAME,
        "version": API_VERSION,
        "base_prefix": prefix,
        "auth": {
            "type": "bearer",
            "header": "Authorization",
            "scheme": "Bearer",
            "token_env_vars": list(DEFAULT_TOKEN_ENV_VARS),
            "app_config_keys": list(DEFAULT_APP_TOKEN_KEYS),
            "alt_headers": list(DEFAULT_ALT_TOKEN_HEADERS),
        },
        "routes": routes_out,
        "envelopes": {
            "success": {"ok": True, "...": "payload"},
            "error": {
                "ok": False,
                "error": {"code": "string", "message": "string", "details": {"...": "any"}},
            },
        },
    }


def _registered_prefix_from_request(request: web.Request) -> str:
    app = cast(MutableMapping[str, Any], request.app)
    for candidate in _iter_app_candidates(app):
        pref = candidate.get("nodes_api_prefix") or candidate.get("api_prefix") or candidate.get("api_base")
        if isinstance(pref, str) and pref:
            return pref
    return "/api"


# -----------------------------
# Aiohttp routes
# -----------------------------

routes = web.RouteTableDef()


@routes.get("/nodes")
async def list_nodes(request: web.Request) -> web.Response:
    try:
        require_nodes_api_auth(request)
        store = _get_store_from_request(request)
        if store is None:
            raise _err_external_failure("Node store is not available.", details={"missing": True})

        try:
            raw = await _maybe_await(store.list_nodes())
        except Exception as e:  # noqa: BLE001 - deterministic wrapper below
            raise _err_external_failure(
                "Node store failed while listing nodes.",
                details={"exception": type(e).__name__},
            ) from e

        nodes = [_normalize_node(n) for n in cast(Sequence[Any], raw)]
        return _json_ok({"nodes": nodes, "count": len(nodes)})

    except NodesApiError as e:
        return _json_error(e)
    except Exception as e:  # noqa: BLE001
        return _json_error(_err_internal("Internal server error.", details={"exception": type(e).__name__}))


@routes.get("/nodes/{node_id}")
async def get_node(request: web.Request) -> web.Response:
    try:
        require_nodes_api_auth(request)
        node_id = _validate_node_id(request.match_info.get("node_id", ""))

        store = _get_store_from_request(request)
        if store is None:
            raise _err_external_failure("Node store is not available.", details={"missing": True})

        try:
            node = await _maybe_await(store.get_node(node_id))
        except Exception as e:  # noqa: BLE001
            raise _err_external_failure(
                "Node store failed while fetching node.",
                details={"exception": type(e).__name__, "node_id": node_id},
            ) from e

        if node is None:
            raise _err_not_found("Node not found.", details={"node_id": node_id})

        return _json_ok({"node": _normalize_node(cast(Any, node))})

    except NodesApiError as e:
        return _json_error(e)
    except Exception as e:  # noqa: BLE001
        return _json_error(_err_internal("Internal server error.", details={"exception": type(e).__name__}))


@routes.get("/nodes/schema")
async def schema(request: web.Request) -> web.Response:
    try:
        require_nodes_api_auth(request)
        prefix = _registered_prefix_from_request(request)
        return _json_ok({"schema": get_nodes_api_schema(prefix=prefix)})
    except NodesApiError as e:
        return _json_error(e)
    except Exception as e:  # noqa: BLE001
        return _json_error(_err_internal("Internal server error.", details={"exception": type(e).__name__}))


def register(app_or_router: Any, *, prefix: str = "/api") -> None:
    """
    Register Nodes API routes.

    Supports two patterns:
    1) aiohttp.web.Application: registers either directly (no prefix) or as a
       subapp mounted under `prefix` to keep the route table clean.
    2) aiohttp.web.UrlDispatcher / router-like: directly adds prefixed routes.

    When a subapp is created, it stores a reference to the root app under
    subapp['root_app'] so handlers can resolve shared config and stores.
    """
    # Store prefix on anything mapping-like (aiohttp Application is a MutableMapping)
    try:
        if isinstance(app_or_router, MutableMapping):
            cast(MutableMapping[str, Any], app_or_router)["nodes_api_prefix"] = prefix
    except Exception:
        # Not fatal; schema will fall back to /api.
        pass

    if isinstance(app_or_router, web.Application):
        # No-prefix registration: attach routes directly to the app.
        if not prefix or prefix == "/":
            app_or_router.add_routes(routes)
            return

        # Prefix registration: mount as a subapp to preserve route metadata.
        subapp = web.Application()
        subapp["nodes_api_prefix"] = prefix
        subapp["root_app"] = app_or_router
        subapp.add_routes(routes)

        mount = prefix.rstrip("/")
        if not mount.startswith("/"):
            mount = "/" + mount
        app_or_router.add_subapp(mount, subapp)
        return

    # Router-like fallback
    router = getattr(app_or_router, "router", app_or_router)
    prefix_norm = prefix.rstrip("/") if prefix and prefix != "/" else ""
    for r in routes:
        method = r.method
        path = f"{prefix_norm}{r.path}"
        router.add_route(method, path, r.handler, **r.kwargs)
