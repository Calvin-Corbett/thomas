"""Tools for units module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult

from . import core


class UnitConversionTool(Tool):
    """Convert between units."""

    name = "unit_conversion"
    category = "units"
    description = "Convert values between different units of measurement"
    parameters = {
        "type": "object",
        "properties": {
            "value": {"type": "number", "description": "Value to convert"},
            "from_unit": {"type": "string", "description": "Source unit"},
            "to_unit": {"type": "string", "description": "Target unit"},
        },
        "required": ["value", "from_unit", "to_unit"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            value = float(args.get("value", 0))
            from_unit = args.get("from_unit")
            to_unit = args.get("to_unit")

            registry = core.UnitRegistry()
            result = registry.convert(value, from_unit, to_unit)

            if result is None:
                return ToolResult(ok=False, error=f"Cannot convert from {from_unit} to {to_unit}")

            return ToolResult(
                ok=True, data={"value": value, "from_unit": from_unit, "to_unit": to_unit, "result": round(result, 6)}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_units_tools(registry):
    """Register all units tools."""
    registry.register(UnitConversionTool())
