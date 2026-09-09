"""Tools for watcher module - file system and event watching."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class WatcherWatchPathTool(Tool):
    """Watch a file or directory for changes."""

    name = "watcher_watch_path"
    category = "watcher"
    description = "Start watching a path for file system changes."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File or directory path to watch",
            },
            "recursive": {
                "type": "boolean",
                "description": "Watch subdirectories (default: true)",
            },
            "patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File patterns to match (optional)",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .observer import watch_path

            watch_id = watch_path(
                path=args["path"],
                recursive=args.get("recursive", True),
                patterns=args.get("patterns", []),
            )
            return ToolResult(ok=True, data={"watch_id": watch_id, "watching": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WatcherStopWatchingTool(Tool):
    """Stop watching a path."""

    name = "watcher_stop_watching"
    category = "watcher"
    description = "Stop watching a path for changes."
    parameters = {
        "type": "object",
        "properties": {
            "watch_id": {
                "type": "string",
                "description": "Watch ID to stop",
            },
        },
        "required": ["watch_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .observer import stop_watching

            stop_watching(args["watch_id"])
            return ToolResult(ok=True, data={"stopped": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WatcherListWatchesTool(Tool):
    """List active watches."""

    name = "watcher_list_watches"
    category = "watcher"
    description = "List all active file system watches."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .observer import list_watches

            watches = list_watches()
            return ToolResult(ok=True, data={"watches": watches or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WatcherGetEventsTool(Tool):
    """Get recent watcher events."""

    name = "watcher_get_events"
    category = "watcher"
    description = "Get recent file system watcher events."
    parameters = {
        "type": "object",
        "properties": {
            "watch_id": {
                "type": "string",
                "description": "Watch ID (optional, get all if not provided)",
            },
            "limit": {
                "type": "integer",
                "description": "Max events to return (default: 50)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .observer import get_events

            events = get_events(
                watch_id=args.get("watch_id"),
                limit=args.get("limit", 50),
            )
            return ToolResult(ok=True, data={"events": events or []})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_watcher_tools(registry):
    """Register watcher tools with the tool registry."""
    tools = [
        WatcherWatchPathTool(),
        WatcherStopWatchingTool(),
        WatcherListWatchesTool(),
        WatcherGetEventsTool(),
    ]
    for tool in tools:
        registry.register(tool)
