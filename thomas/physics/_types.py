"""
Core physics types: vectors, shapes, materials, and configuration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple


class Vec2(NamedTuple):
    """2D vector with full operator overloading."""

    x: float
    y: float

    def __add__(self, other: Vec2) -> Vec2:
        """Vector addition."""
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: Vec2) -> Vec2:
        """Vector subtraction."""
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> Vec2:
        """Scalar multiplication."""
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> Vec2:
        """Right scalar multiplication."""
        return Vec2(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar: float) -> Vec2:
        """Scalar division."""
        if scalar == 0:
            raise ValueError("Division by zero")
        return Vec2(self.x / scalar, self.y / scalar)

    def __neg__(self) -> Vec2:
        """Negation."""
        return Vec2(-self.x, -self.y)

    def __eq__(self, other: object) -> bool:
        """Equality with small epsilon tolerance."""
        if not isinstance(other, Vec2):
            return NotImplemented
        epsilon = 1e-9
        return abs(self.x - other.x) < epsilon and abs(self.y - other.y) < epsilon

    def dot(self, other: Vec2) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y

    def cross(self, other: Vec2) -> float:
        """2D cross product (returns scalar)."""
        return self.x * other.y - self.y * other.x

    def magnitude(self) -> float:
        """Vector magnitude (length)."""
        return math.sqrt(self.x * self.x + self.y * self.y)

    def magnitude_squared(self) -> float:
        """Squared magnitude (faster for comparisons)."""
        return self.x * self.x + self.y * self.y

    def normalize(self) -> Vec2:
        """Return normalized vector."""
        mag = self.magnitude()
        if mag < 1e-9:
            return Vec2(0, 0)
        return Vec2(self.x / mag, self.y / mag)

    def distance_to(self, other: Vec2) -> float:
        """Euclidean distance to another vector."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def distance_squared_to(self, other: Vec2) -> float:
        """Squared distance (faster for comparisons)."""
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def perpendicular(self) -> Vec2:
        """Return perpendicular vector (rotated 90 degrees)."""
        return Vec2(-self.y, self.x)

    def lerp(self, other: Vec2, t: float) -> Vec2:
        """Linear interpolation."""
        return Vec2(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
        )

    def clamp_magnitude(self, max_magnitude: float) -> Vec2:
        """Clamp magnitude to maximum."""
        mag = self.magnitude()
        if mag > max_magnitude:
            return self.normalize() * max_magnitude
        return self


class Vec3(NamedTuple):
    """3D vector with full operator overloading."""

    x: float
    y: float
    z: float

    def __add__(self, other: Vec3) -> Vec3:
        """Vector addition."""
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        """Vector subtraction."""
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        """Scalar multiplication."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vec3:
        """Right scalar multiplication."""
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __truediv__(self, scalar: float) -> Vec3:
        """Scalar division."""
        if scalar == 0:
            raise ValueError("Division by zero")
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def __neg__(self) -> Vec3:
        """Negation."""
        return Vec3(-self.x, -self.y, -self.z)

    def __eq__(self, other: object) -> bool:
        """Equality with small epsilon tolerance."""
        if not isinstance(other, Vec3):
            return NotImplemented
        epsilon = 1e-9
        return abs(self.x - other.x) < epsilon and abs(self.y - other.y) < epsilon and abs(self.z - other.z) < epsilon

    def dot(self, other: Vec3) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        """3D cross product."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def magnitude(self) -> float:
        """Vector magnitude (length)."""
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def magnitude_squared(self) -> float:
        """Squared magnitude (faster for comparisons)."""
        return self.x * self.x + self.y * self.y + self.z * self.z

    def normalize(self) -> Vec3:
        """Return normalized vector."""
        mag = self.magnitude()
        if mag < 1e-9:
            return Vec3(0, 0, 0)
        return Vec3(self.x / mag, self.y / mag, self.z / mag)

    def distance_to(self, other: Vec3) -> float:
        """Euclidean distance to another vector."""
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def distance_squared_to(self, other: Vec3) -> float:
        """Squared distance (faster for comparisons)."""
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return dx * dx + dy * dy + dz * dz

    def lerp(self, other: Vec3, t: float) -> Vec3:
        """Linear interpolation."""
        return Vec3(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
            self.z + (other.z - self.z) * t,
        )

    def clamp_magnitude(self, max_magnitude: float) -> Vec3:
        """Clamp magnitude to maximum."""
        mag = self.magnitude()
        if mag > max_magnitude:
            return self.normalize() * max_magnitude
        return self


@dataclass
class AABB:
    """Axis-Aligned Bounding Box."""

    min: Vec3
    max: Vec3

    def center(self) -> Vec3:
        """Center of AABB."""
        return (self.min + self.max) * 0.5

    def extents(self) -> Vec3:
        """Half-size of AABB."""
        return (self.max - self.min) * 0.5

    def size(self) -> Vec3:
        """Full size of AABB."""
        return self.max - self.min

    def contains_point(self, point: Vec3) -> bool:
        """Check if point is inside AABB."""
        return (
            self.min.x <= point.x <= self.max.x
            and self.min.y <= point.y <= self.max.y
            and self.min.z <= point.z <= self.max.z
        )

    def expand(self, point: Vec3) -> AABB:
        """Expand AABB to contain point."""
        return AABB(
            Vec3(
                min(self.min.x, point.x),
                min(self.min.y, point.y),
                min(self.min.z, point.z),
            ),
            Vec3(
                max(self.max.x, point.x),
                max(self.max.y, point.y),
                max(self.max.z, point.z),
            ),
        )

    def expand_by_aabb(self, other: AABB) -> AABB:
        """Expand AABB to contain another AABB."""
        return AABB(
            Vec3(
                min(self.min.x, other.min.x),
                min(self.min.y, other.min.y),
                min(self.min.z, other.min.z),
            ),
            Vec3(
                max(self.max.x, other.max.x),
                max(self.max.y, other.max.y),
                max(self.max.z, other.max.z),
            ),
        )

    def expand_by_margin(self, margin: float) -> AABB:
        """Expand AABB by margin in all directions."""
        m = Vec3(margin, margin, margin)
        return AABB(self.min - m, self.max + m)

    def surface_area(self) -> float:
        """Surface area of AABB."""
        size = self.size()
        return 2 * (size.x * size.y + size.y * size.z + size.z * size.x)

    def volume(self) -> float:
        """Volume of AABB."""
        size = self.size()
        return size.x * size.y * size.z


@dataclass
class Sphere:
    """Sphere shape (position and radius)."""

    center: Vec3
    radius: float

    def contains_point(self, point: Vec3) -> bool:
        """Check if point is inside sphere."""
        return self.center.distance_to(point) <= self.radius

    def get_aabb(self) -> AABB:
        """Get bounding box of sphere."""
        r = Vec3(self.radius, self.radius, self.radius)
        return AABB(self.center - r, self.center + r)


@dataclass
class Plane:
    """Plane defined by normal and distance from origin."""

    normal: Vec3  # Must be normalized
    d: float  # Distance from origin

    def distance_to_point(self, point: Vec3) -> float:
        """Signed distance from point to plane."""
        return self.normal.dot(point) + self.d

    def closest_point_on_plane(self, point: Vec3) -> Vec3:
        """Get closest point on plane to given point."""
        dist = self.distance_to_point(point)
        return point - self.normal * dist


@dataclass
class Ray:
    """Ray defined by origin and direction."""

    origin: Vec3
    direction: Vec3  # Should be normalized

    def at(self, t: float) -> Vec3:
        """Get point at parameter t along ray."""
        return self.origin + self.direction * t

    def normalize_direction(self) -> Ray:
        """Return ray with normalized direction."""
        return Ray(self.origin, self.direction.normalize())


class RigidBodyType(Enum):
    """Type of rigid body."""

    STATIC = 0  # Does not move
    DYNAMIC = 1  # Affected by forces and collisions
    KINEMATIC = 2  # Moves but not affected by forces


@dataclass
class Material:
    """Material properties for physics."""

    friction: float = 0.5  # Coefficient of friction [0, 1]
    restitution: float = 0.3  # Bounciness [0, 1]
    density: float = 1000.0  # kg/m^3

    def __post_init__(self) -> None:
        """Validate material properties."""
        if not 0 <= self.friction <= 1:
            raise ValueError("Friction must be in [0, 1]")
        if not 0 <= self.restitution <= 1:
            raise ValueError("Restitution must be in [0, 1]")
        if self.density <= 0:
            raise ValueError("Density must be positive")


@dataclass
class PhysicsConfig:
    """Global physics configuration."""

    gravity: Vec3 = Vec3(0, -9.81, 0)
    fixed_timestep: float = 0.016  # 60 Hz
    max_frame_time: float = 0.033  # 30 Hz minimum
    velocity_damping: float = 0.99  # Air resistance
    angular_damping: float = 0.99
    sleep_velocity_threshold: float = 0.1
    sleep_angular_velocity_threshold: float = 0.1
    sleep_time_threshold: float = 1.0
    constraint_iterations: int = 4
    contact_slop: float = 0.01  # Penetration tolerance
    baumgarte_bias: float = 0.2  # For position correction
    warm_start_factor: float = 0.8

    def validate(self) -> None:
        """Validate configuration."""
        if self.fixed_timestep <= 0:
            raise ValueError("Timestep must be positive")
        if not 0 <= self.velocity_damping <= 1:
            raise ValueError("Damping must be in [0, 1]")
        if self.sleep_velocity_threshold < 0:
            raise ValueError("Sleep threshold must be non-negative")
