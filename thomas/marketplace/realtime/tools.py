"""Tools for realtime module - real-time updates and streaming."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class RealtimeSubscribeTool(Tool):
    """Subscribe to real-time updates."""

    name = "realtime_subscribe"
    category = "realtime"
    description = "Subscribe to real-time events and updates."
    parameters = {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel name to subscribe to",
            },
            "filter": {
                "type": "object",
                "description": "Optional event filter",
            },
        },
        "required": ["channel"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .subscriber import subscribe

            result = subscribe(
                channel=args["channel"],
                filter=args.get("filter"),
            )
            return ToolResult(ok=True, data=result or {"subscribed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RealtimePublishTool(Tool):
    """Publish a real-time event."""

    name = "realtime_publish"
    category = "realtime"
    description = "Publish an event to real-time subscribers."
    parameters = {
        "type": "object",
        "properties": {
            "channel": {
                "type": "string",
                "description": "Channel name",
            },
            "event_type": {
                "type": "string",
                "description": "Event type",
            },
            "data": {
                "type": "object",
                "description": "Event data",
            },
        },
        "required": ["channel", "event_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .publisher import publish

            result = publish(
                channel=args["channel"],
                event_type=args["event_type"],
                data=args.get("data", {}),
            )
            return ToolResult(ok=True, data=result or {"published": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RealtimeGetConnectionStatusTool(Tool):
    """Get WebSocket connection status."""

    name = "realtime_get_connection_status"
    category = "realtime"
    description = "Get real-time connection status."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .connection import get_status

            status = get_status()
            return ToolResult(ok=True, data=status or {"connected": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_realtime_tools(registry):
    """Register realtime tools with the tool registry."""
    tools = [
        RealtimeSubscribeTool(),
        RealtimePublishTool(),
        RealtimeGetConnectionStatusTool(),
    ]
    for tool in tools:
        registry.register(tool)
