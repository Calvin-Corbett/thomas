"""aiohttp routes for subagent/worktree progress visibility (CAP-139).

Exposes the :mod:`thomas.observability.worktree_progress` aggregation core over
HTTP so the browser panel (``web/js/worktree_progress_panel.js``) can render
**per-worktree status plus task-graph timing and cost**:

  GET  /api/worktree-progress/snapshot  -> the full deterministic snapshot
       (per-worktree statuses, per-node timings, critical path, cost rollup).
       Optional ``?now=<epoch_seconds>`` pins the clock so a running node's
       elapsed-so-far is reproducible.
  POST /api/worktree-progress/events    -> ingest one node lifecycle event
       (``node_started`` / ``node_finished`` / ``register_worktree``).
  POST /api/worktree-progress/reset     -> drop all ingested state.

State lives in a module-level :class:`ProgressAggregator` singleton so every
handler folds into the same view; tests inject their own via
:func:`set_progress_aggregator` (with a fixed clock) to stay hermetic.

Bad input is always a 4xx: malformed/unparseable payloads are ``400`` and
lifecycle conflicts reported by the core (starting a node twice, finishing a
node that never started, finishing before starting) are ``409``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

from thomas.observability.worktree_progress import ProgressAggregator

log = logging.getLogger(__name__)

WORKTREE_PROGRESS_CONFIG_KEY = web.AppKey("worktree_progress_config", object)

EVENT_NODE_STARTED = "node_started"
EVENT_NODE_FINISHED = "node_finished"
EVENT_REGISTER_WORKTREE = "register_worktree"
KNOWN_EVENTS = (EVENT_NODE_STARTED, EVENT_NODE_FINISHED, EVENT_REGISTER_WORKTREE)

_AGGREGATOR: ProgressAggregator | None = None


# -- module-level singleton -------------------------------------------------
def get_progress_aggregator() -> ProgressAggregator:
    """The shared aggregator every handler reads/writes (created on first use)."""

    global _AGGREGATOR
    if _AGGREGATOR is None:
        _AGGREGATOR = ProgressAggregator()
    return _AGGREGATOR


def set_progress_aggregator(aggregator: ProgressAggregator | None) -> None:
    """Install a specific aggregator (tests inject one with a fixed clock)."""

    global _AGGREGATOR
    _AGGREGATOR = aggregator


def reset_progress_aggregator() -> ProgressAggregator:
    """Replace the singleton with a fresh, empty aggregator and return it."""

    global _AGGREGATOR
    _AGGREGATOR = ProgressAggregator()
    return _AGGREGATOR


# -- error helpers ----------------------------------------------------------
def _json_error(exc_class: type[web.HTTPException], message: str, code: str) -> web.HTTPException:
    body = json.dumps({"ok": False, "error": message, "code": code})
    return exc_class(text=body, content_type="application/json")


def _bad_request(message: str, code: str = "bad_request") -> web.HTTPException:
    return _json_error(web.HTTPBadRequest, message, code)


def _conflict(message: str, code: str = "conflict") -> web.HTTPException:
    return _json_error(web.HTTPConflict, message, code)


# -- parsing helpers --------------------------------------------------------
async def _read_json_object(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        raise _bad_request("request body must be a json object", "missing_body")
    try:
        payload = await request.json()
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        log.debug("worktree-progress: invalid json body: %s", type(exc).__name__)
        raise _bad_request("request body must be valid json", "invalid_json") from exc
    if not isinstance(payload, dict):
        raise _bad_request("request body must be a json object", "invalid_body")
    return payload


def _require_str(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(f"{field} must be a non-empty string", "invalid_field")
    return value.strip()


def _optional_float(payload: dict[str, Any], field: str) -> float | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _bad_request(f"{field} must be a number", "invalid_field")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise _bad_request(f"{field} must be a number", "invalid_field") from exc


def _optional_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _bad_request(f"{field} must be an integer", "invalid_field")
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise _bad_request(f"{field} must be an integer", "invalid_field") from exc


def _optional_str_list(payload: dict[str, Any], field: str) -> tuple[str, ...]:
    value = payload.get(field)
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise _bad_request(f"{field} must be a list of node ids", "invalid_field")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _bad_request(f"{field} must contain non-empty node ids", "invalid_field")
        out.append(item.strip())
    return tuple(out)


def _query_now(request: web.Request) -> float | None:
    raw = request.query.get("now")
    if raw is None or str(raw).strip() == "":
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise _bad_request("now must be a number (epoch seconds)", "invalid_query") from exc


def _snapshot_payload(aggregator: ProgressAggregator, now: float | None) -> dict[str, Any]:
    snapshot = aggregator.snapshot(now=now)
    data = snapshot.to_dict()
    data["critical_path_nodes"] = list(snapshot.critical_path.nodes)
    return {"ok": True, "snapshot": data}


# -- handlers ---------------------------------------------------------------
async def handle_get_snapshot(request: web.Request) -> web.Response:
    """Return the full progress snapshot (status + timing + critical path + cost)."""

    now = _query_now(request)
    return web.json_response(_snapshot_payload(get_progress_aggregator(), now))


async def handle_post_event(request: web.Request) -> web.Response:
    """Ingest one node lifecycle event and return the refreshed snapshot."""

    payload = await _read_json_object(request)
    event = payload.get("event")
    if not isinstance(event, str) or event.strip() not in KNOWN_EVENTS:
        raise _bad_request(
            "event must be one of: " + ", ".join(KNOWN_EVENTS),
            "unknown_event",
        )
    event = event.strip()
    aggregator = get_progress_aggregator()

    if event == EVENT_REGISTER_WORKTREE:
        aggregator.register_worktree(_require_str(payload, "worktree_id"))
    elif event == EVENT_NODE_STARTED:
        worktree_id = _require_str(payload, "worktree_id")
        node_id = _require_str(payload, "node_id")
        depends_on = _optional_str_list(payload, "depends_on")
        at = _optional_float(payload, "at")
        try:
            aggregator.node_started(
                worktree_id=worktree_id,
                node_id=node_id,
                depends_on=depends_on,
                at=at,
            )
        except ValueError as exc:
            raise _conflict(str(exc), "node_conflict") from exc
    else:
        node_id = _require_str(payload, "node_id")
        at = _optional_float(payload, "at")
        try:
            aggregator.node_finished(
                node_id=node_id,
                at=at,
                tokens=_optional_int(payload, "tokens"),
                cost=_optional_float(payload, "cost") or 0.0,
            )
        except ValueError as exc:
            raise _conflict(str(exc), "node_conflict") from exc

    body = _snapshot_payload(aggregator, _query_now(request))
    body["event"] = event
    return web.json_response(body)


async def handle_post_reset(request: web.Request) -> web.Response:
    """Drop all ingested progress state and return the (empty) snapshot."""

    aggregator = reset_progress_aggregator()
    return web.json_response(_snapshot_payload(aggregator, _query_now(request)))


def register_worktree_progress_routes(app: web.Application, config: Any = None) -> None:
    """Register the CAP-139 worktree-progress endpoints on ``app``."""

    app[WORKTREE_PROGRESS_CONFIG_KEY] = config
    app.router.add_get("/api/worktree-progress/snapshot", handle_get_snapshot)
    app.router.add_post("/api/worktree-progress/events", handle_post_event)
    app.router.add_post("/api/worktree-progress/reset", handle_post_reset)
    log.info("Worktree progress routes registered")


__all__ = [
    "EVENT_NODE_FINISHED",
    "EVENT_NODE_STARTED",
    "EVENT_REGISTER_WORKTREE",
    "KNOWN_EVENTS",
    "WORKTREE_PROGRESS_CONFIG_KEY",
    "get_progress_aggregator",
    "handle_get_snapshot",
    "handle_post_event",
    "handle_post_reset",
    "register_worktree_progress_routes",
    "reset_progress_aggregator",
    "set_progress_aggregator",
]
