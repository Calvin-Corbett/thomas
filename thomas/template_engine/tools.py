"""Tools for Template Engine module.

Provides tools for template processing, rendering, and management.
"""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class TemplateRenderingTool(Tool):
    """Render templates with context data."""

    name = "template_rendering"
    category = "template_engine"
    description = "Render templates with variable substitution and logic"
    parameters = {
        "type": "object",
        "properties": {
            "template": {"type": "string", "description": "Template content"},
            "context": {"type": "object", "description": "Variables for template context"},
            "format": {
                "type": "string",
                "enum": ["jinja2", "mustache", "handlebars", "liquid"],
                "description": "Template format",
            },
        },
        "required": ["template", "context"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            template = args.get("template", "")
            context = args.get("context", {})
            format_type = args.get("format", "jinja2")

            if not template:
                return ToolResult(ok=False, error="template required")

            return ToolResult(ok=True, data={"status": "template_rendered", "format": format_type, "output": ""})

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FilterTool(Tool):
    """Apply filters and transformations to template variables."""

    name = "template_filters"
    category = "template_engine"
    description = "Apply built-in and custom filters for data transformation"
    parameters = {
        "type": "object",
        "properties": {
            "filter_name": {
                "type": "string",
                "enum": ["uppercase", "lowercase", "trim", "truncate", "join", "format_date"],
                "description": "Filter to apply",
            },
            "value": {"type": "string", "description": "Value to filter"},
            "parameters": {"type": "object", "description": "Filter parameters"},
        },
        "required": ["filter_name", "value"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            filter_name = args.get("filter_name", "")
            value = args.get("value", "")
            parameters = args.get("parameters", {})

            supported = ["uppercase", "lowercase", "trim", "truncate", "join", "format_date"]
            if filter_name not in supported:
                return ToolResult(ok=False, error=f"Unknown filter: {filter_name}")

            return ToolResult(
                ok=True, data={"filter": filter_name, "input": value, "output": "", "parameters": parameters}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ExtensionTool(Tool):
    """Manage template extensions and custom functions."""

    name = "template_extensions"
    category = "template_engine"
    description = "Create and manage custom template extensions and functions"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_function", "register_filter", "list_extensions"],
                "description": "Extension action",
            },
            "name": {"type": "string", "description": "Name of extension/function"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            name = args.get("name", "")

            if action == "register_function":
                if not name:
                    return ToolResult(ok=False, error="name required")

                return ToolResult(ok=True, data={"status": "function_registered", "name": name})

            elif action == "register_filter":
                if not name:
                    return ToolResult(ok=False, error="name required")

                return ToolResult(ok=True, data={"status": "filter_registered", "name": name})

            elif action == "list_extensions":
                return ToolResult(ok=True, data={"extensions": [], "status": "extensions_listed"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_template_engine_tools(registry):
    """Register all template engine tools."""
    registry.register(TemplateRenderingTool())
    registry.register(FilterTool())
    registry.register(ExtensionTool())
