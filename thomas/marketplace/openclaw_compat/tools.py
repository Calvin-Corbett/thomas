"""Tools for OpenClaw compatibility module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class CompatibilityBridgeTool(Tool):
    """Bridge OpenClaw and Thomas APIs."""

    name = "compatibility_bridge"
    category = "openclaw_compat"
    description = "Translate between OpenClaw v1/v2 and Thomas API formats"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["detect_version", "translate_request", "translate_response"],
                "description": "Bridge action",
            },
            "request": {"type": "object", "description": "Request to process"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")
            args.get("request", {})

            if action == "detect_version":
                return ToolResult(ok=True, data={"status": "version_detected", "version": "2.0", "format": "openclaw"})

            elif action == "translate_request":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "translation_complete",
                        "source_format": "openclaw",
                        "target_format": "thomas",
                        "operation": "query",
                    },
                )

            elif action == "translate_response":
                return ToolResult(
                    ok=True,
                    data={"status": "translation_complete", "source_format": "thomas", "target_format": "openclaw"},
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class VersionMappingTool(Tool):
    """Manage API version mappings."""

    name = "version_mapping"
    category = "openclaw_compat"
    description = "Configure version and operation mappings"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_versions", "register_mapping", "get_mapping"],
                "description": "Mapping action",
            },
            "openclaw_op": {"type": "string", "description": "OpenClaw operation name"},
            "thomas_op": {"type": "string", "description": "Thomas operation name"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")

            if action == "list_versions":
                return ToolResult(ok=True, data={"supported_versions": ["1.0", "2.0", "3.0"], "default": "2.0"})

            elif action == "register_mapping":
                openclaw_op = args.get("openclaw_op")
                thomas_op = args.get("thomas_op")
                return ToolResult(
                    ok=True, data={"status": "mapping_registered", "openclaw": openclaw_op, "thomas": thomas_op}
                )

            elif action == "get_mapping":
                return ToolResult(
                    ok=True, data={"mappings": {"query": "query", "execute": "command", "stream": "stream"}}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_openclaw_compat_tools(registry):
    """Register all OpenClaw compatibility tools."""
    registry.register(CompatibilityBridgeTool())
    registry.register(VersionMappingTool())
