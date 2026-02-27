"""
Collision response: impulse resolution, friction, restitution.
"""

from __future__ import annotations

from dataclasses import dataclass

from thomas.physics._types import Vec3
from thomas.physics.collision_detection import CollisionManifold
from thomas.physics.rigid_body import RigidBody


@dataclass
class Contact:
    """Contact between two bodies."""

    body_a: RigidBody
    body_b: RigidBody
    manifold: CollisionManifold
    # For warm starting
    normal_impulse: float = 0.0
    tangent_impulse: float = 0.0
    tangent_direction: Vec3 | None = None

    def calculate_relative_velocity(self) -> Vec3:
        """Calculate relative velocity at contact point."""
        vel_a = self.body_a.get_velocity_at_point(self.manifold.contact_point)
        vel_b = self.body_b.get_velocity_at_point(self.manifold.contact_point)
        return vel_b - vel_a

    def calculate_relative_velocity_along_normal(self) -> float:
        """Calculate relative velocity along contact normal."""
        rel_vel = self.calculate_relative_velocity()
        return rel_vel.dot(self.manifold.contact_normal)

    def update_warm_starting_impulses(self, normal_impulse: float, tangent_impulse: float) -> None:
        """Update impulses for next frame warm starting."""
        self.normal_impulse = normal_impulse
        self.tangent_impulse = tangent_impulse


def resolve_collision(
    contact: Contact,
    gravity: Vec3,
    contact_slop: float = 0.01,
    baumgarte_bias: float = 0.2,
) -> None:
    """Resolve collision using impulse-based method.

    Args:
        contact: Contact to resolve
        gravity: Gravity vector
        contact_slop: Penetration tolerance
        baumgarte_bias: Baumgarte bias factor for position correction
    """
    # Get bodies
    body_a = contact.body_a
    body_b = contact.body_b

    # Skip if both static
    if body_a.inverse_mass == 0 and body_b.inverse_mass == 0:
        return

    # Contact normal and point
    normal = contact.manifold.contact_normal
    contact_point = contact.manifold.contact_point
    penetration = contact.manifold.penetration_depth

    # Vectors from center of mass to contact point
    r_a = contact_point - body_a.position
    r_b = contact_point - body_b.position

    # Relative velocity
    vel_a = body_a.get_velocity_at_point(contact_point)
    vel_b = body_b.get_velocity_at_point(contact_point)
    rel_vel = vel_b - vel_a

    # Relative velocity along normal
    vel_along_normal = rel_vel.dot(normal)

    # Don't resolve if velocities are separating
    if vel_along_normal >= 0:
        return

    # Calculate restitution coefficient
    restitution = (body_a.material.restitution + body_b.material.restitution) * 0.5

    # Calculate impulse scalar
    # J = -(1 + e) * (v_rel · n) / (1/ma + 1/mb + (ra × n) · (Ia^-1 * (ra × n)) + (rb × n) · (Ib^-1 * (rb × n)))

    cross_a = r_a.cross(normal)
    cross_b = r_b.cross(normal)

    inv_mass_sum = body_a.inverse_mass + body_b.inverse_mass
    inv_inertia_a = cross_a.dot(cross_a) * body_a.inverse_inertia
    inv_inertia_b = cross_b.dot(cross_b) * body_b.inverse_inertia

    j = -(1.0 + restitution) * vel_along_normal / (inv_mass_sum + inv_inertia_a + inv_inertia_b)

    # Apply impulse
    impulse = normal * j
    body_a.apply_impulse_at_point(-impulse, contact_point)
    body_b.apply_impulse_at_point(impulse, contact_point)

    # Position correction (Baumgarte stabilization)
    if penetration > contact_slop:
        correction = (penetration - contact_slop) * baumgarte_bias / (inv_mass_sum + 1e-9)
        body_a.position -= normal * (correction * body_a.inverse_mass)
        body_b.position += normal * (correction * body_b.inverse_mass)


def apply_friction_impulse(
    contact: Contact,
) -> None:
    """Apply friction impulse using Coulomb friction model.

    Args:
        contact: Contact to apply friction to
    """
    body_a = contact.body_a
    body_b = contact.body_b

    if body_a.inverse_mass == 0 and body_b.inverse_mass == 0:
        return

    normal = contact.manifold.contact_normal
    contact_point = contact.manifold.contact_point

    # Calculate friction coefficient
    friction = (body_a.material.friction + body_b.material.friction) * 0.5

    # Relative velocity
    vel_a = body_a.get_velocity_at_point(contact_point)
    vel_b = body_b.get_velocity_at_point(contact_point)
    rel_vel = vel_b - vel_a

    # Tangent direction (perpendicular to normal)
    vel_along_normal = rel_vel.dot(normal)
    normal_component = normal * vel_along_normal
    tangent_vel = rel_vel - normal_component

    tangent_magnitude = tangent_vel.magnitude()
    if tangent_magnitude < 1e-9:
        return

    tangent_dir = tangent_vel.normalize()
    contact.tangent_direction = tangent_dir

    # Vectors from center of mass to contact
    r_a = contact_point - body_a.position
    r_b = contact_point - body_b.position

    cross_a = r_a.cross(tangent_dir)
    cross_b = r_b.cross(tangent_dir)

    inv_mass_sum = body_a.inverse_mass + body_b.inverse_mass
    inv_inertia_a = cross_a.dot(cross_a) * body_a.inverse_inertia
    inv_inertia_b = cross_b.dot(cross_b) * body_b.inverse_inertia

    # Friction impulse magnitude
    j_tangent = -tangent_vel.dot(tangent_dir) / (inv_mass_sum + inv_inertia_a + inv_inertia_b + 1e-9)

    # Clamp to friction cone
    normal_impulse = abs(contact.normal_impulse)
    max_friction = friction * normal_impulse
    j_tangent = max(-max_friction, min(j_tangent, max_friction))

    # Apply friction impulse
    friction_impulse = tangent_dir * j_tangent
    body_a.apply_impulse_at_point(-friction_impulse, contact_point)
    body_b.apply_impulse_at_point(friction_impulse, contact_point)

    contact.tangent_impulse = j_tangent


def warm_start_contact(contact: Contact) -> None:
    """Apply cached impulses from previous frame for stability.

    Args:
        contact: Contact to warm start
    """
    body_a = contact.body_a
    body_b = contact.body_b

    if body_a.inverse_mass == 0 and body_b.inverse_mass == 0:
        return

    normal = contact.manifold.contact_normal
    contact_point = contact.manifold.contact_point

    # Apply normal impulse
    if contact.normal_impulse > 0:
        impulse = normal * contact.normal_impulse
        body_a.apply_impulse_at_point(-impulse, contact_point)
        body_b.apply_impulse_at_point(impulse, contact_point)

    # Apply tangent impulse
    if contact.tangent_impulse > 0 and contact.tangent_direction:
        friction_impulse = contact.tangent_direction * contact.tangent_impulse
        body_a.apply_impulse_at_point(-friction_impulse, contact_point)
        body_b.apply_impulse_at_point(friction_impulse, contact_point)


def sequential_impulse_solver(
    contacts: list[Contact],
    iterations: int = 4,
    gravity: Vec3 | None = None,
    contact_slop: float = 0.01,
    baumgarte_bias: float = 0.2,
) -> None:
    """Sequential impulse solver (Gauss-Seidel style).

    Args:
        contacts: List of contacts to solve
        iterations: Number of solver iterations
        gravity: Gravity vector (for resolve_collision if needed)
        contact_slop: Penetration tolerance
        baumgarte_bias: Baumgarte bias factor
    """
    if gravity is None:
        gravity = Vec3(0, -9.81, 0)

    for _ in range(iterations):
        for contact in contacts:
            resolve_collision(contact, gravity, contact_slop, baumgarte_bias)
            apply_friction_impulse(contact)
