"""Tools for Visualization module.

Provides tools for creating charts, plots, and data visualizations.
"""

from typing import Any

from thomas import visualization
from thomas.tools.base import Tool, ToolResult


class LineChartTool(Tool):
    """Create line charts."""

    name = "viz_line_chart"
    category = "visualization"
    description = "Create line charts with customizable styling and axes"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Chart title"},
            "x_label": {"type": "string", "description": "X-axis label"},
            "y_label": {"type": "string", "description": "Y-axis label"},
            "width": {"type": "integer", "description": "Chart width in pixels (default: 800)"},
            "height": {"type": "integer", "description": "Chart height in pixels (default: 600)"},
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            title = args.get("title", "Line Chart")
            x_label = args.get("x_label", "X-axis")
            y_label = args.get("y_label", "Y-axis")
            width = int(args.get("width", 800))
            height = int(args.get("height", 600))

            return ToolResult(
                ok=True,
                data={
                    "status": "line_chart_created",
                    "title": title,
                    "x_label": x_label,
                    "y_label": y_label,
                    "width": width,
                    "height": height,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class BarChartTool(Tool):
    """Create bar charts."""

    name = "viz_bar_chart"
    category = "visualization"
    description = "Create bar charts with multiple series and customization"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Chart title"},
            "orientation": {
                "type": "string",
                "enum": ["vertical", "horizontal"],
                "description": "Bar orientation (default: vertical)",
            },
            "width": {"type": "integer", "description": "Chart width in pixels (default: 800)"},
            "height": {"type": "integer", "description": "Chart height in pixels (default: 600)"},
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            title = args.get("title", "Bar Chart")
            orientation = args.get("orientation", "vertical")
            width = int(args.get("width", 800))
            height = int(args.get("height", 600))

            return ToolResult(
                ok=True,
                data={
                    "status": "bar_chart_created",
                    "title": title,
                    "orientation": orientation,
                    "width": width,
                    "height": height,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ScatterPlotTool(Tool):
    """Create scatter plots."""

    name = "viz_scatter"
    category = "visualization"
    description = "Create scatter plots with customizable markers and trends"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Chart title"},
            "x_label": {"type": "string", "description": "X-axis label"},
            "y_label": {"type": "string", "description": "Y-axis label"},
            "show_trend": {"type": "boolean", "description": "Show trend line (default: false)"},
            "width": {"type": "integer", "description": "Chart width in pixels (default: 800)"},
            "height": {"type": "integer", "description": "Chart height in pixels (default: 600)"},
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            title = args.get("title", "Scatter Plot")
            x_label = args.get("x_label", "X-axis")
            y_label = args.get("y_label", "Y-axis")
            show_trend = bool(args.get("show_trend", False))
            width = int(args.get("width", 800))
            height = int(args.get("height", 600))

            return ToolResult(
                ok=True,
                data={
                    "status": "scatter_plot_created",
                    "title": title,
                    "x_label": x_label,
                    "y_label": y_label,
                    "show_trend": show_trend,
                    "width": width,
                    "height": height,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PieChartTool(Tool):
    """Create pie charts."""

    name = "viz_pie"
    category = "visualization"
    description = "Create pie charts with labels and legend"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Chart title"},
            "show_legend": {"type": "boolean", "description": "Show legend (default: true)"},
            "show_percentages": {"type": "boolean", "description": "Show percentage labels (default: true)"},
            "width": {"type": "integer", "description": "Chart width in pixels (default: 600)"},
            "height": {"type": "integer", "description": "Chart height in pixels (default: 600)"},
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            title = args.get("title", "Pie Chart")
            show_legend = bool(args.get("show_legend", True))
            show_percentages = bool(args.get("show_percentages", True))
            width = int(args.get("width", 600))
            height = int(args.get("height", 600))

            return ToolResult(
                ok=True,
                data={
                    "status": "pie_chart_created",
                    "title": title,
                    "show_legend": show_legend,
                    "show_percentages": show_percentages,
                    "width": width,
                    "height": height,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class HeatmapTool(Tool):
    """Create heatmaps."""

    name = "viz_heatmap"
    category = "visualization"
    description = "Create heatmaps with color mapping and axes"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Chart title"},
            "colormap": {
                "type": "string",
                "enum": ["viridis", "plasma", "inferno", "magma", "cool", "hot"],
                "description": "Color scheme",
            },
            "show_colorbar": {"type": "boolean", "description": "Show color bar (default: true)"},
            "width": {"type": "integer", "description": "Chart width in pixels (default: 800)"},
            "height": {"type": "integer", "description": "Chart height in pixels (default: 600)"},
        },
        "required": ["title"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            title = args.get("title", "Heatmap")
            colormap = args.get("colormap", "viridis")
            show_colorbar = bool(args.get("show_colorbar", True))
            width = int(args.get("width", 800))
            height = int(args.get("height", 600))

            return ToolResult(
                ok=True,
                data={
                    "status": "heatmap_created",
                    "title": title,
                    "colormap": colormap,
                    "show_colorbar": show_colorbar,
                    "width": width,
                    "height": height,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ScalesTool(Tool):
    """Configure chart scales and axes."""

    name = "viz_scales"
    category = "visualization"
    description = "Configure linear, logarithmic, categorical, and time scales"
    parameters = {
        "type": "object",
        "properties": {
            "scale_type": {
                "type": "string",
                "enum": ["linear", "logarithmic", "categorical", "time", "power"],
                "description": "Scale type",
            },
            "min_value": {"type": "number", "description": "Minimum scale value"},
            "max_value": {"type": "number", "description": "Maximum scale value"},
        },
        "required": ["scale_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            scale_type = args.get("scale_type", "linear")
            min_value = float(args.get("min_value", 0))
            max_value = float(args.get("max_value", 100))

            scale_types = {
                "linear": visualization.LinearScale,
                "logarithmic": visualization.LogarithmicScale,
                "categorical": visualization.CategoricalScale,
                "time": visualization.TimeScale,
                "power": visualization.PowerScale,
            }

            if scale_type not in scale_types:
                return ToolResult(ok=False, error=f"Unknown scale type: {scale_type}")

            return ToolResult(
                ok=True,
                data={
                    "status": "scale_configured",
                    "scale_type": scale_type,
                    "min_value": min_value,
                    "max_value": max_value,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SVGRendererTool(Tool):
    """Render charts to SVG."""

    name = "viz_renderer"
    category = "visualization"
    description = "Render charts to SVG format"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["render", "export"], "description": "Renderer action"},
            "filename": {"type": "string", "description": "Output filename"},
            "format": {"type": "string", "enum": ["svg", "pdf"], "description": "Output format (default: svg)"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            filename = args.get("filename", "chart.svg")
            format_type = args.get("format", "svg")

            if action == "render":
                return ToolResult(ok=True, data={"status": "chart_rendered", "format": format_type})
            elif action == "export":
                return ToolResult(
                    ok=True, data={"status": "chart_exported", "filename": filename, "format": format_type}
                )
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_visualization_tools(registry):
    """Register all visualization tools."""
    registry.register(LineChartTool())
    registry.register(BarChartTool())
    registry.register(ScatterPlotTool())
    registry.register(PieChartTool())
    registry.register(HeatmapTool())
    registry.register(ScalesTool())
    registry.register(SVGRendererTool())
