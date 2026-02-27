"""
Physics constraints: distance, joints, contact, and solver.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from thomas.physics._types import Vec3
from thomas.physics.rigid_body import RigidBody


class Constraint(ABC):
    """Base class for constraints."""

    @abstractmethod
    def solve(self) -> None:
        """Solve constraint."""
        pass

    @abstractmethod
    def get_constraint_force(self) -> float:
        """Get current constraint force."""
        pass


@dataclass
class DistanceConstraint(Constraint):
    """Distance constraint (spring or rigid rod)."""

    body_a: RigidBody
    body_b: RigidBody
    local_point_a: Vec3
    local_point_b: Vec3
    rest_distance: float
    spring_constant: float = 0.0  # 0 = rigid
    damping: float = 0.0
    max_force: float = float("inf")
    constraint_force: float = 0.0

    def get_world_point_a(self) -> Vec3:
        """Get point A in world space."""
        return self.body_a.position + self.local_point_a

    def get_world_point_b(self) -> Vec3:
        """Get point B in world space."""
        return self.body_b.position + self.local_point_b

    def solve(self) -> None:
        """Solve distance constraint using spring or rigid rod."""
        point_a = self.get_world_point_a()
        point_b = self.get_world_point_b()

        delta = point_b - point_a
        current_distance = delta.magnitude()

        if current_distance < 1e-9:
            self.constraint_force = 0.0
            return

        direction = delta.normalize()
        distance_error = current_distance - self.rest_distance

        if self.spring_constant > 0:
            # Spring force: F = -k * x
            spring_force = -self.spring_constant * distance_error

            # Damping force: F = -d * v_rel
            vel_a = self.body_a.get_velocity_at_point(point_a)
            vel_b = self.body_b.get_velocity_at_point(point_b)
            relative_vel = vel_b - vel_a
            vel_along_direction = relative_vel.dot(direction)
            damping_force = -self.damping * vel_along_direction

            force_magnitude = spring_force + damping_force
        else:
            # Rigid rod - use impulse method
            vel_a = self.body_a.get_velocity_at_point(point_a)
            vel_b = self.body_b.get_velocity_at_point(point_b)
            relative_vel = vel_b - vel_a
            vel_along_direction = relative_vel.dot(direction)

            if abs(vel_along_direction) < 1e-9:
                force_magnitude = 0.0
            else:
                # Calculate impulse to correct distance
                r_a = point_a - self.body_a.position
                r_b = point_b - self.body_b.position
                cross_a = r_a.cross(direction)
                cross_b = r_b.cross(direction)

                inv_mass_sum = self.body_a.inverse_mass + self.body_b.inverse_mass
                inv_inertia_a = cross_a.dot(cross_a) * self.body_a.inverse_inertia
                inv_inertia_b = cross_b.dot(cross_b) * self.body_b.inverse_inertia

                force_magnitude = -vel_along_direction / (inv_mass_sum + inv_inertia_a + inv_inertia_b + 1e-9)

        # Clamp force
        force_magnitude = max(-self.max_force, min(force_magnitude, self.max_force))
        self.constraint_force = force_magnitude

        # Apply forces
        impulse = direction * force_magnitude
        self.body_a.apply_impulse_at_point(-impulse, point_a)
        self.body_b.apply_impulse_at_point(impulse, point_b)

    def get_constraint_force(self) -> float:
        """Get current constraint force."""
        return self.constraint_force


@dataclass
class HingeJoint(Constraint):
    """Hinge (revolute) joint between two bodies."""

    body_a: RigidBody
    body_b: RigidBody
    anchor: Vec3
    axis: Vec3  # Joint axis
    lower_limit: float = 0.0
    upper_limit: float = 0.0
    enable_limit: bool = False
    constraint_force: float = 0.0

    def __post_init__(self) -> None:
        """Normalize axis."""
        self.axis = self.axis.normalize()

    def solve(self) -> None:
        """Solve hinge constraint."""
        # Ensure anchor is shared between bodies
        anchor_a = self.anchor - self.body_a.position
        anchor_b = self.anchor - self.body_b.position

        # Relative position at anchor
        pos_a = self.body_a.position + anchor_a
        pos_b = self.body_b.position + anchor_b

        delta = pos_b - pos_a

        if delta.magnitude() > 1e-3:
            # Correct anchor position
            direction = delta.normalize()
            correction = delta.magnitude() / (self.body_a.inverse_mass + self.body_b.inverse_mass + 1e-9) * 0.5
            self.body_a.position -= direction * (correction * self.body_a.inverse_mass)
            self.body_b.position += direction * (correction * self.body_b.inverse_mass)

    def get_constraint_force(self) -> float:
        """Get current constraint force."""
        return self.constraint_force


@dataclass
class SliderJoint(Constraint):
    """Slider (prismatic) joint between two bodies."""

    body_a: RigidBody
    body_b: RigidBody
    anchor: Vec3
    slide_axis: Vec3  # Direction of allowed motion
    lower_limit: float = 0.0
    upper_limit: float = 0.0
    enable_limit: bool = False
    constraint_force: float = 0.0

    def __post_init__(self) -> None:
        """Normalize slide axis."""
        self.slide_axis = self.slide_axis.normalize()

    def solve(self) -> None:
        """Solve slider constraint."""
        # Keep bodies aligned along slide axis
        anchor_a = self.anchor - self.body_a.position
        anchor_b = self.anchor - self.body_b.position

        pos_a = self.body_a.position + anchor_a
        pos_b = self.body_b.position + anchor_b

        delta = pos_b - pos_a
        slide_component = delta.dot(self.slide_axis)
        perpendicular_component = delta - self.slide_axis * slide_component

        if perpendicular_component.magnitude() > 1e-3:
            direction = perpendicular_component.normalize()
            correction = (
                perpendicular_component.magnitude() / (self.body_a.inverse_mass + self.body_b.inverse_mass + 1e-9) * 0.5
            )
            self.body_a.position -= direction * (correction * self.body_a.inverse_mass)
            self.body_b.position += direction * (correction * self.body_b.inverse_mass)

    def get_constraint_force(self) -> float:
        """Get current constraint force."""
        return self.constraint_force


@dataclass
class ContactConstraint(Constraint):
    """Contact constraint from collision."""

    body_a: RigidBody
    body_b: RigidBody
    contact_point: Vec3
    contact_normal: Vec3
    penetration_depth: float
    restitution: float = 0.0
    friction: float = 0.5
    constraint_force: float = 0.0

    def solve(self) -> None:
        """Solve contact constraint."""
        vel_a = self.body_a.get_velocity_at_point(self.contact_point)
        vel_b = self.body_b.get_velocity_at_point(self.contact_point)
        rel_vel = vel_b - vel_a

        vel_along_normal = rel_vel.dot(self.contact_normal)

        if vel_along_normal >= 0:
            return

        # Calculate impulse
        r_a = self.contact_point - self.body_a.position
        r_b = self.contact_point - self.body_b.position

        cross_a = r_a.cross(self.contact_normal)
        cross_b = r_b.cross(self.contact_normal)

        inv_mass_sum = self.body_a.inverse_mass + self.body_b.inverse_mass
        inv_inertia_a = cross_a.dot(cross_a) * self.body_a.inverse_inertia
        inv_inertia_b = cross_b.dot(cross_b) * self.body_b.inverse_inertia

        j = -(1.0 + self.restitution) * vel_along_normal / (inv_mass_sum + inv_inertia_a + inv_inertia_b + 1e-9)

        self.constraint_force = j
        impulse = self.contact_normal * j

        self.body_a.apply_impulse_at_point(-impulse, self.contact_point)
        self.body_b.apply_impulse_at_point(impulse, self.contact_point)

    def get_constraint_force(self) -> float:
        """Get current constraint force."""
        return self.constraint_force


class ConstraintSolver:
    """Constraint solver using iterative method (Gauss-Seidel)."""

    def __init__(self, iterations: int = 4) -> None:
        """Initialize solver.

        Args:
            iterations: Number of solver iterations
        """
        self.iterations = iterations
        self.constraints: list[Constraint] = []

    def add_constraint(self, constraint: Constraint) -> None:
        """Add constraint to solver.

        Args:
            constraint: Constraint to add
        """
        self.constraints.append(constraint)

    def remove_constraint(self, constraint: Constraint) -> None:
        """Remove constraint from solver.

        Args:
            constraint: Constraint to remove
        """
        self.constraints.remove(constraint)

    def clear_constraints(self) -> None:
        """Clear all constraints."""
        self.constraints.clear()

    def solve(self) -> None:
        """Solve all constraints."""
        for _ in range(self.iterations):
            for constraint in self.constraints:
                constraint.solve()

    def get_total_constraint_force(self) -> float:
        """Get sum of all constraint forces."""
        return sum(c.get_constraint_force() for c in self.constraints)
