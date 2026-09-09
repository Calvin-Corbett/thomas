"""Tools for companion module - device management and audit logging."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)


class CompanionGetDevicesTool(Tool):
    """Get connected companion devices."""

    name = "companion_get_devices"
    category = "companion"
    description = "List connected companion devices and their status."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .devices import get_devices

            devices = get_devices()
            return ToolResult(
                ok=True,
                data={
                    "device_count": len(devices),
                    "devices": [
                        {
                            "id": d.get("id"),
                            "name": d.get("name"),
                            "type": d.get("type"),
                        }
                        for d in devices
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CompanionLogAuditEventTool(Tool):
    """Log an audit event."""

    name = "companion_log_audit_event"
    category = "companion"
    description = "Log an action to the audit trail."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action name",
            },
            "details": {
                "type": "object",
                "description": "Action details",
            },
            "timestamp": {
                "type": "integer",
                "description": "Unix timestamp (optional)",
            },
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from .audit import log_audit_event

            result = log_audit_event(
                action=args["action"],
                details=args.get("details", {}),
                timestamp=args.get("timestamp"),
            )
            return ToolResult(ok=True, data=result)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_companion_tools(registry):
    """Register companion tools with the tool registry."""
    tools = [
        CompanionGetDevicesTool(),
        CompanionLogAuditEventTool(),
    ]
    for tool in tools:
        registry.register(tool)
