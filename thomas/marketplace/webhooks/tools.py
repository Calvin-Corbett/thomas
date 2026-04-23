"""Tools for webhooks module - webhook handling and delivery."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class WebhooksRegisterTool(Tool):
    """Register a webhook."""

    name = "webhooks_register"
    category = "webhooks"
    description = "Register a webhook to receive events."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Webhook URL endpoint",
            },
            "events": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Event types to subscribe to",
            },
            "secret": {
                "type": "string",
                "description": "Webhook secret for verification (optional)",
            },
        },
        "required": ["url", "events"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .registry import register_webhook

            webhook_id = register_webhook(
                url=args["url"],
                events=args["events"],
                secret=args.get("secret"),
            )
            return ToolResult(ok=True, data={"webhook_id": webhook_id, "registered": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WebhooksUnregisterTool(Tool):
    """Unregister a webhook."""

    name = "webhooks_unregister"
    category = "webhooks"
    description = "Remove a registered webhook."
    parameters = {
        "type": "object",
        "properties": {
            "webhook_id": {
                "type": "string",
                "description": "Webhook ID to remove",
            },
        },
        "required": ["webhook_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .registry import unregister_webhook

            unregister_webhook(args["webhook_id"])
            return ToolResult(ok=True, data={"unregistered": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WebhooksListTool(Tool):
    """List registered webhooks."""

    name = "webhooks_list"
    category = "webhooks"
    description = "List all registered webhooks."
    parameters = {
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "description": "Filter by event type (optional)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .registry import list_webhooks

            webhooks = list_webhooks(event_type=args.get("event_type"))
            return ToolResult(ok=True, data={"webhooks": webhooks or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WebhooksTriggerTool(Tool):
    """Manually trigger a webhook."""

    name = "webhooks_trigger"
    category = "webhooks"
    description = "Manually deliver a webhook event."
    parameters = {
        "type": "object",
        "properties": {
            "webhook_id": {
                "type": "string",
                "description": "Webhook ID",
            },
            "event_type": {
                "type": "string",
                "description": "Event type",
            },
            "payload": {
                "type": "object",
                "description": "Event payload",
            },
        },
        "required": ["webhook_id", "event_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .dispatcher import trigger_webhook

            result = trigger_webhook(
                webhook_id=args["webhook_id"],
                event_type=args["event_type"],
                payload=args.get("payload", {}),
            )
            return ToolResult(ok=True, data=result or {"triggered": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WebhooksGetDeliveryHistoryTool(Tool):
    """Get webhook delivery history."""

    name = "webhooks_get_delivery_history"
    category = "webhooks"
    description = "Get delivery history for a webhook."
    parameters = {
        "type": "object",
        "properties": {
            "webhook_id": {
                "type": "string",
                "description": "Webhook ID",
            },
            "limit": {
                "type": "integer",
                "description": "Max history entries (default: 50)",
            },
        },
        "required": ["webhook_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .history import get_delivery_history

            history = get_delivery_history(
                webhook_id=args["webhook_id"],
                limit=args.get("limit", 50),
            )
            return ToolResult(ok=True, data={"history": history or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_webhooks_tools(registry):
    """Register webhooks tools with the tool registry."""
    tools = [
        WebhooksRegisterTool(),
        WebhooksUnregisterTool(),
        WebhooksListTool(),
        WebhooksTriggerTool(),
        WebhooksGetDeliveryHistoryTool(),
    ]
    for tool in tools:
        registry.register(tool)
