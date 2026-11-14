"""Tools for notifications module - notification management and delivery."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thomas.core.file_access import names_another_volume
from thomas.tools.base import Tool, ToolResult
from thomas.tools.fs_scope import Scope

log = logging.getLogger(__name__)


def _database_under(scope: Scope, text: Any) -> str:
    """The database file ``text`` names inside the scope's folder, as the path to open.

    The name is read as text first, so another drive or a network name is refused before the disk is touched. Only then
    does the scope resolve it, which also refuses a ``..`` and a link that leads out. The path the scope returns is the
    one opened, never the text the model sent.
    """
    if not isinstance(text, str) or not text.strip() or "\x00" in text:
        raise ValueError("store_path must name a database file inside the notifications folder")
    root = Path(scope.root)
    if names_another_volume(text, root) or ".." in Path(text).parts:
        raise ValueError(f"store_path leaves the notifications folder: {text}")
    try:
        return str(scope.resolve(text))
    except (ValueError, OSError):
        raise ValueError(f"store_path leaves the notifications folder: {text}") from None


class _NotificationTool(Tool):
    """A notification tool whose database files all live inside one folder, the scope's."""

    def __init__(self, scope: Scope) -> None:
        self._scope = scope

    def _open(self, args: dict[str, Any]) -> Any:
        from .store import NotificationStore

        return NotificationStore(_database_under(self._scope, args.get("store_path")))


class NotificationsGetStoreTool(_NotificationTool):
    """Open a notification store inside the notifications folder."""

    name = "notifications_get_store"
    category = "notifications"
    description = "Open a notification store, a database file inside the notifications folder."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            store = self._open(args)

            return ToolResult(
                ok=True,
                data={
                    "store_path": str(store.db_path) if hasattr(store, "db_path") else "in-memory",
                    "initialized": True,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsCreateTool(_NotificationTool):
    """Create and store a notification."""

    name = "notifications_create"
    category = "notifications"
    description = "Create and store a new notification."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
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
            from .store import NotificationCreate

            store = self._open(args)

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


class NotificationsListTool(_NotificationTool):
    """List notifications with filtering."""

    name = "notifications_list"
    category = "notifications"
    description = "List notifications with optional filtering."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
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
            store = self._open(args)

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


class NotificationsMarkReadTool(_NotificationTool):
    """Mark notifications as read."""

    name = "notifications_mark_read"
    category = "notifications"
    description = "Mark one or all notifications as read."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
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
            store = self._open(args)

            notif_id = args.get("notification_id")
            if notif_id:
                store.mark_read(notif_id)
            else:
                store.mark_all_read()

            return ToolResult(ok=True, data={"marked_as_read": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsGetUnreadCountTool(_NotificationTool):
    """Get unread notification count."""

    name = "notifications_get_unread_count"
    category = "notifications"
    description = "Get the count of unread notifications."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
            },
        },
        "required": ["store_path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            store = self._open(args)
            count = store.unread_count()

            return ToolResult(ok=True, data={"unread_count": count})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class NotificationsClearTool(_NotificationTool):
    """Clear notifications (delete)."""

    name = "notifications_clear"
    category = "notifications"
    description = "Delete notifications (all or by type/severity)."
    parameters = {
        "type": "object",
        "properties": {
            "store_path": {
                "type": "string",
                "description": "Database file inside the notifications folder",
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
            store = self._open(args)

            severity = args.get("severity")
            notif_type = args.get("notification_type")

            store.clear(severity=severity, notification_type=notif_type)

            return ToolResult(ok=True, data={"cleared": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def build_notifications_tools(scope: Scope) -> list[Tool]:
    """The six notification tools, each keeping its database files inside ``scope``'s folder."""
    return [
        NotificationsGetStoreTool(scope),
        NotificationsCreateTool(scope),
        NotificationsListTool(scope),
        NotificationsMarkReadTool(scope),
        NotificationsGetUnreadCountTool(scope),
        NotificationsClearTool(scope),
    ]
