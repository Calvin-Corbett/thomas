"""
Core geometric types for the CAD engine.

Defines Point2D, Point3D, vectors, curves, surfaces, and solid representations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class DrawingUnit(Enum):
    """Drawing unit system."""

    MM = "mm"
    CM = "cm"
    M = "m"
    INCH = "inch"
    FOOT = "foot"
    YARD = "yard"


class Material(Enum):
    """Common materials."""

    STEEL = "steel"
    ALUMINUM = "aluminum"
    COPPER = "copper"
    PLASTIC = "plastic"
    WOOD = "wood"
    COMPOSITE = "composite"


@dataclass
class Point2D:
    """A 2D point."""

    x: float
    y: float

    def __add__(self, other: Vector2D) -> Point2D:
        """Add a vector to this point."""
        return Point2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Point2D) -> Vector2D:
        """Subtract two points to get a vector."""
        return Vector2D(self.x - other.x, self.y - other.y)

    def distance_to(self, other: Point2D) -> float:
        """Euclidean distance to another point."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def to_3d(self, z: float = 0.0) -> Point3D:
        """Convert to 3D point with given z coordinate."""
        return Point3D(self.x, self.y, z)

    def __repr__(self) -> str:
        return f"Point2D({self.x}, {self.y})"


@dataclass
class Point3D:
    """A 3D point."""

    x: float
    y: float
    z: float

    def __add__(self, other: Vector3D) -> Point3D:
        """Add a vector to this point."""
        return Point3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Point3D) -> Vector3D:
        """Subtract two points to get a vector."""
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def distance_to(self, other: Point3D) -> float:
        """Euclidean distance to another point."""
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def to_2d(self) -> Point2D:
        """Project to 2D (drop z coordinate)."""
        return Point2D(self.x, self.y)

    def __repr__(self) -> str:
        return f"Point3D({self.x}, {self.y}, {self.z})"


@dataclass
class Vector2D:
    """A 2D vector."""

    x: float
    y: float

    def __add__(self, other: Vector2D) -> Vector2D:
        """Add two vectors."""
        return Vector2D(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vector2D) -> Vector2D:
        """Subtract two vectors."""
        return Vector2D(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vector2D:
        """Scalar multiplication."""
        return Vector2D(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vector2D:
        """Scalar multiplication (reverse)."""
        return self.__mul__(scalar)

    def dot(self, other: Vector2D) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y

    def cross(self) -> float:
        """2D cross product (returns scalar)."""
        return self.x * self.y

    def magnitude(self) -> float:
        """Vector magnitude."""
        return math.sqrt(self.x * self.x + self.y * self.y)

    def normalize(self) -> Vector2D:
        """Return normalized vector."""
        mag = self.magnitude()
        if mag < 1e-10:
            return Vector2D(0.0, 0.0)
        return Vector2D(self.x / mag, self.y / mag)

    def perpendicular(self) -> Vector2D:
        """Return perpendicular vector (90 degrees counterclockwise)."""
        return Vector2D(-self.y, self.x)

    def __repr__(self) -> str:
        return f"Vector2D({self.x}, {self.y})"


@dataclass
class Vector3D:
    """A 3D vector."""

    x: float
    y: float
    z: float

    def __add__(self, other: Vector3D) -> Vector3D:
        """Add two vectors."""
        return Vector3D(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vector3D) -> Vector3D:
        """Subtract two vectors."""
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vector3D:
        """Scalar multiplication."""
        return Vector3D(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vector3D:
        """Scalar multiplication (reverse)."""
        return self.__mul__(scalar)

    def dot(self, other: Vector3D) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vector3D) -> Vector3D:
        """Cross product."""
        return Vector3D(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def magnitude(self) -> float:
        """Vector magnitude."""
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self) -> Vector3D:
        """Return normalized vector."""
        mag = self.magnitude()
        if mag < 1e-10:
            return Vector3D(0.0, 0.0, 0.0)
        return Vector3D(self.x / mag, self.y / mag, self.z / mag)

    def __repr__(self) -> str:
        return f"Vector3D({self.x}, {self.y}, {self.z})"


@dataclass
class Line:
    """A line segment."""

    start: Point2D
    end: Point2D

    def length(self) -> float:
        """Get line segment length."""
        return self.start.distance_to(self.end)

    def direction(self) -> Vector2D:
        """Get normalized direction vector."""
        return (self.end - self.start).normalize()

    def midpoint(self) -> Point2D:
        """Get midpoint of line."""
        return Point2D((self.start.x + self.end.x) / 2, (self.start.y + self.end.y) / 2)

    def __repr__(self) -> str:
        return f"Line({self.start}, {self.end})"


@dataclass
class Circle:
    """A circle."""

    center: Point2D
    radius: float

    def area(self) -> float:
        """Circle area."""
        return math.pi * self.radius * self.radius

    def circumference(self) -> float:
        """Circle circumference."""
        return 2 * math.pi * self.radius

    def point_at_angle(self, angle: float) -> Point2D:
        """Get point on circle at given angle (in radians)."""
        return Point2D(
            self.center.x + self.radius * math.cos(angle),
            self.center.y + self.radius * math.sin(angle),
        )

    def __repr__(self) -> str:
        return f"Circle(center={self.center}, radius={self.radius})"


@dataclass
class Arc:
    """A circular arc."""

    center: Point2D
    radius: float
    start_angle: float
    end_angle: float

    def length(self) -> float:
        """Arc length."""
        angle_span = abs(self.end_angle - self.start_angle)
        return self.radius * angle_span

    def start_point(self) -> Point2D:
        """Get start point of arc."""
        return Point2D(
            self.center.x + self.radius * math.cos(self.start_angle),
            self.center.y + self.radius * math.sin(self.start_angle),
        )

    def end_point(self) -> Point2D:
        """Get end point of arc."""
        return Point2D(
            self.center.x + self.radius * math.cos(self.end_angle),
            self.center.y + self.radius * math.sin(self.end_angle),
        )

    def __repr__(self) -> str:
        return f"Arc(center={self.center}, radius={self.radius})"


@dataclass
class Ellipse:
    """An ellipse."""

    center: Point2D
    major_axis: float
    minor_axis: float
    rotation: float = 0.0

    def area(self) -> float:
        """Ellipse area."""
        return math.pi * self.major_axis * self.minor_axis

    def __repr__(self) -> str:
        return f"Ellipse(center={self.center}, major={self.major_axis}, minor={self.minor_axis})"


@dataclass
class Polyline:
    """A polyline (sequence of connected line segments)."""

    points: list[Point2D] = field(default_factory=list)

    def length(self) -> float:
        """Total length of polyline."""
        total = 0.0
        for i in range(len(self.points) - 1):
            total += self.points[i].distance_to(self.points[i + 1])
        return total

    def add_point(self, point: Point2D) -> None:
        """Add a point to the polyline."""
        self.points.append(point)

    def __repr__(self) -> str:
        return f"Polyline({len(self.points)} points)"


@dataclass
class Polygon:
    """A closed polygon."""

    points: list[Point2D] = field(default_factory=list)

    def area(self) -> float:
        """Polygon area using Shoelace formula."""
        if len(self.points) < 3:
            return 0.0
        area = 0.0
        for i in range(len(self.points)):
            j = (i + 1) % len(self.points)
            area += self.points[i].x * self.points[j].y
            area -= self.points[j].x * self.points[i].y
        return abs(area) / 2.0

    def perimeter(self) -> float:
        """Polygon perimeter."""
        total = 0.0
        for i in range(len(self.points)):
            j = (i + 1) % len(self.points)
            total += self.points[i].distance_to(self.points[j])
        return total

    def centroid(self) -> Point2D:
        """Polygon centroid."""
        if len(self.points) == 0:
            return Point2D(0.0, 0.0)
        cx, cy = 0.0, 0.0
        for p in self.points:
            cx += p.x
            cy += p.y
        n = len(self.points)
        return Point2D(cx / n, cy / n)

    def is_convex(self) -> bool:
        """Check if polygon is convex."""
        if len(self.points) < 3:
            return False
        sign = None
        for i in range(len(self.points)):
            p1 = self.points[i]
            p2 = self.points[(i + 1) % len(self.points)]
            p3 = self.points[(i + 2) % len(self.points)]
            cross = (p2.x - p1.x) * (p3.y - p2.y) - (p2.y - p1.y) * (p3.x - p2.x)
            if cross != 0:
                if sign is None:
                    sign = cross > 0
                elif (cross > 0) != sign:
                    return False
        return True

    def __repr__(self) -> str:
        return f"Polygon({len(self.points)} points)"


@dataclass
class BezierCurve:
    """A Bezier curve defined by control points."""

    control_points: list[Point2D] = field(default_factory=list)
    degree: int = 0

    def __post_init__(self) -> None:
        """Validate degree."""
        self.degree = len(self.control_points) - 1

    def evaluate(self, t: float) -> Point2D:
        """Evaluate curve at parameter t (0 <= t <= 1)."""
        if t < 0 or t > 1:
            raise ValueError("Parameter t must be in [0, 1]")
        points = [p for p in self.control_points]
        for _ in range(self.degree):
            new_points = []
            for i in range(len(points) - 1):
                p = Point2D(
                    (1 - t) * points[i].x + t * points[i + 1].x,
                    (1 - t) * points[i].y + t * points[i + 1].y,
                )
                new_points.append(p)
            points = new_points
        return points[0]

    def __repr__(self) -> str:
        return f"BezierCurve(degree={self.degree})"


@dataclass
class BSplineCurve:
    """A B-spline curve."""

    control_points: list[Point2D] = field(default_factory=list)
    knot_vector: list[float] = field(default_factory=list)
    degree: int = 3

    def __repr__(self) -> str:
        return f"BSplineCurve(degree={self.degree}, cp_count={len(self.control_points)})"


@dataclass
class NURBSSurface:
    """A NURBS (Non-Uniform Rational B-Spline) surface."""

    control_points: list[list[Point3D]] = field(default_factory=list)
    weights: list[list[float]] = field(default_factory=list)
    knot_vector_u: list[float] = field(default_factory=list)
    knot_vector_v: list[float] = field(default_factory=list)
    degree_u: int = 3
    degree_v: int = 3

    def __repr__(self) -> str:
        return f"NURBSSurface(degree_u={self.degree_u}, degree_v={self.degree_v})"


@dataclass
class Vertex:
    """A vertex in a solid."""

    point: Point3D
    id: int = 0

    def __repr__(self) -> str:
        return f"Vertex({self.point})"


@dataclass
class Edge:
    """An edge in a solid."""

    start_vertex: Vertex
    end_vertex: Vertex
    id: int = 0

    def __repr__(self) -> str:
        return f"Edge({self.start_vertex.point}->{self.end_vertex.point})"


@dataclass
class Face:
    """A face in a solid."""

    vertices: list[Vertex] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    id: int = 0

    def area(self) -> float:
        """Approximate face area assuming planar."""
        if len(self.vertices) < 3:
            return 0.0
        v0 = self.vertices[0].point
        v1 = self.vertices[1].point
        v2 = self.vertices[2].point
        edge1 = v1 - v0
        edge2 = v2 - v0
        cross = edge1.cross(edge2)
        return cross.magnitude() / 2.0

    def normal(self) -> Vector3D:
        """Compute face normal."""
        if len(self.vertices) < 3:
            return Vector3D(0.0, 0.0, 1.0)
        v0 = self.vertices[0].point
        v1 = self.vertices[1].point
        v2 = self.vertices[2].point
        edge1 = v1 - v0
        edge2 = v2 - v0
        return edge1.cross(edge2).normalize()

    def __repr__(self) -> str:
        return f"Face({len(self.vertices)} vertices)"


@dataclass
class Solid:
    """A 3D solid."""

    vertices: list[Vertex] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)

    def surface_area(self) -> float:
        """Total surface area."""
        return sum(face.area() for face in self.faces)

    def __repr__(self) -> str:
        return f"Solid({len(self.vertices)} verts, {len(self.faces)} faces)"


@dataclass
class Layer:
    """A drawing layer."""

    name: str
    visible: bool = True
    locked: bool = False
    color: str = "0"

    def __repr__(self) -> str:
        return f"Layer('{self.name}')"


@dataclass
class Tolerance:
    """A tolerance specification."""

    value: float
    bilateral: bool = False
    upper: float | None = None
    lower: float | None = None

    def __repr__(self) -> str:
        if self.bilateral:
            return f"±{self.value}"
        elif self.upper is not None and self.lower is not None:
            return f"+{self.upper}/{self.lower}"
        else:
            return f"±{self.value}"


@dataclass
class Dimension:
    """A dimension annotation."""

    name: str
    value: float
    tolerance: Tolerance | None = None
    layer: Layer | None = None
    position: Point2D | None = None

    def __repr__(self) -> str:
        return f"Dimension('{self.name}': {self.value})"
