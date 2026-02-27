"""Tools for platform compatibility module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult

from . import core


class PlatformDetectionTool(Tool):
    """Detect platform capabilities."""

    name = "platform_detection"
    category = "platform_compat"
    description = "Detect OS, architecture, and platform capabilities"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "enum": ["os", "architecture", "python_version", "capabilities"],
                "description": "Query type",
            }
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            query = args.get("query")
            detector = core.PlatformDetector()

            if query == "os":
                return ToolResult(
                    ok=True, data={"os": detector.get_os().value, "platform_string": detector.get_platform_string()}
                )

            elif query == "architecture":
                return ToolResult(
                    ok=True, data={"architecture": detector.get_architecture().value, "is_64bit": detector.is_64bit()}
                )

            elif query == "python_version":
                return ToolResult(ok=True, data={"version": detector.get_python_version()})

            elif query == "capabilities":
                return ToolResult(
                    ok=True, data={"features": ["threading", "asyncio", "multiprocessing"], "limitations": []}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown query: {query}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FeatureFlagTool(Tool):
    """Manage feature flags."""

    name = "feature_flags"
    category = "platform_compat"
    description = "Check and manage feature availability"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["check", "enable", "disable", "list"], "description": "Flag action"},
            "feature": {"type": "string", "description": "Feature name"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")

            if action == "check":
                feature = args.get("feature")
                return ToolResult(ok=True, data={"feature": feature, "enabled": True})

            elif action == "list":
                return ToolResult(
                    ok=True, data={"features": {"async_support": True, "multiprocessing": True, "gpu_support": False}}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_platform_compat_tools(registry):
    """Register all platform compatibility tools."""
    registry.register(PlatformDetectionTool())
    registry.register(FeatureFlagTool())
