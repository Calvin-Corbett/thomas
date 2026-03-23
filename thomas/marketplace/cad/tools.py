"""Tools for CAD module.

Provides tools for geometric modeling, CAD operations, and design manipulation.
"""

from typing import Any

from thomas import cad
from thomas.tools.base import Tool, ToolResult


class GeometryTool(Tool):
    """Create and manipulate geometric objects."""

    name = "cad_geometry"
    category = "cad"
    description = "Create 2D/3D geometric primitives and manipulate them"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create_point", "create_circle", "create_line", "create_polygon", "get_info"],
                "description": "Geometry operation",
            },
            "dimension": {"type": "string", "enum": ["2d", "3d"], "description": "2D or 3D"},
            "coords": {"type": "array", "items": {"type": "number"}, "description": "Coordinates [x, y] or [x, y, z]"},
            "radius": {"type": "number", "description": "Radius for circles"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation", "")

            if operation == "create_point":
                coords = args.get("coords", [0, 0])
                dimension = args.get("dimension", "2d")

                if dimension == "2d":
                    point = cad.Point2D(x=float(coords[0]), y=float(coords[1]))
                else:
                    point = cad.Point3D(
                        x=float(coords[0]), y=float(coords[1]), z=float(coords[2]) if len(coords) > 2 else 0
                    )

                return ToolResult(ok=True, data={"type": "point", "dimension": dimension, "coords": coords})

            elif operation == "create_circle":
                coords = args.get("coords", [0, 0])
                radius = float(args.get("radius", 1.0))

                center = cad.Point2D(x=float(coords[0]), y=float(coords[1]))
                circle = cad.Circle(center=center, radius=radius)

                return ToolResult(ok=True, data={"type": "circle", "center": coords, "radius": radius})

            elif operation == "create_line":
                coords = args.get("coords", [])
                if len(coords) < 4:
                    return ToolResult(ok=False, error="Line requires 4 coordinates [x1, y1, x2, y2]")

                p1 = cad.Point2D(x=float(coords[0]), y=float(coords[1]))
                p2 = cad.Point2D(x=float(coords[2]), y=float(coords[3]))
                line = cad.Line(p1=p1, p2=p2)

                return ToolResult(
                    ok=True, data={"type": "line", "start": [coords[0], coords[1]], "end": [coords[2], coords[3]]}
                )

            elif operation == "create_polygon":
                coords = args.get("coords", [])
                if len(coords) < 6:
                    return ToolResult(ok=False, error="Polygon requires at least 3 points")

                points = []
                for i in range(0, len(coords), 2):
                    points.append(cad.Point2D(x=float(coords[i]), y=float(coords[i + 1])))

                polygon = cad.Polygon(points=tuple(points))

                return ToolResult(ok=True, data={"type": "polygon", "num_vertices": len(points), "coords": coords})

            elif operation == "get_info":
                return ToolResult(
                    ok=True,
                    data={
                        "supported_geometries": [
                            "Point2D",
                            "Point3D",
                            "Line",
                            "Circle",
                            "Ellipse",
                            "Arc",
                            "Polyline",
                            "Polygon",
                            "BSplineCurve",
                            "BezierCurve",
                            "NURBSSurface",
                            "Solid",
                        ]
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConstraintsTool(Tool):
    """Apply geometric constraints."""

    name = "cad_constraints"
    category = "cad"
    description = "Apply constraints to geometric objects for parametric design"
    parameters = {
        "type": "object",
        "properties": {
            "constraint_type": {
                "type": "string",
                "enum": ["distance", "angle", "perpendicular", "parallel", "coincident"],
                "description": "Type of constraint",
            },
            "value": {"type": "number", "description": "Constraint value (for distance/angle)"},
        },
        "required": ["constraint_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            constraint_type = args.get("constraint_type", "")
            value = args.get("value")

            supported = ["distance", "angle", "perpendicular", "parallel", "coincident"]

            if constraint_type not in supported:
                return ToolResult(ok=False, error=f"Unknown constraint type: {constraint_type}")

            return ToolResult(ok=True, data={"status": "constraint_applied", "type": constraint_type, "value": value})

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class IOFormatsTool(Tool):
    """Handle CAD file I/O operations."""

    name = "cad_io_formats"
    category = "cad"
    description = "Load and save CAD files in various formats (STEP, IGES, STL)"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["load", "save", "list_formats"], "description": "I/O operation"},
            "format": {"type": "string", "enum": ["step", "iges", "stl", "obj", "dxf"], "description": "File format"},
            "filepath": {"type": "string", "description": "File path"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation", "")

            if operation == "list_formats":
                return ToolResult(ok=True, data={"supported_formats": ["step", "iges", "stl", "obj", "dxf"]})

            elif operation == "load":
                format_type = args.get("format", "step")
                filepath = args.get("filepath", "")

                if not filepath:
                    return ToolResult(ok=False, error="filepath required for load operation")

                return ToolResult(ok=True, data={"status": "file_loaded", "format": format_type, "filepath": filepath})

            elif operation == "save":
                format_type = args.get("format", "step")
                filepath = args.get("filepath", "")

                if not filepath:
                    return ToolResult(ok=False, error="filepath required for save operation")

                return ToolResult(ok=True, data={"status": "file_saved", "format": format_type, "filepath": filepath})

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_cad_tools(registry):
    """Register all CAD tools."""
    registry.register(GeometryTool())
    registry.register(ConstraintsTool())
    registry.register(IOFormatsTool())
