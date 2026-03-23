"""
Type definitions and data structures for game AI systems.

Provides core types used throughout the game AI module including vectors,
entities, AI state enumerations, and shared data structures.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass
class Vec2:
    """2D vector for positions and velocities.

    Supports common vector operations including normalization, magnitude,
    dot/cross products, and distance calculations.
    """

    x: float
    y: float

    def __add__(self, other: "Vec2") -> "Vec2":
        """Add two vectors."""
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vec2") -> "Vec2":
        """Subtract two vectors."""
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vec2":
        """Multiply vector by scalar."""
        return Vec2(self.x * scalar, self.y * scalar)

    def __rmul__(self, scalar: float) -> "Vec2":
        """Right multiply vector by scalar."""
        return self * scalar

    def __truediv__(self, scalar: float) -> "Vec2":
        """Divide vector by scalar."""
        if scalar == 0:
            raise ValueError("Cannot divide by zero")
        return Vec2(self.x / scalar, self.y / scalar)

    def __eq__(self, other: object) -> bool:
        """Check vector equality with small epsilon."""
        if not isinstance(other, Vec2):
            return NotImplemented
        epsilon = 1e-6
        return abs(self.x - other.x) < epsilon and abs(self.y - other.y) < epsilon

    def __hash__(self) -> int:
        """Hash vector for use in sets/dicts."""
        return hash((round(self.x, 6), round(self.y, 6)))

    def magnitude(self) -> float:
        """Return the magnitude (length) of the vector."""
        return math.sqrt(self.x * self.x + self.y * self.y)

    def magnitude_squared(self) -> float:
        """Return squared magnitude (faster, no sqrt)."""
        return self.x * self.x + self.y * self.y

    def normalize(self) -> "Vec2":
        """Return normalized vector (magnitude = 1)."""
        mag = self.magnitude()
        if mag == 0:
            return Vec2(0, 0)
        return self / mag

    def dot(self, other: "Vec2") -> float:
        """Calculate dot product with another vector."""
        return self.x * other.x + self.y * other.y

    def cross(self, other: "Vec2") -> float:
        """Calculate cross product (returns scalar in 2D)."""
        return self.x * other.y - self.y * other.x

    def distance_to(self, other: "Vec2") -> float:
        """Calculate distance to another point."""
        dx = self.x - other.x
        dy = self.y - other.y
        return math.sqrt(dx * dx + dy * dy)

    def distance_squared_to(self, other: "Vec2") -> float:
        """Calculate squared distance (faster, no sqrt)."""
        dx = self.x - other.x
        dy = self.y - other.y
        return dx * dx + dy * dy

    def angle_to(self, other: "Vec2") -> float:
        """Calculate angle to another point (radians)."""
        diff = other - self
        return math.atan2(diff.y, diff.x)

    def rotate(self, angle_radians: float) -> "Vec2":
        """Rotate vector by angle in radians."""
        cos_a = math.cos(angle_radians)
        sin_a = math.sin(angle_radians)
        return Vec2(
            self.x * cos_a - self.y * sin_a,
            self.x * sin_a + self.y * cos_a,
        )

    def clamp_magnitude(self, max_magnitude: float) -> "Vec2":
        """Clamp vector to maximum magnitude."""
        mag = self.magnitude()
        if mag > max_magnitude:
            return (self / mag) * max_magnitude
        return Vec2(self.x, self.y)

    def lerp(self, other: "Vec2", t: float) -> "Vec2":
        """Linear interpolation towards another vector."""
        t = max(0, min(1, t))
        return Vec2(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
        )


@dataclass
class GameEntity:
    """Represents a game entity with position and velocity.

    Entities are the primary objects in the game world that AI systems
    interact with and control.
    """

    id: int
    position: Vec2
    velocity: Vec2
    faction: str = "neutral"


class AIState(Enum):
    """Enumeration of basic AI states."""

    IDLE = "idle"
    ACTIVE = "active"
    SLEEPING = "sleeping"
    DISABLED = "disabled"


class BTNodeStatus(Enum):
    """Behavior tree node execution status.

    SUCCESS: Node completed successfully
    FAILURE: Node failed
    RUNNING: Node is still executing
    """

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


class ActionType(Enum):
    """Types of actions in GOAP and decision-making."""

    MOVE = "move"
    ATTACK = "attack"
    DEFEND = "defend"
    HEAL = "heal"
    GATHER = "gather"
    BUILD = "build"
    SCOUT = "scout"
    CUSTOM = "custom"


@dataclass
class Goal:
    """Represents a goal state to achieve.

    Goals can have priority levels and conditions that define
    the desired world state.
    """

    name: str
    conditions: dict[str, Any]
    priority: int = 0
    max_cost: float | None = None


@dataclass
class NavMeshPolygon:
    """Represents a polygon in a navigation mesh.

    Polygons define walkable areas and edges connect adjacent polygons
    for pathfinding.
    """

    id: int
    vertices: list[Vec2]
    edges: list[int] = field(default_factory=list)  # IDs of adjacent polygons

    def center(self) -> Vec2:
        """Calculate polygon center."""
        if not self.vertices:
            return Vec2(0, 0)
        avg_x = sum(v.x for v in self.vertices) / len(self.vertices)
        avg_y = sum(v.y for v in self.vertices) / len(self.vertices)
        return Vec2(avg_x, avg_y)

    def contains_point(self, point: Vec2) -> bool:
        """Check if point is inside polygon using ray casting."""
        if len(self.vertices) < 3:
            return False

        inside = False
        p1 = self.vertices[-1]

        for p2 in self.vertices:
            if (p2.y > point.y) != (p1.y > point.y) and point.x < (p1.x - p2.x) * (point.y - p2.y) / (
                p1.y - p2.y
            ) + p2.x:
                inside = not inside
            p1 = p2

        return inside


@dataclass
class InfluenceCell:
    """Represents a cell in an influence map."""

    x: int
    y: int
    value: float = 0.0

    def position(self, cell_size: float) -> Vec2:
        """Convert grid cell to world position."""
        return Vec2(self.x * cell_size + cell_size / 2, self.y * cell_size + cell_size / 2)


@dataclass
class UtilityScore:
    """Represents a scored decision with utility value."""

    decision_name: str
    utility: float
    component_scores: dict[str, float] = field(default_factory=dict)


# Blackboard for sharing data between behavior tree nodes
Blackboard = dict[str, Any]
