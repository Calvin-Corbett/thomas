"""2D drawing canvas with shapes, layers, and transforms.

Provides a 2D canvas system with shape drawing, layering, and geometric transformations.
"""

import math
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class ShapeType(str, Enum):
    """Types of shapes that can be drawn."""

    RECTANGLE = "rectangle"
    CIRCLE = "circle"
    POLYGON = "polygon"
    LINE = "line"
    TEXT = "text"
    IMAGE = "image"


@dataclass
class Color:
    """Color representation."""

    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0

    def to_hex(self) -> str:
        """Convert to hex color."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def to_rgba(self) -> str:
        """Convert to RGBA string."""
        return f"rgba({self.r}, {self.g}, {self.b}, {self.a})"


@dataclass
class Point:
    """2D point."""

    x: float = 0.0
    y: float = 0.0

    def distance_to(self, other: "Point") -> float:
        """Calculate distance to another point."""
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)

    def rotate(self, angle: float, origin: Optional["Point"] = None) -> "Point":
        """Rotate point around origin."""
        if origin is None:
            origin = Point(0, 0)

        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        x = (self.x - origin.x) * cos_a - (self.y - origin.y) * sin_a + origin.x
        y = (self.x - origin.x) * sin_a + (self.y - origin.y) * cos_a + origin.y

        return Point(x, y)

    def translate(self, dx: float, dy: float) -> "Point":
        """Translate point by offset."""
        return Point(self.x + dx, self.y + dy)


@dataclass
class BoundingBox:
    """Bounding box for shapes."""

    x_min: float = 0.0
    y_min: float = 0.0
    x_max: float = 0.0
    y_max: float = 0.0

    def width(self) -> float:
        """Get width."""
        return self.x_max - self.x_min

    def height(self) -> float:
        """Get height."""
        return self.y_max - self.y_min

    def contains_point(self, point: Point) -> bool:
        """Check if point is inside bounding box."""
        return self.x_min <= point.x <= self.x_max and self.y_min <= point.y <= self.y_max

    def intersects(self, other: "BoundingBox") -> bool:
        """Check if this box intersects with another."""
        return not (
            self.x_max < other.x_min or self.x_min > other.x_max or self.y_max < other.y_min or self.y_min > other.y_max
        )


@dataclass
class Transform:
    """2D transformation matrix."""

    sx: float = 1.0  # scale x
    sy: float = 1.0  # scale y
    tx: float = 0.0  # translate x
    ty: float = 0.0  # translate y
    rotation: float = 0.0  # rotation angle in radians

    def apply_to_point(self, point: Point) -> Point:
        """Apply transform to a point."""
        # Scale
        scaled = Point(point.x * self.sx, point.y * self.sy)
        # Rotate
        rotated = scaled.rotate(self.rotation)
        # Translate
        return rotated.translate(self.tx, self.ty)

    def compose(self, other: "Transform") -> "Transform":
        """Compose two transforms."""
        return Transform(
            sx=self.sx * other.sx,
            sy=self.sy * other.sy,
            tx=self.tx + other.tx,
            ty=self.ty + other.ty,
            rotation=self.rotation + other.rotation,
        )

    def inverse(self) -> "Transform":
        """Get inverse transform."""
        return Transform(
            sx=1.0 / self.sx if self.sx != 0 else 1.0,
            sy=1.0 / self.sy if self.sy != 0 else 1.0,
            tx=-self.tx,
            ty=-self.ty,
            rotation=-self.rotation,
        )


class Shape:
    """Base class for drawable shapes."""

    def __init__(self, shape_type: ShapeType, x: float = 0.0, y: float = 0.0):
        self.id = str(uuid.uuid4())
        self.type = shape_type
        self.position = Point(x, y)
        self.fill_color = Color(200, 200, 200)
        self.stroke_color = Color(0, 0, 0)
        self.stroke_width = 1
        self.opacity = 1.0
        self.visible = True
        self.transform = Transform()

    def get_bounding_box(self) -> BoundingBox:
        """Get bounding box of shape."""
        return BoundingBox(self.position.x, self.position.y, self.position.x, self.position.y)

    def to_dict(self) -> dict[str, Any]:
        """Convert shape to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "position": {"x": self.position.x, "y": self.position.y},
            "fill": self.fill_color.to_hex(),
            "stroke": self.stroke_color.to_hex(),
            "stroke_width": self.stroke_width,
            "opacity": self.opacity,
            "visible": self.visible,
        }


class Rectangle(Shape):
    """Rectangle shape."""

    def __init__(self, x: float = 0.0, y: float = 0.0, width: float = 100.0, height: float = 100.0):
        super().__init__(ShapeType.RECTANGLE, x, y)
        self.width = width
        self.height = height

    def get_bounding_box(self) -> BoundingBox:
        """Get bounding box."""
        return BoundingBox(
            self.position.x, self.position.y, self.position.x + self.width, self.position.y + self.height
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({"width": self.width, "height": self.height})
        return data


class Circle(Shape):
    """Circle shape."""

    def __init__(self, x: float = 0.0, y: float = 0.0, radius: float = 50.0):
        super().__init__(ShapeType.CIRCLE, x, y)
        self.radius = radius

    def get_bounding_box(self) -> BoundingBox:
        """Get bounding box."""
        return BoundingBox(
            self.position.x - self.radius,
            self.position.y - self.radius,
            self.position.x + self.radius,
            self.position.y + self.radius,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({"radius": self.radius})
        return data


class Polygon(Shape):
    """Polygon shape."""

    def __init__(self, x: float = 0.0, y: float = 0.0, points: list[tuple[float, float]] | None = None):
        super().__init__(ShapeType.POLYGON, x, y)
        self.points = [Point(p[0], p[1]) for p in points] if points else []

    def get_bounding_box(self) -> BoundingBox:
        """Get bounding box."""
        if not self.points:
            return BoundingBox(self.position.x, self.position.y, self.position.x, self.position.y)

        x_coords = [p.x for p in self.points]
        y_coords = [p.y for p in self.points]

        return BoundingBox(min(x_coords), min(y_coords), max(x_coords), max(y_coords))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        data = super().to_dict()
        data.update({"points": [(p.x, p.y) for p in self.points]})
        return data


class Layer:
    """A drawing layer."""

    def __init__(self, name: str, visible: bool = True, opacity: float = 1.0):
        self.id = str(uuid.uuid4())
        self.name = name
        self.visible = visible
        self.opacity = opacity
        self.shapes: list[Shape] = []
        self.blend_mode = "normal"

    def add_shape(self, shape: Shape) -> None:
        """Add a shape to the layer."""
        self.shapes.append(shape)

    def remove_shape(self, shape_id: str) -> bool:
        """Remove a shape from the layer."""
        for i, shape in enumerate(self.shapes):
            if shape.id == shape_id:
                self.shapes.pop(i)
                return True
        return False

    def get_shape(self, shape_id: str) -> Shape | None:
        """Get a shape by ID."""
        for shape in self.shapes:
            if shape.id == shape_id:
                return shape
        return None

    def get_shapes_at(self, point: Point) -> list[Shape]:
        """Get all shapes at a point."""
        result = []
        for shape in self.shapes:
            if shape.visible and shape.get_bounding_box().contains_point(point):
                result.append(shape)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "visible": self.visible,
            "opacity": self.opacity,
            "blend_mode": self.blend_mode,
            "shapes": [shape.to_dict() for shape in self.shapes],
        }


class Canvas:
    """2D drawing canvas."""

    def __init__(self, width: float = 800.0, height: float = 600.0):
        self.id = str(uuid.uuid4())
        self.width = width
        self.height = height
        self.layers: list[Layer] = []
        self.background_color = Color(255, 255, 255)
        self.active_layer: Layer | None = None
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []

    def add_layer(self, layer: Layer) -> None:
        """Add a layer."""
        self.layers.append(layer)
        if self.active_layer is None:
            self.active_layer = layer

    def remove_layer(self, layer_id: str) -> bool:
        """Remove a layer."""
        for i, layer in enumerate(self.layers):
            if layer.id == layer_id:
                if self.active_layer == layer and len(self.layers) > 1:
                    self.active_layer = self.layers[0 if i > 0 else 1]
                self.layers.pop(i)
                return True
        return False

    def create_layer(self, name: str) -> Layer:
        """Create and add a new layer."""
        layer = Layer(name)
        self.add_layer(layer)
        self.active_layer = layer
        return layer

    def set_active_layer(self, layer_id: str) -> bool:
        """Set the active layer."""
        for layer in self.layers:
            if layer.id == layer_id:
                self.active_layer = layer
                return True
        return False

    def add_shape(self, shape: Shape) -> None:
        """Add a shape to the active layer."""
        if self.active_layer:
            self.active_layer.add_shape(shape)

    def remove_shape(self, shape_id: str) -> bool:
        """Remove a shape from canvas."""
        for layer in self.layers:
            if layer.remove_shape(shape_id):
                return True
        return False

    def get_all_shapes(self) -> list[Shape]:
        """Get all shapes from all layers."""
        shapes = []
        for layer in self.layers:
            shapes.extend(layer.shapes)
        return shapes

    def export_svg(self) -> str:
        """Export canvas as SVG."""
        svg_parts = [f'<svg width="{self.width}" height="{self.height}" xmlns="http://www.w3.org/2000/svg">']
        svg_parts.append(f'<rect width="{self.width}" height="{self.height}" fill="{self.background_color.to_hex()}"/>')

        for layer in self.layers:
            if layer.visible:
                for shape in layer.shapes:
                    if shape.visible:
                        if shape.type == ShapeType.RECTANGLE:
                            rect = shape
                            svg_parts.append(
                                f'<rect x="{rect.position.x}" y="{rect.position.y}" '
                                f'width="{rect.width}" height="{rect.height}" '
                                f'fill="{rect.fill_color.to_hex()}" stroke="{rect.stroke_color.to_hex()}" '
                                f'stroke-width="{rect.stroke_width}"/>'
                            )
                        elif shape.type == ShapeType.CIRCLE:
                            circ = shape
                            svg_parts.append(
                                f'<circle cx="{circ.position.x}" cy="{circ.position.y}" '
                                f'r="{circ.radius}" fill="{circ.fill_color.to_hex()}" '
                                f'stroke="{circ.stroke_color.to_hex()}" stroke-width="{circ.stroke_width}"/>'
                            )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "background": self.background_color.to_hex(),
            "layers": [layer.to_dict() for layer in self.layers],
        }
