"""Tools for Canvas module.

Provides tools for drawing, shape management, and layer control.
"""

from typing import Any

from thomas.canvas import core
from thomas.tools.base import Tool, ToolResult


class DrawingTool(Tool):
    """Draw shapes on the canvas."""

    name = "canvas_draw"
    category = "canvas"
    description = "Draw shapes on canvas"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_canvas", "draw_rectangle", "draw_circle", "draw_polygon"],
                "description": "Drawing action",
            },
            "width": {"type": "number", "description": "Canvas width"},
            "height": {"type": "number", "description": "Canvas height"},
            "x": {"type": "number", "description": "X coordinate"},
            "y": {"type": "number", "description": "Y coordinate"},
            "size": {"type": "number", "description": "Size (width/height/radius)"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.canvas: core.Canvas | None = None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_canvas":
                width = args.get("width", 800)
                height = args.get("height", 600)
                self.canvas = core.Canvas(width, height)
                self.canvas.create_layer("default")
                return ToolResult(ok=True, data={"canvas_id": self.canvas.id, "width": width, "height": height})

            elif action == "draw_rectangle":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                x = args.get("x", 0)
                y = args.get("y", 0)
                width = args.get("size", 100)
                height = args.get("size", 100)

                rect = core.Rectangle(x, y, width, height)
                self.canvas.add_shape(rect)
                return ToolResult(ok=True, data={"shape_id": rect.id})

            elif action == "draw_circle":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                x = args.get("x", 0)
                y = args.get("y", 0)
                radius = args.get("size", 50)

                circle = core.Circle(x, y, radius)
                self.canvas.add_shape(circle)
                return ToolResult(ok=True, data={"shape_id": circle.id})

            elif action == "draw_polygon":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                x = args.get("x", 0)
                y = args.get("y", 0)
                points = [(0, 0), (50, 0), (50, 50), (0, 50)]

                polygon = core.Polygon(x, y, points)
                self.canvas.add_shape(polygon)
                return ToolResult(ok=True, data={"shape_id": polygon.id})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LayerManagementTool(Tool):
    """Manage canvas layers."""

    name = "canvas_layers"
    category = "canvas"
    description = "Create, manage, and organize layers"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_layer", "list_layers", "set_active", "remove_layer"],
                "description": "Layer action",
            },
            "layer_name": {"type": "string", "description": "Name of the layer"},
            "layer_id": {"type": "string", "description": "Layer identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.canvas: core.Canvas | None = None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_layer":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                layer_name = args.get("layer_name", "layer")
                layer = self.canvas.create_layer(layer_name)
                return ToolResult(ok=True, data={"layer_id": layer.id, "name": layer_name})

            elif action == "list_layers":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                layers = [
                    {"id": layer.id, "name": layer.name, "visible": layer.visible} for layer in self.canvas.layers
                ]
                return ToolResult(ok=True, data={"layers": layers})

            elif action == "set_active":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                layer_id = args.get("layer_id", "")
                if self.canvas.set_active_layer(layer_id):
                    return ToolResult(ok=True, data={"active_layer": layer_id})
                else:
                    return ToolResult(ok=False, error=f"Layer not found: {layer_id}")

            elif action == "remove_layer":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                layer_id = args.get("layer_id", "")
                if self.canvas.remove_layer(layer_id):
                    return ToolResult(ok=True, data={"removed": layer_id})
                else:
                    return ToolResult(ok=False, error=f"Layer not found: {layer_id}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CanvasTransformTool(Tool):
    """Transform shapes and canvas elements."""

    name = "canvas_transform"
    category = "canvas"
    description = "Apply transformations to shapes"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_canvas", "export_svg"], "description": "Transform action"}
        },
        "required": ["action"],
    }

    def __init__(self):
        self.canvas: core.Canvas | None = None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_canvas":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                return ToolResult(ok=True, data=self.canvas.to_dict())

            elif action == "export_svg":
                if not self.canvas:
                    return ToolResult(ok=False, error="No canvas created")

                svg = self.canvas.export_svg()
                return ToolResult(ok=True, data={"svg": svg})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_canvas_tools(registry):
    """Register all canvas tools."""
    registry.register(DrawingTool())
    registry.register(LayerManagementTool())
    registry.register(CanvasTransformTool())
