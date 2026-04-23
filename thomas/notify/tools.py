"""Tools for notify module - push notifications and alerting."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class NotifySendTool(Tool):
    """Send a notification."""

    name = "notify_send"
    category = "notify"
    description = "Send a notification to the user."
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
            "severity": {
                "type": "string",
                "description": "Severity (info, warning, error)",
            },
            "action_url": {
                "type": "string",
                "description": "Optional action URL",
            },
        },
        "required": ["title", "message"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .dispatcher import send_notification

            result = send_notification(
                title=args["title"],
                message=args["message"],
                severity=args.get("severity", "info"),
                action_url=args.get("action_url"),
            )
            return ToolResult(ok=True, data=result or {"sent": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotifySubscribeTool(Tool):
    """Subscribe to notifications."""

    name = "notify_subscribe"
    category = "notify"
    description = "Register for push notifications."
    parameters = {
        "type": "object",
        "properties": {
            "endpoint": {
                "type": "string",
                "description": "Push notification endpoint",
            },
            "auth": {
                "type": "string",
                "description": "Auth token",
            },
        },
        "required": ["endpoint"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .subscriber import subscribe

            result = subscribe(
                endpoint=args["endpoint"],
                auth=args.get("auth"),
            )
            return ToolResult(ok=True, data=result or {"subscribed": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotifyGetSubscriptionsTool(Tool):
    """Get active subscriptions."""

    name = "notify_get_subscriptions"
    category = "notify"
    description = "Get list of active notification subscriptions."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .subscriber import list_subscriptions

            subs = list_subscriptions()
            return ToolResult(ok=True, data={"subscriptions": subs or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_notify_tools(registry):
    """Register notify tools with the tool registry."""
    tools = [
        NotifySendTool(),
        NotifySubscribeTool(),
        NotifyGetSubscriptionsTool(),
    ]
    for tool in tools:
        registry.register(tool)
