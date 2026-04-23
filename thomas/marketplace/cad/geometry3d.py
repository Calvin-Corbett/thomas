"""
3D geometry operations and algorithms.

Includes plane-line/plane intersection, distance calculations, 3D transformations
using Rodrigues' formula, bounding boxes, and volume/surface area calculations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ._exceptions import GeometryError
from ._types import Face, Point3D, Solid, Vector3D

EPSILON = 1e-10


@dataclass
class Plane:
    """A plane defined by normal vector and point."""

    normal: Vector3D
    point: Point3D

    def __post_init__(self) -> None:
        """Normalize the normal vector."""
        self.normal = self.normal.normalize()

    @classmethod
    def from_three_points(cls, p1: Point3D, p2: Point3D, p3: Point3D) -> Plane:
        """Create plane from three non-collinear points."""
        edge1 = p2 - p1
        edge2 = p3 - p1
        normal = edge1.cross(edge2)

        if normal.magnitude() < EPSILON:
            raise GeometryError("Points are collinear, cannot define plane")

        return cls(normal, p1)

    def distance_to_point(self, point: Point3D) -> float:
        """Compute signed distance from point to plane."""
        vec = point - self.point
        return vec.dot(self.normal)

    def project_point(self, point: Point3D) -> Point3D:
        """Project point onto plane."""
        dist = self.distance_to_point(point)
        return point + self.normal * (-dist)


def plane_line_intersection(plane: Plane, line_start: Point3D, line_end: Point3D) -> Point3D | None:
    """
    Find intersection of line with plane.

    Solves parametric line equation against plane equation.

    Args:
        plane: Plane
        line_start: Line start point
        line_end: Line end point

    Returns:
        Intersection point or None if parallel
    """
    direction = line_end - line_start
    denom = direction.dot(plane.normal)

    if abs(denom) < EPSILON:
        return None

    t = (plane.point - line_start).dot(plane.normal) / denom

    if 0 <= t <= 1:
        return line_start + direction * t

    return None


def plane_plane_intersection(plane1: Plane, plane2: Plane) -> tuple[Point3D, Vector3D] | None:
    """
    Find intersection of two planes.

    Returns a line (point + direction) or None if parallel.

    Args:
        plane1: First plane
        plane2: Second plane

    Returns:
        Tuple of (point_on_line, direction) or None if parallel
    """
    direction = plane1.normal.cross(plane2.normal)

    if direction.magnitude() < EPSILON:
        return None

    direction = direction.normalize()

    denom = plane1.normal.dot(plane1.normal) * plane2.normal.dot(plane2.normal) - plane1.normal.dot(plane2.normal) ** 2

    if abs(denom) < EPSILON:
        return None

    t1 = (
        plane1.distance_to_point(plane2.point) * plane2.normal.dot(plane2.normal)
        - plane2.distance_to_point(plane1.point) * plane1.normal.dot(plane2.normal)
    ) / denom

    point = plane1.point + plane1.normal * (-t1)

    return (point, direction)


def point_plane_distance(point: Point3D, plane: Plane) -> float:
    """Compute distance from point to plane."""
    vec = point - plane.point
    return abs(vec.dot(plane.normal))


@dataclass
class Matrix3x3:
    """A 3x3 matrix for 3D transformations."""

    m: list[list[float]]

    def __init__(self, m: list[list[float]] | None = None) -> None:
        """Initialize matrix (identity if not provided)."""
        if m is None:
            self.m = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        else:
            self.m = [row[:] for row in m]

    @classmethod
    def identity(cls) -> Matrix3x3:
        """Create identity matrix."""
        return cls()

    @classmethod
    def rotation_x(cls, angle: float) -> Matrix3x3:
        """Create rotation matrix around X axis."""
        c, s = math.cos(angle), math.sin(angle)
        return cls([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])

    @classmethod
    def rotation_y(cls, angle: float) -> Matrix3x3:
        """Create rotation matrix around Y axis."""
        c, s = math.cos(angle), math.sin(angle)
        return cls([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])

    @classmethod
    def rotation_z(cls, angle: float) -> Matrix3x3:
        """Create rotation matrix around Z axis."""
        c, s = math.cos(angle), math.sin(angle)
        return cls([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])

    @classmethod
    def scale(cls, sx: float, sy: float, sz: float) -> Matrix3x3:
        """Create scale matrix."""
        return cls([[sx, 0.0, 0.0], [0.0, sy, 0.0], [0.0, 0.0, sz]])

    def multiply(self, other: Matrix3x3) -> Matrix3x3:
        """Multiply two matrices."""
        result = [[0.0] * 3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                for k in range(3):
                    result[i][j] += self.m[i][k] * other.m[k][j]
        return Matrix3x3(result)

    def transform_vector(self, v: Vector3D) -> Vector3D:
        """Apply transformation to vector."""
        x = self.m[0][0] * v.x + self.m[0][1] * v.y + self.m[0][2] * v.z
        y = self.m[1][0] * v.x + self.m[1][1] * v.y + self.m[1][2] * v.z
        z = self.m[2][0] * v.x + self.m[2][1] * v.y + self.m[2][2] * v.z
        return Vector3D(x, y, z)


def rotate_around_axis(point: Point3D, axis: Vector3D, angle: float, center: Point3D) -> Point3D:
    """
    Rotate point around arbitrary axis using Rodrigues' formula.

    Args:
        point: Point to rotate
        axis: Rotation axis (should be normalized)
        angle: Rotation angle in radians
        center: Rotation center

    Returns:
        Rotated point
    """
    axis = axis.normalize()

    v = point - center

    cos_a = math.cos(angle)
    sin_a = math.sin(angle)

    rotated = v * cos_a + axis.cross(v) * sin_a + axis * axis.dot(v) * (1 - cos_a)

    return center + rotated


def translate(point: Point3D, offset: Vector3D) -> Point3D:
    """Translate a point."""
    return point + offset


def scale_point(point: Point3D, factor: float, center: Point3D) -> Point3D:
    """Scale point relative to center."""
    return center + (point - center) * factor


def mirror_point(point: Point3D, plane: Plane) -> Point3D:
    """Mirror point across plane."""
    dist = plane.distance_to_point(point)
    return point + plane.normal * (-2 * dist)


@dataclass
class BoundingBox:
    """Axis-aligned bounding box."""

    min_point: Point3D
    max_point: Point3D

    def contains(self, point: Point3D) -> bool:
        """Check if point is in bounding box."""
        return (
            self.min_point.x <= point.x <= self.max_point.x
            and self.min_point.y <= point.y <= self.max_point.y
            and self.min_point.z <= point.z <= self.max_point.z
        )

    def intersects(self, other: BoundingBox) -> bool:
        """Check if two boxes intersect."""
        return (
            self.min_point.x <= other.max_point.x
            and self.max_point.x >= other.min_point.x
            and self.min_point.y <= other.max_point.y
            and self.max_point.y >= other.min_point.y
            and self.min_point.z <= other.max_point.z
            and self.max_point.z >= other.min_point.z
        )

    def merge(self, other: BoundingBox) -> BoundingBox:
        """Merge two bounding boxes."""
        return BoundingBox(
            Point3D(
                min(self.min_point.x, other.min_point.x),
                min(self.min_point.y, other.min_point.y),
                min(self.min_point.z, other.min_point.z),
            ),
            Point3D(
                max(self.max_point.x, other.max_point.x),
                max(self.max_point.y, other.max_point.y),
                max(self.max_point.z, other.max_point.z),
            ),
        )

    def volume(self) -> float:
        """Get bounding box volume."""
        dx = self.max_point.x - self.min_point.x
        dy = self.max_point.y - self.min_point.y
        dz = self.max_point.z - self.min_point.z
        return dx * dy * dz


def compute_bounding_box(points: list[Point3D]) -> BoundingBox:
    """Compute bounding box for points."""
    if not points:
        return BoundingBox(Point3D(0, 0, 0), Point3D(0, 0, 0))

    xs = [p.x for p in points]
    ys = [p.y for p in points]
    zs = [p.z for p in points]

    return BoundingBox(Point3D(min(xs), min(ys), min(zs)), Point3D(max(xs), max(ys), max(zs)))


def solid_volume(solid: Solid) -> float:
    """
    Compute solid volume using divergence theorem.

    Volume = (1/6) * sum of signed tetrahedron volumes with origin.

    Args:
        solid: Solid object

    Returns:
        Volume
    """
    volume = 0.0

    for face in solid.faces:
        if len(face.vertices) < 3:
            continue

        v0 = face.vertices[0].point
        for i in range(1, len(face.vertices) - 1):
            v1 = face.vertices[i].point
            v2 = face.vertices[i + 1].point

            edge1 = v1 - v0
            edge2 = v2 - v0

            normal = edge1.cross(edge2)

            volume += v0.dot(normal)

    return abs(volume) / 6.0


def solid_surface_area(solid: Solid) -> float:
    """
    Compute solid surface area.

    Args:
        solid: Solid object

    Returns:
        Total surface area
    """
    return sum(face.area() for face in solid.faces)


def face_centroid(face: Face) -> Point3D:
    """Compute face centroid."""
    if not face.vertices:
        return Point3D(0, 0, 0)

    xs = sum(v.point.x for v in face.vertices)
    ys = sum(v.point.y for v in face.vertices)
    zs = sum(v.point.z for v in face.vertices)
    n = len(face.vertices)

    return Point3D(xs / n, ys / n, zs / n)


def solid_centroid(solid: Solid) -> Point3D:
    """Compute solid centroid."""
    if not solid.vertices:
        return Point3D(0, 0, 0)

    xs = sum(v.point.x for v in solid.vertices)
    ys = sum(v.point.y for v in solid.vertices)
    zs = sum(v.point.z for v in solid.vertices)
    n = len(solid.vertices)

    return Point3D(xs / n, ys / n, zs / n)


def line_to_line_distance(p1: Point3D, d1: Vector3D, p2: Point3D, d2: Vector3D) -> float:
    """
    Compute minimum distance between two lines in 3D.

    Args:
        p1: Point on first line
        d1: Direction of first line
        p2: Point on second line
        d2: Direction of second line

    Returns:
        Minimum distance
    """
    d1 = d1.normalize()
    d2 = d2.normalize()

    w = p2 - p1

    a = d1.dot(d1)
    b = d1.dot(d2)
    c = d2.dot(d2)
    d = d1.dot(w)
    e = d2.dot(w)

    denom = a * c - b * b

    if abs(denom) < EPSILON:
        return w.magnitude()

    s = (b * e - c * d) / denom
    t = (a * e - b * d) / denom

    closest1 = p1 + d1 * s
    closest2 = p2 + d2 * t

    return closest1.distance_to(closest2)


def compute_vertex_normal(vertex: Point3D, adjacent_faces: list[Face]) -> Vector3D:
    """
    Compute vertex normal as average of adjacent face normals.

    Args:
        vertex: Vertex point
        adjacent_faces: Adjacent faces

    Returns:
        Vertex normal
    """
    if not adjacent_faces:
        return Vector3D(0, 0, 1)

    normal = Vector3D(0, 0, 0)
    for face in adjacent_faces:
        normal = normal + face.normal()

    return normal.normalize()


def triangle_area_3d(p1: Point3D, p2: Point3D, p3: Point3D) -> float:
    """Compute area of triangle in 3D."""
    edge1 = p2 - p1
    edge2 = p3 - p1
    cross = edge1.cross(edge2)
    return cross.magnitude() / 2.0
