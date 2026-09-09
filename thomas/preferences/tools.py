"""Tools for preferences module - user preferences and settings."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class PreferencesGetTool(Tool):
    """Get user preference."""

    name = "preferences_get"
    category = "preferences"
    description = "Retrieve a user preference value."
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Preference key",
            },
            "default": {
                "type": "string",
                "description": "Default value if not set",
            },
        },
        "required": ["key"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import get_preference

            value = get_preference(args["key"], default=args.get("default"))
            return ToolResult(ok=True, data={"key": args["key"], "value": value})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PreferencesSetTool(Tool):
    """Set user preference."""

    name = "preferences_set"
    category = "preferences"
    description = "Set a user preference value."
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Preference key",
            },
            "value": {
                "type": ["string", "number", "boolean", "object"],
                "description": "Preference value",
            },
        },
        "required": ["key", "value"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import set_preference

            set_preference(args["key"], args["value"])
            return ToolResult(ok=True, data={"set": True, "key": args["key"]})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PreferencesListTool(Tool):
    """List all preferences."""

    name = "preferences_list"
    category = "preferences"
    description = "List all user preferences."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import list_preferences

            prefs = list_preferences()
            return ToolResult(ok=True, data={"preferences": prefs or {}})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PreferencesResetTool(Tool):
    """Reset preferences to defaults."""

    name = "preferences_reset"
    category = "preferences"
    description = "Reset preferences to default values."
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Specific key to reset (optional, resets all if not provided)",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .store import reset_preferences

            key = args.get("key")
            reset_preferences(key)
            return ToolResult(ok=True, data={"reset": True})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_preferences_tools(registry):
    """Register preferences tools with the tool registry."""
    tools = [
        PreferencesGetTool(),
        PreferencesSetTool(),
        PreferencesListTool(),
        PreferencesResetTool(),
    ]
    for tool in tools:
        registry.register(tool)
