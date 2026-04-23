"""Tools for tray_agent module - system tray agent."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class TrayAgentGetStatusTool(Tool):
    """Get tray agent status."""

    name = "tray_agent_get_status"
    category = "tray_agent"
    description = "Get the status of the system tray agent."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .agent import get_status

            status = get_status()
            return ToolResult(ok=True, data=status or {"running": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TrayAgentShowNotificationTool(Tool):
    """Show a notification in the system tray."""

    name = "tray_agent_show_notification"
    category = "tray_agent"
    description = "Display a notification in the system tray."
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Notification title",
            },
            "message": {
                "type": "string",
                "description": "Notification message",
            },
            "icon": {
                "type": "string",
                "description": "Icon name or path",
            },
            "timeout_ms": {
                "type": "integer",
                "description": "Display timeout in milliseconds",
            },
        },
        "required": ["title", "message"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .agent import show_notification

            show_notification(
                title=args["title"],
                message=args["message"],
                icon=args.get("icon"),
                timeout_ms=args.get("timeout_ms", 5000),
            )
            return ToolResult(ok=True, data={"shown": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TrayAgentStartTool(Tool):
    """Start the tray agent."""

    name = "tray_agent_start"
    category = "tray_agent"
    description = "Start the system tray agent."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .agent import start

            start()
            return ToolResult(ok=True, data={"started": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TrayAgentStopTool(Tool):
    """Stop the tray agent."""

    name = "tray_agent_stop"
    category = "tray_agent"
    description = "Stop the system tray agent."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .agent import stop

            stop()
            return ToolResult(ok=True, data={"stopped": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_tray_agent_tools(registry):
    """Register tray_agent tools with the tool registry."""
    tools = [
        TrayAgentGetStatusTool(),
        TrayAgentShowNotificationTool(),
        TrayAgentStartTool(),
        TrayAgentStopTool(),
    ]
    for tool in tools:
        registry.register(tool)
