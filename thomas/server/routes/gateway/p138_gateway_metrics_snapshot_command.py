from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, MutableMapping, Optional, TypedDict, cast

from aiohttp import ClientError, ClientSession, ClientTimeout, web

# Local route table for this module. The Thomas app loader can add this table directly.
routes = web.RouteTableDef()
ROUTES = routes

# Prefer aiohttp AppKey for application dict keys (avoids NotAppKeyWarning), but accept plain-string keys too.
_AppKey = getattr(web, "AppKey", None)
if _AppKey is not None:  # pragma: no cover
    SNAPSHOTTER_APP_KEY = web.AppKey("gateway_metrics_snapshotter", object)  # type: ignore[attr-defined]
    CONFIG_APP_KEY = web.AppKey("config", dict)  # type: ignore[attr-defined]
    _ROUTE_TABLE_IDS_ADDED_KEY = web.AppKey("thomas_route_table_ids_added", set)  # type: ignore[attr-defined]
else:  # pragma: no cover
    SNAPSHOTTER_APP_KEY = "gateway_metrics_snapshotter"
    CONFIG_APP_KEY = "config"
    _ROUTE_TABLE_IDS_ADDED_KEY = "_thomas_route_table_ids_added"


class GatewayMetricsSnapshotRequest(TypedDict, total=False):
    reset: bool
    window_seconds: int


class GatewayMetricsSnapshotErrorInfo(TypedDict, total=False):
    code: str
    message: str
    details: Mapping[str, Any]


class GatewayMetricsSnapshotFailure(TypedDict):
    ok: bool
    error: GatewayMetricsSnapshotErrorInfo


class GatewayMetricsSnapshotSuccess(TypedDict):
    ok: bool
    taken_at: str
    source: str
    request: GatewayMetricsSnapshotRequest
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class _ParsedRequest:
    reset: bool
    window_seconds: Optional[int]


class _SnapshotError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


_TRUE_STRINGS = {"1", "true", "t", "yes", "y", "on"}
_FALSE_STRINGS = {"0", "false", "f", "no", "n", "off"}
_LAST_INPROCESS_SNAPSHOTTER: Optional[Callable[..., Any]] = None


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()


def _json_response(payload: Mapping[str, Any], *, status: int) -> web.Response:
    return web.json_response(payload, status=status)


def _parse_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE_STRINGS:
            return True
        if v in _FALSE_STRINGS:
            return False
    raise _SnapshotError(
        "invalid_request",
        "Field 'reset' must be a boolean.",
        http_status=400,
        details={"field": "reset"},
    )


def _parse_optional_int(value: Any, *, field: str, min_value: int, max_value: int) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _SnapshotError(
            "invalid_request",
            f"Field '{field}' must be an integer.",
            http_status=400,
            details={"field": field},
        )
    if isinstance(value, int):
        v = value
    elif isinstance(value, str):
        if value.strip() == "":
            return None
        try:
            v = int(value)
        except ValueError as e:
            raise _SnapshotError(
                "invalid_request",
                f"Field '{field}' must be an integer.",
                http_status=400,
                details={"field": field},
            ) from e
    else:
        raise _SnapshotError(
            "invalid_request",
            f"Field '{field}' must be an integer.",
            http_status=400,
            details={"field": field},
        )

    if v < min_value or v > max_value:
        raise _SnapshotError(
            "invalid_request",
            f"Field '{field}' must be between {min_value} and {max_value}.",
            http_status=400,
            details={"field": field, "min": min_value, "max": max_value},
        )
    return v


async def _parse_request(request: web.Request) -> _ParsedRequest:
    body: Mapping[str, Any] = {}
    if request.method in {"POST", "PUT", "PATCH"} and request.can_read_body:
        content_type = (request.content_type or "").lower()
        if "json" in content_type:
            try:
                parsed = await request.json()
            except json.JSONDecodeError as e:
                raise _SnapshotError("invalid_json", "Request body must be valid JSON.", http_status=400) from e
            if parsed is None:
                body = {}
            elif isinstance(parsed, Mapping):
                body = cast(Mapping[str, Any], parsed)
            else:
                raise _SnapshotError("invalid_request", "JSON body must be an object.", http_status=400)

    def _pick(name: str, *aliases: str) -> Any:
        for k in (name, *aliases):
            if k in request.query:
                return request.query.get(k)
        for k in (name, *aliases):
            if k in body:
                return body.get(k)
        return None

    reset = _parse_bool(_pick("reset"), default=False)
    window_seconds = _parse_optional_int(
        _pick("window_seconds", "windowSeconds"),
        field="window_seconds",
        min_value=1,
        max_value=86_400,
    )
    return _ParsedRequest(reset=reset, window_seconds=window_seconds)


def _extract_config(app: web.Application) -> Mapping[str, Any]:
    # Prefer an AppKey'd config if present, else string keys.
    candidate = app.get(CONFIG_APP_KEY) or app.get("config") or app.get("settings") or app.get("cfg")
    if isinstance(candidate, Mapping):
        return candidate
    return {}


def get_inprocess_snapshotter() -> Optional[Callable[..., Any]]:
    return _LAST_INPROCESS_SNAPSHOTTER


def _resolve_metrics_url(app: web.Application) -> Optional[str]:
    cfg = _extract_config(app)

    # 1) Explicit endpoint URL.
    for key in ("gateway_metrics_url", "gatewayMetricsUrl", "gateway_metrics_endpoint", "gatewayMetricsEndpoint"):
        value = cfg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    # 2) Environment variable override.
    env_url = os.getenv("THOMAS_GATEWAY_METRICS_URL") or os.getenv("GATEWAY_METRICS_URL")
    if env_url and env_url.strip():
        return env_url.strip()

    # 3) Base URL + path.
    base_url = (
        cfg.get("gateway_url")
        or cfg.get("gateway_base_url")
        or cfg.get("gatewayBaseUrl")
        or os.getenv("THOMAS_GATEWAY_URL")
        or os.getenv("GATEWAY_URL")
    )
    if isinstance(base_url, str) and base_url.strip():
        path = cfg.get("gateway_metrics_snapshot_path") or cfg.get("gatewayMetricsSnapshotPath") or "/metrics/snapshot"
        if not isinstance(path, str) or not path.strip():
            path = "/metrics/snapshot"
        return base_url.rstrip("/") + "/" + path.lstrip("/")

    return None


async def _maybe_await(value: Any) -> Any:
    if isinstance(value, Awaitable) or getattr(value, "__await__", None) is not None:
        return await cast(Awaitable[Any], value)
    return value


async def _snapshot_from_app(request: web.Request, parsed: _ParsedRequest) -> Optional[tuple[Mapping[str, Any], str]]:
    """
    Try to read metrics from in-process hooks.
    """
    snapshotter = request.app.get(SNAPSHOTTER_APP_KEY) or request.app.get("gateway_metrics_snapshotter")
    if callable(snapshotter):
        result = snapshotter(reset=parsed.reset, window_seconds=parsed.window_seconds)  # type: ignore[misc]
        result = await _maybe_await(result)
        if not isinstance(result, Mapping):
            raise _SnapshotError(
                "invalid_metrics_provider",
                "gateway_metrics_snapshotter returned a non-object snapshot.",
                http_status=500,
                details={"provider": "gateway_metrics_snapshotter"},
            )
        return (cast(Mapping[str, Any], result), "app.gateway_metrics_snapshotter")

    gateway_client = request.app.get("gateway_client") or request.app.get("gateway") or request.app.get("gateway_api")
    if gateway_client is not None:
        for method_name in ("metrics_snapshot", "get_metrics_snapshot", "snapshot_metrics"):
            method = getattr(gateway_client, method_name, None)
            if callable(method):
                result = method(reset=parsed.reset, window_seconds=parsed.window_seconds)  # type: ignore[misc]
                result = await _maybe_await(result)
                if isinstance(result, Mapping):
                    return (cast(Mapping[str, Any], result), f"app.{type(gateway_client).__name__}.{method_name}")

    metrics_obj = request.app.get("gateway_metrics") or request.app.get("metrics") or request.app.get("metrics_registry")
    if metrics_obj is not None:
        for method_name in ("snapshot", "to_dict", "as_dict"):
            method = getattr(metrics_obj, method_name, None)
            if callable(method):
                result = method()  # type: ignore[misc]
                result = await _maybe_await(result)
                if isinstance(result, Mapping):
                    return (cast(Mapping[str, Any], result), f"app.{type(metrics_obj).__name__}.{method_name}")

    return None


async def _fetch_external_snapshot(request: web.Request, parsed: _ParsedRequest, *, url: str) -> Mapping[str, Any]:
    cfg = _extract_config(request.app)

    timeout_seconds = 10
    t = cfg.get("gateway_metrics_timeout_seconds") or cfg.get("gatewayMetricsTimeoutSeconds")
    if isinstance(t, int) and t > 0:
        timeout_seconds = t

    session = (
        request.app.get("http_session")
        or request.app.get("client_session")
        or request.app.get("aiohttp_session")
    )
    close_session = False
    if not isinstance(session, ClientSession) or session.closed:
        session = ClientSession(timeout=ClientTimeout(total=timeout_seconds))
        close_session = True

    params: MutableMapping[str, str] = {}
    if parsed.reset:
        params["reset"] = "true"
    if parsed.window_seconds is not None:
        params["window_seconds"] = str(parsed.window_seconds)

    try:
        async with session.get(url, params=params) as resp:
            if resp.status != 200:
                raise _SnapshotError(
                    "gateway_upstream_error",
                    f"Gateway metrics endpoint returned HTTP {resp.status}.",
                    http_status=502,
                    details={"upstream_status": resp.status},
                )
            # Prefer JSON, tolerate non-JSON by returning {"raw": "..."}.
            try:
                data = await resp.json()
            except Exception:
                raw = await resp.text()
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {"raw": raw}

            if isinstance(data, Mapping):
                return cast(Mapping[str, Any], data)
            return {"value": data}
    except _SnapshotError:
        raise
    except (ClientError, asyncio.TimeoutError, TimeoutError, OSError) as e:
        raise _SnapshotError(
            "gateway_unreachable",
            "Unable to reach the configured gateway metrics endpoint.",
            http_status=502,
        ) from e
    finally:
        if close_session:
            await session.close()


async def _get_snapshot(request: web.Request, parsed: _ParsedRequest) -> tuple[Mapping[str, Any], str]:
    in_process = await _snapshot_from_app(request, parsed)
    if in_process is not None:
        return in_process

    url = _resolve_metrics_url(request.app)
    if not url:
        raise _SnapshotError(
            "missing_config",
            "No gateway metrics source is configured.",
            http_status=500,
            details={
                "hint": "Set app['config']['gateway_metrics_url'] (or THOMAS_GATEWAY_METRICS_URL) to a reachable endpoint."
            },
        )

    data = await _fetch_external_snapshot(request, parsed, url=url)
    return (data, f"external:{url}")


@routes.get("/v1/gateway/metrics/snapshot")
@routes.post("/v1/gateway/metrics/snapshot")
@routes.get("/gateway/metrics/snapshot")
@routes.post("/gateway/metrics/snapshot")
async def gateway_metrics_snapshot(request: web.Request) -> web.Response:
    """
    Gateway metrics snapshot endpoint.
      - GET with query params: reset, window_seconds
      - POST with JSON body: {"reset": bool, "window_seconds": int}
    """
    try:
        parsed = await _parse_request(request)
        snapshot, source = await _get_snapshot(request, parsed)

        req_payload: GatewayMetricsSnapshotRequest = {"reset": parsed.reset}
        if parsed.window_seconds is not None:
            req_payload["window_seconds"] = parsed.window_seconds

        payload: GatewayMetricsSnapshotSuccess = {
            "ok": True,
            "taken_at": _utcnow_iso(),
            "source": source,
            "request": req_payload,
            "snapshot": snapshot,
        }
        return _json_response(payload, status=200)
    except _SnapshotError as e:
        payload: GatewayMetricsSnapshotFailure = {
            "ok": False,
            "error": {"code": e.code, "message": e.message, "details": e.details},
        }
        return _json_response(payload, status=e.http_status)
    except Exception:
        payload: GatewayMetricsSnapshotFailure = {
            "ok": False,
            "error": {"code": "internal_error", "message": "Internal server error."},
        }
        return _json_response(payload, status=500)


def register(app: web.Application) -> None:
    """
    Optional explicit registration hook used by some route loaders.
    Safe to call multiple times for the same app instance.
    """
    seen = app.get(_ROUTE_TABLE_IDS_ADDED_KEY)
    if not isinstance(seen, set):
        seen = set()
        app[_ROUTE_TABLE_IDS_ADDED_KEY] = seen
    table_id = id(routes)
    if table_id in seen:
        return
    app.add_routes(routes)
    seen.add(table_id)
    global _LAST_INPROCESS_SNAPSHOTTER
    snapshotter = app.get(SNAPSHOTTER_APP_KEY) or app.get("gateway_metrics_snapshotter")
    _LAST_INPROCESS_SNAPSHOTTER = snapshotter if callable(snapshotter) else None
