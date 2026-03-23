"""Tools for event_bus module - event distribution and handling."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class EventBusPublishTool(Tool):
    """Publish an event to the bus."""

    name = "event_bus_publish"
    category = "event_bus"
    description = "Publish an event to subscribers."
    parameters = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Event type/name",
            },
            "data": {
                "type": "object",
                "description": "Event payload",
            },
            "priority": {
                "type": "integer",
                "description": "Priority (optional)",
            },
        },
        "required": ["event_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .bus import get_default_bus

            bus = get_default_bus()
            event_type = args["event_type"]
            data = args.get("data", {})
            priority = args.get("priority", 0)

            await bus.publish(event_type, data, priority=priority)
            return ToolResult(ok=True, data={"published": True, "event_type": event_type})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class EventBusSubscribeTool(Tool):
    """Subscribe to events (informational tool)."""

    name = "event_bus_subscribe"
    category = "event_bus"
    description = "Register interest in an event type (returns subscription info)."
    parameters = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Event type to subscribe to",
            },
        },
        "required": ["event_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            event_type = args["event_type"]
            return ToolResult(
                ok=True,
                data={
                    "subscribed": True,
                    "event_type": event_type,
                    "note": "Use event-based APIs to receive events",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class EventBusGetDispatcherInfoTool(Tool):
    """Get dispatcher information."""

    name = "event_bus_get_dispatcher_info"
    category = "event_bus"
    description = "Get information about the event dispatcher."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .dispatcher import EventDispatcher

            dispatcher = EventDispatcher()
            info = dispatcher.get_stats()
            return ToolResult(ok=True, data=info or {"status": "ready"})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_event_bus_tools(registry):
    """Register event_bus tools with the tool registry."""
    tools = [
        EventBusPublishTool(),
        EventBusSubscribeTool(),
        EventBusGetDispatcherInfoTool(),
    ]
    for tool in tools:
        registry.register(tool)
