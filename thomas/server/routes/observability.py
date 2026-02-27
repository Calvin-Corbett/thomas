"""Observability dashboard endpoints for real-time system monitoring.

Provides:
  GET /api/events - Recent events with optional filtering
  GET /api/metrics - Current system metrics
  GET /api/agents/activity - Active agent summary
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

log = logging.getLogger(__name__)

# In-memory event storage
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
_REQUEST_COUNTS: deque = deque(maxlen=30)  # 2s intervals -> 60s window
_ERROR_COUNTS: deque = deque(maxlen=30)
_WEBSOCKET_CLIENTS: set = set()


def _get_uptime_seconds() -> int:
    """Get server uptime in seconds."""
    return int(time.time() - _BOOT_TIME)


def record_event(
    event_type: str,
    source_agent: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an event to the in-memory store."""
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "source_agent": source_agent,
        "message": message,
        "details": details or {},
    }
    _EVENT_STORE.append(event)

    # Notify WebSocket clients
    asyncio.create_task(_broadcast_to_websockets(event))


async def _broadcast_to_websockets(event: dict[str, Any]) -> None:
    """Broadcast event to all connected WebSocket clients."""
    disconnected = []
    for ws in _WEBSOCKET_CLIENTS:
        try:
            if not ws.is_closed():
                await ws.send_json({"type": "event", "data": event})
            else:
                disconnected.append(ws)
        except Exception as e:
            log.debug(f"Error broadcasting to WebSocket: {e}")
            disconnected.append(ws)

    # Clean up disconnected clients
    for ws in disconnected:
        _WEBSOCKET_CLIENTS.discard(ws)


def update_metrics(updates: dict[str, Any]) -> None:
    """Update system metrics."""
    _METRICS_STORE.update(updates)


async def api_events(request: web.Request) -> web.Response:
    """GET /api/events - Return recent events with optional filtering.

    Query params:
      - type: Filter by event type (comma-separated: tools, llm, agent, error, system)
      - limit: Max events to return (default: 100, max: 500)
      - minutes: Only events from last N minutes (default: 60)
    """
    app: web.Application = request.app

    # Get query parameters
    event_type_filter = request.query.get("type", "")
    limit = min(int(request.query.get("limit", 100)), 500)
    minutes = int(request.query.get("minutes", 60))

    # Parse filter types
    filter_types = set(t.strip() for t in event_type_filter.split(",") if t.strip())

    # Calculate cutoff time
    cutoff_time = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    # Filter events
    events = []
    for event in _EVENT_STORE:
        if event["timestamp"] < cutoff_time:
            continue
        if filter_types and event["type"] not in filter_types:
            continue
        events.append(event)

    # Return most recent events, limited
    return web.json_response(
        {
            "success": True,
            "events": list(events)[-limit:],
            "count": len(events),
            "total_available": len(_EVENT_STORE),
        }
    )


async def api_metrics(request: web.Request) -> web.Response:
    """GET /api/metrics - Return current system metrics."""
    app: web.Application = request.app

    # Update uptime
    uptime = _get_uptime_seconds()

    # Calculate request rate (requests per second over last 60 seconds)
    request_rate = len(_REQUEST_COUNTS) * 2 / 60 if _REQUEST_COUNTS else 0

    # Calculate error rate
    total_errors = sum(_ERROR_COUNTS)
    total_requests = sum(_REQUEST_COUNTS)
    error_rate = (total_errors / total_requests * 100) if total_requests > 0 else 0

    response_data = {
        **_METRICS_STORE,
        "uptime_seconds": uptime,
        "request_rate": round(request_rate, 2),
        "error_rate": round(error_rate, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return web.json_response(
        {
            "success": True,
            "metrics": response_data,
        }
    )


async def api_agents_activity(request: web.Request) -> web.Response:
    """GET /api/agents/activity - Return active agent activity summary."""
    app: web.Application = request.app

    # This would typically fetch from the app's agent manager
    # For now, return a template structure
    agents_data = []

    return web.json_response(
        {
            "success": True,
            "agents": agents_data,
            "active_count": len(agents_data),
        }
    )


async def api_tools_usage(request: web.Request) -> web.Response:
    """GET /api/tools/usage - Return tool usage statistics."""
    app: web.Application = request.app

    # This would typically fetch from tool usage tracking
    # For now, return a template structure
    usage_stats = {
        "by_tool": {},
        "success_rate": 0.0,
        "total_calls": 0,
        "recent_calls": [],
    }

    return web.json_response(
        {
            "success": True,
            "usage": usage_stats,
        }
    )


async def ws_events(request: web.Request) -> web.WebSocketResponse:
    """WS /ws/events - WebSocket handler for real-time event streaming.

    Sends events as they occur in real-time. Client can optionally send
    filter requests to filter event types.
    """
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Add to connected clients
    _WEBSOCKET_CLIENTS.add(ws)
    log.info(f"WebSocket client connected. Total: {len(_WEBSOCKET_CLIENTS)}")

    try:
        # Send initial connection confirmation
        await ws.send_json(
            {
                "type": "connected",
                "message": "Connected to observability stream",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        # Handle incoming messages (e.g., filter changes)
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    log.warning(f"Invalid JSON from WebSocket client: {msg.data}")
            elif msg.type == web.WSMsgType.ERROR:
                log.error(f"WebSocket error: {ws.exception()}")
                break
    except Exception as e:
        log.error(f"WebSocket handler error: {e}")
    finally:
        # Remove from connected clients
        _WEBSOCKET_CLIENTS.discard(ws)
        log.info(f"WebSocket client disconnected. Total: {len(_WEBSOCKET_CLIENTS)}")

    return ws


def register_observability_routes(app: web.Application) -> None:
    """Register all observability routes."""
    app.router.add_get("/api/events", api_events)
    app.router.add_get("/api/metrics", api_metrics)
    app.router.add_get("/api/agents/activity", api_agents_activity)
    app.router.add_get("/api/tools/usage", api_tools_usage)
    app.router.add_get("/ws/events", ws_events)

    log.info("Observability routes registered")


# Export for direct use
__all__ = [
    "record_event",
    "update_metrics",
    "register_observability_routes",
    "api_events",
    "api_metrics",
    "api_agents_activity",
    "api_tools_usage",
    "ws_events",
]
