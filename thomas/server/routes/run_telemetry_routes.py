"""aiohttp routes exposing live run telemetry + completion projection (CAP-137).

These routes are the HTTP surface over
:class:`thomas.observability.run_projection.RunProjection`. They exist so the
always-visible live-run readout in the web UI has something real to poll:

  GET  /api/run-telemetry            -- alias of /snapshot
  GET  /api/run-telemetry/snapshot   -- current turns/tokens/rate/projection
  POST /api/run-telemetry/events     -- ingest one run event (drives the surface)
  POST /api/run-telemetry/target     -- set the completion target
  POST /api/run-telemetry/reset      -- clear the aggregate back to empty

The projection state is process-wide: a module-level singleton reached through
:func:`get_run_projection` so every request observes the same live run. Tests
swap it out with :func:`reset_run_projection`, which also accepts an injected
clock for determinism.

Two invariants this layer is responsible for:

* **User error is never a 500.** Every malformed body, unknown event kind, or
  out-of-range number becomes a 4xx with a readable message.
* **The JSON never contains ``NaN`` or ``Infinity``.** ``json.dumps`` happily
  emits those bare tokens, which are not valid JSON and would blow up the
  browser's ``JSON.parse``. Every float leaving here is passed through
  :func:`_finite_or_none`, so an unknowable rate or ETA is serialized as
  ``null`` -- which the UI renders as an explicit "unknown".
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import math
from typing import Any

from aiohttp import web

from thomas.observability.run_projection import (
    EventKind,
    RunProjection,
    RunSnapshot,
    RunTarget,
)

_log = logging.getLogger(__name__)

RUN_TELEMETRY_CONFIG_KEY = web.AppKey("run_telemetry_config", object)

_DEFAULT_WINDOW_SECONDS = 60.0
_MIN_WINDOW_SECONDS = 1.0
_MAX_WINDOW_SECONDS = 86_400.0
_MAX_TOKENS_PER_EVENT = 10_000_000
_MAX_TARGET = 1_000_000_000

_EVENT_KINDS: dict[str, EventKind] = {kind.value: kind for kind in EventKind}

# Float fields of RunSnapshot.as_dict() that must be finite-or-null on the wire.
_FLOAT_FIELDS = (
    "now",
    "window_seconds",
    "tokens_per_min",
    "turns_per_min",
    "eta_seconds_turns",
    "eta_seconds_tokens",
    "eta_seconds",
)

# Exceptions a malformed/aborted request body can raise. Deliberately a wide
# *specific* tuple rather than a bare `except Exception`.
_BODY_ERRORS = (ValueError, TypeError, UnicodeDecodeError, LookupError, OSError)

_PROJECTION: RunProjection | None = None


# ────────────────────────────── singleton state ──────────────────────────────


def get_run_projection() -> RunProjection:
    """Return the process-wide live-run projection, creating it on first use."""
    global _PROJECTION
    if _PROJECTION is None:
        _PROJECTION = RunProjection(window_seconds=_DEFAULT_WINDOW_SECONDS)
    return _PROJECTION


def set_run_projection(projection: RunProjection) -> None:
    """Install *projection* as the process-wide instance (wiring/tests)."""
    global _PROJECTION
    _PROJECTION = projection


def reset_run_projection(
    *,
    window_seconds: float = _DEFAULT_WINDOW_SECONDS,
    clock: Any | None = None,
    target: RunTarget | None = None,
) -> RunProjection:
    """Replace the singleton with a fresh projection and return it."""
    kwargs: dict[str, Any] = {"window_seconds": float(window_seconds)}
    if clock is not None:
        kwargs["clock"] = clock
    if target is not None:
        kwargs["target"] = target
    projection = RunProjection(**kwargs)
    set_run_projection(projection)
    return projection


# ────────────────────────────── registration ──────────────────────────────


def register_run_telemetry_routes(app: web.Application, config: Any) -> None:
    """Register the /api/run-telemetry/* routes on *app*."""
    app[RUN_TELEMETRY_CONFIG_KEY] = config

    window_seconds = _resolve_window_seconds(config)
    current = get_run_projection()
    if current.window_seconds != window_seconds:
        reset_run_projection(window_seconds=window_seconds, clock=current.clock, target=current.target)

    app.router.add_get("/api/run-telemetry", handle_snapshot)
    app.router.add_get("/api/run-telemetry/snapshot", handle_snapshot)
    app.router.add_post("/api/run-telemetry/events", handle_ingest_event)
    app.router.add_post("/api/run-telemetry/target", handle_set_target)
    app.router.add_post("/api/run-telemetry/reset", handle_reset)


def _resolve_window_seconds(config: Any) -> float:
    """Read the rolling-rate window from config, falling back to the default."""
    raw = _deep_get(config, ["observability", "run_telemetry_window_seconds"])
    if raw is None:
        return _DEFAULT_WINDOW_SECONDS
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        _log.warning("run_telemetry: ignoring non-numeric window config %r", raw)
        return _DEFAULT_WINDOW_SECONDS
    value = float(raw)
    if not math.isfinite(value):
        return _DEFAULT_WINDOW_SECONDS
    return min(max(value, _MIN_WINDOW_SECONDS), _MAX_WINDOW_SECONDS)


# ────────────────────────────── handlers ──────────────────────────────


async def handle_snapshot(request: web.Request) -> web.Response:
    """GET the current live telemetry snapshot."""
    _require_run_telemetry_access(request)
    projection = get_run_projection()
    return _snapshot_response(projection.snapshot())


async def handle_ingest_event(request: web.Request) -> web.Response:
    """POST one run event into the live aggregate and return the new snapshot."""
    _require_run_telemetry_access(request)
    body = await _read_json_object(request)
    projection = get_run_projection()

    kind = _parse_kind(body.get("kind"))
    timestamp = _parse_timestamp(body.get("timestamp"), projection)

    if kind is EventKind.TOKENS:
        tokens = _parse_tokens(body.get("tokens"))
        projection.record_tokens(tokens, timestamp)
    elif kind is EventKind.TURN_STARTED:
        projection.turn_started(timestamp)
    else:
        projection.turn_finished(timestamp)

    return _snapshot_response(projection.snapshot(), status=201)


async def handle_set_target(request: web.Request) -> web.Response:
    """POST the completion target the projection estimates toward."""
    _require_run_telemetry_access(request)
    body = await _read_json_object(request)
    if "turns" not in body and "tokens" not in body:
        raise web.HTTPBadRequest(text="target requires at least one of: turns, tokens")

    target = RunTarget(
        turns=_parse_target_value(body.get("turns"), "turns"),
        tokens=_parse_target_value(body.get("tokens"), "tokens"),
    )
    projection = get_run_projection()
    projection.set_target(target)
    return _snapshot_response(projection.snapshot())


async def handle_reset(request: web.Request) -> web.Response:
    """POST to clear the live aggregate back to an empty run."""
    _require_run_telemetry_access(request)
    current = get_run_projection()
    projection = reset_run_projection(
        window_seconds=current.window_seconds,
        clock=current.clock,
        target=current.target,
    )
    return _snapshot_response(projection.snapshot())


# ────────────────────────────── serialization ──────────────────────────────


def _snapshot_response(snapshot: RunSnapshot, *, status: int = 200) -> web.Response:
    return web.json_response({"ok": True, "snapshot": snapshot_to_json(snapshot)}, status=status)


def snapshot_to_json(snapshot: RunSnapshot) -> dict[str, Any]:
    """JSON-safe snapshot mapping: every float is finite or ``null``."""
    payload = dict(snapshot.as_dict())
    for field in _FLOAT_FIELDS:
        payload[field] = _finite_or_none(payload.get(field))
    payload["projection_known"] = bool(payload.get("projection_known"))
    payload["rate_known"] = payload["tokens_per_min"] is not None or payload["turns_per_min"] is not None
    payload["eta_known"] = payload["projection_known"] and payload["eta_seconds"] is not None
    return payload


def _finite_or_none(value: Any) -> float | None:
    """Coerce to a finite float, or ``None``. Never emits NaN/Infinity."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


# ────────────────────────────── input validation ──────────────────────────────


async def _read_json_object(request: web.Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except _BODY_ERRORS as exc:
        _log.debug("run_telemetry: invalid json body: %s", type(exc).__name__)
        raise web.HTTPBadRequest(text="invalid json body") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="json body must be an object")
    return payload


def _parse_kind(raw: Any) -> EventKind:
    if raw is None:
        raise web.HTTPBadRequest(text=f"kind is required; expected one of: {_kind_list()}")
    if not isinstance(raw, str):
        raise web.HTTPBadRequest(text=f"kind must be a string; expected one of: {_kind_list()}")
    kind = _EVENT_KINDS.get(raw.strip().lower())
    if kind is None:
        raise web.HTTPBadRequest(text=f"unknown kind {raw!r}; expected one of: {_kind_list()}")
    return kind


def _kind_list() -> str:
    return ", ".join(sorted(_EVENT_KINDS))


def _parse_timestamp(raw: Any, projection: RunProjection) -> float:
    """Event timestamp in seconds; defaults to the projection's own clock."""
    if raw is None:
        return float(projection.clock())
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise web.HTTPBadRequest(text="timestamp must be a number of seconds")
    value = float(raw)
    if not math.isfinite(value):
        raise web.HTTPBadRequest(text="timestamp must be a finite number")
    return value


def _parse_tokens(raw: Any) -> int:
    if raw is None:
        raise web.HTTPBadRequest(text="tokens is required for kind=tokens")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise web.HTTPBadRequest(text="tokens must be an integer")
    value = float(raw)
    if not math.isfinite(value) or value != int(value):
        raise web.HTTPBadRequest(text="tokens must be a whole number")
    tokens = int(value)
    if tokens < 0:
        raise web.HTTPBadRequest(text="tokens must not be negative")
    if tokens > _MAX_TOKENS_PER_EVENT:
        raise web.HTTPBadRequest(text=f"tokens must be <= {_MAX_TOKENS_PER_EVENT}")
    return tokens


def _parse_target_value(raw: Any, field: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise web.HTTPBadRequest(text=f"target {field} must be an integer or null")
    value = float(raw)
    if not math.isfinite(value) or value != int(value):
        raise web.HTTPBadRequest(text=f"target {field} must be a whole number")
    target = int(value)
    if target < 0:
        raise web.HTTPBadRequest(text=f"target {field} must not be negative")
    if target > _MAX_TARGET:
        raise web.HTTPBadRequest(text=f"target {field} must be <= {_MAX_TARGET}")
    return target


# ────────────────────────────── access control ──────────────────────────────


def _require_run_telemetry_access(request: web.Request) -> None:
    """Loopback-only locally; bearer-token gated in remote access mode."""
    cfg = request.app.get(RUN_TELEMETRY_CONFIG_KEY)
    server_cfg = getattr(cfg, "server", None)
    mode = str(getattr(server_cfg, "access_mode", "local") or "local").strip().lower()
    if mode == "remote":
        expected = str(getattr(server_cfg, "api_token", "") or "").strip()
        if not expected:
            raise web.HTTPUnauthorized(text="server api token is not configured")
        incoming = _extract_request_token(request)
        if not incoming:
            raise web.HTTPUnauthorized(text="missing api token")
        if not hmac.compare_digest(incoming.encode("utf-8"), expected.encode("utf-8")):
            raise web.HTTPUnauthorized(text="invalid api token")
        return
    if not _is_loopback_request(request):
        raise web.HTTPForbidden(text="This endpoint is only available from localhost.")


def _extract_request_token(request: web.Request) -> str:
    auth = str(request.headers.get("Authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(request.headers.get("X-Api-Token") or "").strip()


def _is_loopback_host(host: str) -> bool:
    value = str(host or "").strip().lower()
    if not value:
        return False
    if value in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return bool(ipaddress.ip_address(value).is_loopback)
    except ValueError:
        return False


def _is_loopback_request(request: web.Request) -> bool:
    peer: Any = None
    transport = request.transport
    if transport is not None:
        peer = transport.get_extra_info("peername")
    if isinstance(peer, (tuple, list)) and peer:
        return _is_loopback_host(str(peer[0]))
    return _is_loopback_host(str(request.remote or ""))


def _deep_get(obj: Any, keys: list[str], default: Any = None) -> Any:
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        else:
            cur = getattr(cur, key, default)
    return cur
