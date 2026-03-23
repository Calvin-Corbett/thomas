"""Tools for design patterns module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult

from . import core


class PatternImplementationTool(Tool):
    """Implement design patterns."""

    name = "pattern_implementation"
    category = "patterns"
    description = "Create instances of design patterns"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "enum": ["factory", "observer", "strategy", "command", "state", "singleton"],
                "description": "Pattern type",
            }
        },
        "required": ["pattern"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pattern = args.get("pattern")

            if pattern == "factory":
                factory = core.ConcreteFactory()
                return ToolResult(ok=True, data={"status": "factory_created", "pattern": "factory"})

            elif pattern == "observer":
                subject = core.Subject()
                return ToolResult(ok=True, data={"status": "observer_created", "pattern": "observer", "observers": 0})

            elif pattern == "strategy":
                context = core.Context(None)
                return ToolResult(ok=True, data={"status": "strategy_created", "pattern": "strategy"})

            elif pattern == "command":
                invoker = core.CommandInvoker()
                return ToolResult(ok=True, data={"status": "command_created", "pattern": "command", "history": 0})

            elif pattern == "state":
                return ToolResult(ok=True, data={"status": "state_machine_created", "pattern": "state"})

            elif pattern == "singleton":
                instance = core.Singleton()
                return ToolResult(ok=True, data={"status": "singleton_created", "pattern": "singleton"})

            else:
                return ToolResult(ok=False, error=f"Unknown pattern: {pattern}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_patterns_tools(registry):
    """Register all pattern tools."""
    registry.register(PatternImplementationTool())
