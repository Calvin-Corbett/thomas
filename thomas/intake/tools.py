"""Tools for intake module - input capture from clipboard, hotkeys, etc."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class IntakeGetClipboardTool(Tool):
    """Get current clipboard content."""

    name = "intake_get_clipboard"
    category = "intake"
    description = "Retrieve current clipboard content."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .clipboard_watcher import get_clipboard

            content = get_clipboard()
            return ToolResult(ok=True, data={"clipboard": content})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class IntakeSetClipboardTool(Tool):
    """Set clipboard content."""

    name = "intake_set_clipboard"
    category = "intake"
    description = "Copy text to clipboard."
    parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Content to copy to clipboard",
            },
        },
        "required": ["content"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .clipboard_watcher import set_clipboard

            set_clipboard(args["content"])
            return ToolResult(ok=True, data={"set": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class IntakeStartWatcherTool(Tool):
    """Start clipboard watcher."""

    name = "intake_start_watcher"
    category = "intake"
    description = "Start watching clipboard for changes."
    parameters = {
        "type": "object",
        "properties": {
            "poll_interval_ms": {
                "type": "integer",
                "description": "Poll interval in milliseconds (default: 500)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .clipboard_watcher import start_watcher

            interval = args.get("poll_interval_ms", 500) / 1000.0
            start_watcher(interval=interval)
            return ToolResult(ok=True, data={"watcher_started": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_intake_tools(registry):
    """Register intake tools with the tool registry."""
    tools = [
        IntakeGetClipboardTool(),
        IntakeSetClipboardTool(),
        IntakeStartWatcherTool(),
    ]
    for tool in tools:
        registry.register(tool)
