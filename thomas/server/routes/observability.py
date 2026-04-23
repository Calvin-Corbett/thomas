"""Observability dashboard endpoints for real-time system monitoring.

Provides:
  GET /api/events - Recent events with optional filtering
  GET /api/metrics - Current system metrics
  GET /api/agents/activity - Active agent summary
  GET /api/task-bots/executions - Canonical task-bot runtime summary
  GET /api/tools/usage - Tool usage statistics
  WS /ws/events - WebSocket event streaming
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import web

from thomas.core import agent_presence, task_bot_runtime

log = logging.getLogger(__name__)

_EVENT_STORE: deque = deque(maxlen=500)
_METRICS_STORE: dict[str, Any] = {
    "active_agents": 0,
    "tasks_queued": 0,
    "memory_usage": 0.0,
    "uptime_seconds": 0,
    "request_rate": 0,
    "error_rate": 0.0,
    "llm_tokens": {"input": 0, "output": 0},
    "tools_called": 0,
}
_BOOT_TIME: float = time.time()
_REQUEST_COUNTS: deque = deque(maxlen=30)
_ERROR_COUNTS: deque = deque(maxlen=30)
_WEBSOCKET_CLIENTS: set = set()


def _get_uptime_seconds() -> int:
    return int(time.time() - _BOOT_TIME)


def record_event(
    event_type: str,
    source_agent: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "source_agent": source_agent,
        "message": message,
        "details": details or {},
    }
    _EVENT_STORE.append(event)
    asyncio.create_task(_broadcast_to_websockets(event))


async def _broadcast_to_websockets(event: dict[str, Any]) -> None:
    disconnected = []
    for ws in _WEBSOCKET_CLIENTS:
        try:
            if not ws.is_closed():
                await ws.send_json({"type": "event", "data": event})
            else:
                disconnected.append(ws)
        except Exception as exc:
            log.debug("Error broadcasting to WebSocket: %s", exc)
            disconnected.append(ws)
    for ws in disconnected:
        _WEBSOCKET_CLIENTS.discard(ws)


def update_metrics(updates: dict[str, Any]) -> None:
    _METRICS_STORE.update(updates)


def _parse_query_int(
    request: web.Request,
    name: str,
    *,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    raw = request.query.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text=f"invalid {name}") from exc
    if value < min_value or value > max_value:
        raise web.HTTPBadRequest(text=f"invalid {name}")
    return value


async def api_events(request: web.Request) -> web.Response:
    event_type_filter = request.query.get("type", "")
    limit = _parse_query_int(request, "limit", default=100, min_value=1, max_value=500)
    minutes = _parse_query_int(request, "minutes", default=60, min_value=1, max_value=24 * 60)
    filter_types = {t.strip() for t in event_type_filter.split(",") if t.strip()}
    cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    events = []
    for event in _EVENT_STORE:
        if event["timestamp"] < cutoff_time:
            continue
        if filter_types and event["type"] not in filter_types:
            continue
        events.append(event)

    return web.json_response(
        {
            "success": True,
            "events": list(events)[-limit:],
            "count": len(events),
            "total_available": len(_EVENT_STORE),
        }
    )


async def api_metrics(request: web.Request) -> web.Response:
    uptime = _get_uptime_seconds()
    request_rate = len(_REQUEST_COUNTS) * 2 / 60 if _REQUEST_COUNTS else 0
    total_errors = sum(_ERROR_COUNTS)
    total_requests = sum(_REQUEST_COUNTS)
    error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0
    task_bot_summary = task_bot_runtime.read_summary(refresh=True)

    response_data = {
        **_METRICS_STORE,
        "uptime_seconds": uptime,
        "request_rate": round(request_rate, 2),
        "error_rate": round(error_rate, 2),
        "task_bot_active": int(task_bot_summary.get("active_count", 0) or 0),
        "task_bot_stale": int(task_bot_summary.get("stale_count", 0) or 0),
        "task_bot_awaiting_proof": int(task_bot_summary.get("awaiting_proof_count", 0) or 0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return web.json_response({"success": True, "metrics": response_data})


async def api_agents_activity(request: web.Request) -> web.Response:
    try:
        payload = agent_presence.collect_presence()
    except Exception as exc:
        return web.json_response({"success": False, "error": f"{type(exc).__name__}: {exc}"}, status=500)
    return web.json_response(payload)


async def api_task_bot_executions(request: web.Request) -> web.Response:
    try:
        summary = task_bot_runtime.read_summary(refresh=True)
    except Exception as exc:
        return web.json_response({"success": False, "error": f"{type(exc).__name__}: {exc}"}, status=500)
    return web.json_response({"success": True, "task_bots": summary})


async def api_tools_usage(request: web.Request) -> web.Response:
    usage_stats = {
        "by_tool": {},
        "success_rate": 0.0,
        "total_calls": 0,
        "recent_calls": [],
    }
    return web.json_response({"success": True, "usage": usage_stats})


async def ws_events(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _WEBSOCKET_CLIENTS.add(ws)
    log.info("WebSocket client connected. Total: %s", len(_WEBSOCKET_CLIENTS))

    try:
        await ws.send_json(
            {
                "type": "connected",
                "message": "Connected to observability stream",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    log.warning("Invalid JSON from WebSocket client: %s", msg.data)
            elif msg.type == web.WSMsgType.ERROR:
                log.error("WebSocket error: %s", ws.exception())
                break
    except Exception as exc:
        log.error("WebSocket handler error: %s", exc)
    finally:
        _WEBSOCKET_CLIENTS.discard(ws)
        log.info("WebSocket client disconnected. Total: %s", len(_WEBSOCKET_CLIENTS))

    return ws


def register_observability_routes(app: web.Application) -> None:
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/api/metrics", api_metrics)
    app.router.add_get("/api/agents/activity", api_agents_activity)
    app.router.add_get("/api/task-bots/executions", api_task_bot_executions)
    app.router.add_get("/api/tools/usage", api_tools_usage)
    app.router.add_get("/ws/events", ws_events)
    log.info("Observability routes registered")


__all__ = [
    "record_event",
    "update_metrics",
    "register_observability_routes",
    "api_events",
    "api_metrics",
    "api_agents_activity",
    "api_task_bot_executions",
    "api_tools_usage",
    "ws_events",
]
