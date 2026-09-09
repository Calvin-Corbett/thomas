"""Tools for notifications module - notification management and delivery."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class NotificationsGetStoreTool(Tool):
    """Get or create notification store."""

    name = "notifications_get_store"
    category = "notifications"
    description = "Get a notification store instance for managing notifications."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database (optional, defaults to in-memory)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationStore

            store_path = args.get("store_path")
            store = NotificationStore(store_path) if store_path else NotificationStore()

            return ToolResult(
                ok=True,
                data={
                    "store_path": str(store.db_path) if hasattr(store, "db_path") else "in-memory",
                    "initialized": True,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsCreateTool(Tool):
    """Create and store a notification."""

    name = "notifications_create"
    category = "notifications"
    description = "Create and store a new notification."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database",
            },
            "type": {
                "type": "string",
                "description": "Event type (e.g. task.complete, error.occurred)",
            },
            "title": {
                "type": "string",
                "description": "Short notification title",
            },
            "body": {
                "type": "string",
                "description": "Detailed notification body",
            },
            "severity": {
                "type": "string",
                "description": "Severity: info, warn, or error (default: info)",
            },
            "action_url": {
                "type": "string",
                "description": "Optional URL for action button",
            },
        },
        "required": ["store_path", "type", "title", "body"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationCreate, NotificationStore

            store = NotificationStore(args["store_path"])

            nc = NotificationCreate(
                type=args["type"],
                title=args["title"],
                body=args["body"],
                severity=args.get("severity", "info"),
                action_url=args.get("action_url"),
            )

            notification = store.create(nc)

            return ToolResult(
                ok=True,
                data={
                    "id": notification.id,
                    "type": notification.type,
                    "title": notification.title,
                    "created_at": notification.created_at,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsListTool(Tool):
    """List notifications with filtering."""

    name = "notifications_list"
    category = "notifications"
    description = "List notifications with optional filtering."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database",
            },
            "unread_only": {
                "type": "boolean",
                "description": "Filter to unread only (default: false)",
            },
            "severity": {
                "type": "string",
                "description": "Filter by severity: info, warn, error (optional)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default: 50)",
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset (default: 0)",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationStore

            store = NotificationStore(args["store_path"])

            notifications = store.list(
                unread_only=args.get("unread_only", False),
                severity=args.get("severity"),
                limit=args.get("limit", 50),
                offset=args.get("offset", 0),
            )

            return ToolResult(
                ok=True,
                data={
                    "total": len(notifications),
                    "notifications": [
                        {
                            "id": n.id,
                            "type": n.type,
                            "title": n.title,
                            "body": n.body,
                            "severity": n.severity,
                            "read": n.read,
                            "created_at": n.created_at,
                        }
                        for n in notifications
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsMarkReadTool(Tool):
    """Mark notifications as read."""

    name = "notifications_mark_read"
    category = "notifications"
    description = "Mark one or all notifications as read."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database",
            },
            "notification_id": {
                "type": "string",
                "description": "Notification ID (if None, marks all as read)",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationStore

            store = NotificationStore(args["store_path"])

            notif_id = args.get("notification_id")
            if notif_id:
                store.mark_read(notif_id)
            else:
                store.mark_all_read()

            return ToolResult(ok=True, data={"marked_as_read": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsGetUnreadCountTool(Tool):
    """Get unread notification count."""

    name = "notifications_get_unread_count"
    category = "notifications"
    description = "Get the count of unread notifications."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationStore

            store = NotificationStore(args["store_path"])
            count = store.unread_count()

            return ToolResult(ok=True, data={"unread_count": count})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsClearTool(Tool):
    """Clear notifications (delete)."""

    name = "notifications_clear"
    category = "notifications"
    description = "Delete notifications (all or by type/severity)."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Path to SQLite database",
            },
            "severity": {
                "type": "string",
                "description": "Clear by severity (info, warn, error) (optional)",
            },
            "notification_type": {
                "type": "string",
                "description": "Clear by type (optional)",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import NotificationStore

            store = NotificationStore(args["store_path"])

            severity = args.get("severity")
            notif_type = args.get("notification_type")

            store.clear(severity=severity, notification_type=notif_type)

            return ToolResult(ok=True, data={"cleared": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_notifications_tools(registry):
    """Register notifications tools with the tool registry."""
    tools = [
        NotificationsGetStoreTool(),
        NotificationsCreateTool(),
        NotificationsListTool(),
        NotificationsMarkReadTool(),
        NotificationsGetUnreadCountTool(),
        NotificationsClearTool(),
    ]
    for tool in tools:
        registry.register(tool)
