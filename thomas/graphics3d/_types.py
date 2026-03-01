"""
Core type definitions for 3D graphics engine.

Provides fundamental data structures:
- Vectors: Vec2, Vec3, Vec4
- Matrices: Mat3, Mat4
- Quaternion: Quaternion
- Geometric primitives: Ray, AABB, Sphere, Plane, Triangle
- Graphics objects: Vertex, Mesh, Material, Color, Light, Camera, Viewport, FrameBuffer, Texture, UV
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Vec2:
    """2D vector with x, y components."""

    x: float = 0.0
    y: float = 0.0

    def __add__(self, other: Vec2) -> Vec2:
        """Add two vectors."""
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        """Subtract two vectors."""
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        """Multiply vector by scalar."""
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vec2:
        """Multiply scalar by vector."""
        return Vec2(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar: float) -> Vec2:
        """Divide vector by scalar."""
        if scalar == 0:
            raise ValueError("Cannot divide by zero")
        return Vec2(self.x / scalar, self.y / scalar)

    def __neg__(self) -> Vec2:
        """Negate vector."""
        return Vec2(-self.x, -self.y)

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Vec2):
            return False
        epsilon = 1e-9
        return abs(self.x - other.x) < epsilon and abs(self.y - other.y) < epsilon

    def dot(self, other: Vec2) -> float:
        """Compute dot product."""
        return self.x * other.x + self.y * other.y

    def length(self) -> float:
        """Compute vector length."""
        return math.sqrt(self.x * self.x + self.y * self.y)

    def normalize(self) -> Vec2:
        """Return normalized vector."""
        length = self.length()
        if length < 1e-9:
            raise ValueError("Cannot normalize zero vector")
        return Vec2(self.x / length, self.y / length)

    def to_tuple(self) -> tuple[float, float]:
        """Convert to tuple."""
        return (self.x, self.y)


@dataclass
class Vec3:
    """3D vector with x, y, z components."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __add__(self, other: Vec3) -> Vec3:
        """Add two vectors."""
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        """Subtract two vectors."""
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        """Multiply vector by scalar."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vec3:
        """Multiply scalar by vector."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __truediv__(self, scalar: float) -> Vec3:
        """Divide vector by scalar."""
        if scalar == 0:
            raise ValueError("Cannot divide by zero")
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __neg__(self) -> Vec3:
        """Negate vector."""
        return Vec3(-self.x, -self.y, -self.z)

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Vec3):
            return False
        epsilon = 1e-9
        return abs(self.x - other.x) < epsilon and abs(self.y - other.y) < epsilon and abs(self.z - other.z) < epsilon

    def dot(self, other: Vec3) -> float:
        """Compute dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        """Compute cross product."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        """Compute vector length."""
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self) -> Vec3:
        """Return normalized vector."""
        length = self.length()
        if length < 1e-9:
            raise ValueError("Cannot normalize zero vector")
        return Vec3(self.x / length, self.y / length, self.z / length)

    def lerp(self, other: Vec3, t: float) -> Vec3:
        """Linear interpolation with another vector."""
        return self * (1 - t) + other * t

    def to_tuple(self) -> tuple[float, float, float]:
        """Convert to tuple."""
        return (self.x, self.y, self.z)


@dataclass
class Vec4:
    """4D vector (homogeneous coordinates) with x, y, z, w components."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    def __add__(self, other: Vec4) -> Vec4:
        """Add two vectors."""
        return Vec4(self.x + other.x, self.y + other.y, self.z + other.z, self.w + other.w)

    def __sub__(self, other: Vec4) -> Vec4:
        """Subtract two vectors."""
        return Vec4(self.x - other.x, self.y - other.y, self.z - other.z, self.w - other.w)

    def __mul__(self, scalar: float) -> Vec4:
        """Multiply vector by scalar."""
        return Vec4(self.x * scalar, self.y * scalar, self.z * scalar, self.w * scalar)

    def __rmul__(self, scalar: float) -> Vec4:
        """Multiply scalar by vector."""
        return Vec4(self.x * scalar, self.y * scalar, self.z * scalar, self.w * scalar)

    def __truediv__(self, scalar: float) -> Vec4:
        """Divide vector by scalar."""
        if scalar == 0:
            raise ValueError("Cannot divide by zero")
        return Vec4(self.x / scalar, self.y / scalar, self.z / scalar, self.w / scalar)

    def __neg__(self) -> Vec4:
        """Negate vector."""
        return Vec4(-self.x, -self.y, -self.z, -self.w)

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Vec4):
            return False
        epsilon = 1e-9
        return (
            abs(self.x - other.x) < epsilon
            and abs(self.y - other.y) < epsilon
            and abs(self.z - other.z) < epsilon
            and abs(self.w - other.w) < epsilon
        )

    def dot(self, other: Vec4) -> float:
        """Compute dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z + self.w * other.w

    def length(self) -> float:
        """Compute vector length."""
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w)

    def normalize(self) -> Vec4:
        """Return normalized vector."""
        length = self.length()
        if length < 1e-9:
            raise ValueError("Cannot normalize zero vector")
        return Vec4(self.x / length, self.y / length, self.z / length, self.w / length)

    def to_tuple(self) -> tuple[float, float, float, float]:
        """Convert to tuple."""
        return (self.x, self.y, self.z, self.w)

    def to_vec3(self) -> Vec3:
        """Convert to Vec3 by perspective divide."""
        if abs(self.w) < 1e-9:
            return Vec3(self.x, self.y, self.z)
        return Vec3(self.x / self.w, self.y / self.w, self.z / self.w)


@dataclass
class Mat3:
    """3x3 matrix stored in row-major order."""

    data: list[list[float]] = field(default_factory=lambda: [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def __getitem__(self, key: tuple[int, int]) -> float:
        """Get element at (row, col)."""
        row, col = key
        return self.data[row][col]

    def __setitem__(self, key: tuple[int, int], value: float) -> None:
        """Set element at (row, col)."""
        row, col = key
        self.data[row][col] = value

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Mat3):
            return False
        epsilon = 1e-9
        for i in range(3):
            for j in range(3):
                if abs(self.data[i][j] - other.data[i][j]) > epsilon:
                    return False
        return True

    @staticmethod
    def identity() -> Mat3:
        """Create identity matrix."""
        return Mat3([[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def transpose(self) -> Mat3:
        """Return transposed matrix."""
        return Mat3([[self.data[j][i] for j in range(3)] for i in range(3)])

    def determinant(self) -> float:
        """Compute determinant."""
        a = self.data[0][0] * (self.data[1][1] * self.data[2][2] - self.data[1][2] * self.data[2][1])
        b = self.data[0][1] * (self.data[1][0] * self.data[2][2] - self.data[1][2] * self.data[2][0])
        c = self.data[0][2] * (self.data[1][0] * self.data[2][1] - self.data[1][1] * self.data[2][0])
        return a - b + c


@dataclass
class Mat4:
    """4x4 matrix stored in row-major order."""

    data: list[list[float]] = field(
        default_factory=lambda: [
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
    )

    def __getitem__(self, key: tuple[int, int]) -> float:
        """Get element at (row, col)."""
        row, col = key
        return self.data[row][col]

    def __setitem__(self, key: tuple[int, int], value: float) -> None:
        """Set element at (row, col)."""
        row, col = key
        self.data[row][col] = value

    def __mul__(self, other: Mat4 | Vec4) -> Mat4 | Vec4:
        """Multiply matrix by matrix or vector."""
        if isinstance(other, Mat4):
            result = [
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ]
            for i in range(4):
                for j in range(4):
                    for k in range(4):
                        result[i][j] += self.data[i][k] * other.data[k][j]
            return Mat4(result)
        elif isinstance(other, Vec4):
            result = [0, 0, 0, 0]
            for i in range(4):
                for j in range(4):
                    result[i] += self.data[i][j] * other.to_tuple()[j]
            return Vec4(*result)
        else:
            return NotImplemented

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Mat4):
            return False
        epsilon = 1e-9
        for i in range(4):
            for j in range(4):
                if abs(self.data[i][j] - other.data[i][j]) > epsilon:
                    return False
        return True

    @staticmethod
    def identity() -> Mat4:
        """Create identity matrix."""
        return Mat4(
            [
                [1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ]
        )

    def transpose(self) -> Mat4:
        """Return transposed matrix."""
        result = [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        for i in range(4):
            for j in range(4):
                result[j][i] = self.data[i][j]
        return Mat4(result)

    def determinant(self) -> float:
        """Compute determinant via cofactor expansion."""
        result = 0.0
        for j in range(4):
            minor = self._get_minor(0, j)
            cofactor = ((-1) ** j) * minor.determinant()
            result += self.data[0][j] * cofactor
        return result

    def _get_minor(self, row: int, col: int) -> Mat3:
        """Extract 3x3 minor by removing row and col."""
        minor_data = []
        for i in range(4):
            if i == row:
                continue
            minor_row = []
            for j in range(4):
                if j == col:
                    continue
                minor_row.append(self.data[i][j])
            minor_data.append(minor_row)
        return Mat3(minor_data)

    def inverse(self) -> Mat4:
        """Compute inverse via cofactor expansion."""
        det = self.determinant()
        if abs(det) < 1e-9:
            raise ValueError("Matrix is singular, cannot invert")

        adj = self._adjugate()
        result = [[adj.data[i][j] / det for j in range(4)] for i in range(4)]
        return Mat4(result)

    def _adjugate(self) -> Mat4:
        """Compute adjugate (transpose of cofactor matrix)."""
        cofactors = [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        for i in range(4):
            for j in range(4):
                minor = self._get_minor(i, j)
                cofactors[i][j] = ((-1) ** (i + j)) * minor.determinant()

        result = [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]
        for i in range(4):
            for j in range(4):
                result[j][i] = cofactors[i][j]
        return Mat4(result)


@dataclass
class Quaternion:
    """Unit quaternion for rotations: q = w + xi + yj + zk."""

    w: float = 1.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __mul__(self, other: Quaternion) -> Quaternion:
        """Quaternion multiplication (Hamilton product)."""
        a, b, c, d = self.w, self.x, self.y, self.z
        e, f, g, h = other.w, other.x, other.y, other.z

        return Quaternion(
            a * e - b * f - c * g - d * h,
            a * f + b * e + c * h - d * g,
            a * g - b * h + c * e + d * f,
            a * h + b * g - c * f + d * e,
        )

    def __eq__(self, other: Any) -> bool:
        """Check equality with epsilon tolerance."""
        if not isinstance(other, Quaternion):
            return False
        epsilon = 1e-9
        return (
            abs(self.w - other.w) < epsilon
            and abs(self.x - other.x) < epsilon
            and abs(self.y - other.y) < epsilon
            and abs(self.z - other.z) < epsilon
        )

    def length(self) -> float:
        """Compute quaternion magnitude."""
        return math.sqrt(self.w * self.w + self.x * self.x + self.y * self.y + self.z * self.z)

    def normalize(self) -> Quaternion:
        """Return normalized quaternion."""
        length = self.length()
        if length < 1e-9:
            raise ValueError("Cannot normalize zero quaternion")
        return Quaternion(self.w / length, self.x / length, self.y / length, self.z / length)

    def conjugate(self) -> Quaternion:
        """Return conjugate."""
        return Quaternion(self.w, -self.x, -self.y, -self.z)

    def to_rotation_matrix(self) -> Mat4:
        """Convert to 4x4 rotation matrix."""
        q = self.normalize()
        w, x, y, z = q.w, q.x, q.y, q.z

        return Mat4(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 0],
                [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 0],
                [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y), 0],
                [0, 0, 0, 1],
            ]
        )

    @staticmethod
    def from_axis_angle(axis: Vec3, angle: float) -> Quaternion:
        """Create quaternion from axis-angle representation."""
        normalized_axis = axis.normalize()
        half_angle = angle / 2
        sin_half = math.sin(half_angle)
        return Quaternion(
            math.cos(half_angle),
            normalized_axis.x * sin_half,
            normalized_axis.y * sin_half,
            normalized_axis.z * sin_half,
        )

    @staticmethod
    def from_euler(pitch: float, yaw: float, roll: float) -> Quaternion:
        """Create quaternion from Euler angles (radians)."""
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        return Quaternion(
            cy * cp * cr + sy * sp * sr,
            cy * sp * cr + sy * cp * sr,
            sy * cp * cr - cy * sp * sr,
            cy * cp * sr - sy * sp * cr,
        )

    def slerp(self, other: Quaternion, t: float) -> Quaternion:
        """Spherical linear interpolation."""
        a, b = self.normalize(), other.normalize()
        dot_product = a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z

        if dot_product < 0:
            b = Quaternion(-b.w, -b.x, -b.y, -b.z)
            dot_product = -dot_product

        if dot_product > 0.9995:
            result = Quaternion(
                a.w + t * (b.w - a.w),
                a.x + t * (b.x - a.x),
                a.y + t * (b.y - a.y),
                a.z + t * (b.z - a.z),
            )
            return result.normalize()

        theta = math.acos(dot_product)
        sin_theta = math.sin(theta)
        w1 = math.sin((1 - t) * theta) / sin_theta
        w2 = math.sin(t * theta) / sin_theta

        return Quaternion(
            w1 * a.w + w2 * b.w,
            w1 * a.x + w2 * b.x,
            w1 * a.y + w2 * b.y,
            w1 * a.z + w2 * b.z,
        )

    def nlerp(self, other: Quaternion, t: float) -> Quaternion:
        """Normalized linear interpolation (faster than slerp)."""
        a, b = self.normalize(), other.normalize()
        dot_product = a.w * b.w + a.x * b.x + a.y * b.y + a.z * b.z

        if dot_product < 0:
            b = Quaternion(-b.w, -b.x, -b.y, -b.z)

        result = Quaternion(
            a.w + t * (b.w - a.w),
            a.x + t * (b.x - a.x),
            a.y + t * (b.y - a.y),
            a.z + t * (b.z - a.z),
        )
        return result.normalize()


@dataclass
class Ray:
    """Ray: origin + direction * t."""

    origin: Vec3
    direction: Vec3

    def at(self, t: float) -> Vec3:
        """Get point on ray at parameter t."""
        return self.origin + self.direction * t


@dataclass
class AABB:
    """Axis-aligned bounding box."""

    min: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    max: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))

    def center(self) -> Vec3:
        """Get center point."""
        return (self.min + self.max) * 0.5

    def extent(self) -> Vec3:
        """Get half-extents."""
        return (self.max - self.min) * 0.5

    def contains_point(self, point: Vec3) -> bool:
        """Check if point is inside AABB."""
        return (
            self.min.x <= point.x <= self.max.x
            and self.min.y <= point.y <= self.max.y
            and self.min.z <= point.z <= self.max.z
        )


@dataclass
class Sphere:
    """Bounding sphere."""

    center: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    radius: float = 0.0

    def contains_point(self, point: Vec3) -> bool:
        """Check if point is inside sphere."""
        dist = (point - self.center).length()
        return dist <= self.radius


@dataclass
class Plane:
    """Plane defined by normal and distance: normal . point = distance."""

    normal: Vec3 = field(default_factory=lambda: Vec3(0, 1, 0))
    distance: float = 0.0

    def signed_distance_to_point(self, point: Vec3) -> float:
        """Compute signed distance from point to plane."""
        return self.normal.dot(point) - self.distance


@dataclass
class Triangle:
    """Triangle with three vertices."""

    v0: Vec3
    v1: Vec3
    v2: Vec3

    def normal(self) -> Vec3:
        """Compute face normal."""
        edge1 = self.v1 - self.v0
        edge2 = self.v2 - self.v0
        return edge1.cross(edge2).normalize()

    def area(self) -> float:
        """Compute triangle area."""
        edge1 = self.v1 - self.v0
        edge2 = self.v2 - self.v0
        return edge1.cross(edge2).length() * 0.5


@dataclass
class UV:
    """Texture coordinates."""

    u: float = 0.0
    v: float = 0.0

    def __add__(self, other: UV) -> UV:
        """Add UV coordinates."""
        return UV(self.u + other.u, self.v + other.v)

    def __mul__(self, scalar: float) -> UV:
        """Multiply by scalar."""
        return UV(self.u * scalar, self.v * scalar)

    def __rmul__(self, scalar: float) -> UV:
        """Multiply by scalar."""
        return UV(self.u * scalar, self.v * scalar)

    def lerp(self, other: UV, t: float) -> UV:
        """Linear interpolation."""
        return UV(self.u + t * (other.u - self.u), self.v + t * (other.v - self.v))


_GRAPHICS_TYPES_EXPORTS = {
    "Vertex",
    "Mesh",
    "Color",
    "LightType",
    "Light",
    "Material",
    "Camera",
    "Viewport",
    "Texture",
    "FrameBuffer",
}


def __getattr__(name: str) -> Any:
    """Lazily expose graphics-facing types without import cycles."""
    if name in _GRAPHICS_TYPES_EXPORTS:
        from thomas.graphics3d import _graphics_types as _gfx_types

        return getattr(_gfx_types, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
