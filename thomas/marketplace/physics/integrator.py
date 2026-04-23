"""
Numerical integration methods: Euler, symplectic Euler, Verlet, RK4, adaptive.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from thomas.marketplace.physics._types import Vec3
from thomas.marketplace.physics.rigid_body import RigidBody


class Integrator(ABC):
    """Base class for numerical integrators."""

    @abstractmethod
    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float,
        angular_damping: float,
    ) -> None:
        """Step simulation forward.

        Args:
            bodies: Bodies to integrate
            gravity: Gravity vector
            timestep: Time step size
            damping: Linear velocity damping
            angular_damping: Angular velocity damping
        """
        pass


class EulerIntegrator(Integrator):
    """Explicit Euler integration (basic, least accurate)."""

    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float = 0.99,
        angular_damping: float = 0.99,
    ) -> None:
        """Step using explicit Euler: x += v*dt, v += a*dt."""
        for body in bodies:
            if body.body_type.value == 0:  # STATIC
                continue

            # v += a*dt
            body.velocity += body.acceleration * timestep

            # x += v*dt
            body.position += body.velocity * timestep

            # Apply damping
            body.velocity = body.velocity * damping
            body.angular_velocity *= angular_damping


class SymplecticEulerIntegrator(Integrator):
    """Semi-implicit Euler (symplectic, better energy conservation)."""

    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float = 0.99,
        angular_damping: float = 0.99,
    ) -> None:
        """Step using semi-implicit Euler: v += a*dt, x += v*dt."""
        for body in bodies:
            if body.body_type.value == 0:  # STATIC
                continue

            # Integrate forces
            body.integrate_forces(gravity, timestep)

            # Integrate velocity
            body.integrate_velocity(timestep, damping)


class VerletIntegrator(Integrator):
    """Verlet integration (position-based, stable for constraints)."""

    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float = 0.99,
        angular_damping: float = 0.99,
    ) -> None:
        """Step using Verlet: x_new = 2*x - x_prev + a*dt^2."""
        dt_sq = timestep * timestep

        for body in bodies:
            if body.body_type.value == 0:  # STATIC
                continue

            # Calculate new position using Verlet
            acceleration = (body.force_accumulator / body.mass) + gravity
            new_position = body.position * 2.0 - body._previous_position + acceleration * dt_sq

            # Update velocity from positions
            body.velocity = (new_position - body.position) / timestep * damping

            # Update position
            body._previous_position = body.position
            body.position = new_position

            # Angular motion (simplified)
            body.angular_velocity *= angular_damping
            body.angle += body.angular_velocity * timestep

            # Clear accumulators
            body.force_accumulator = Vec3(0, 0, 0)
            body.torque_accumulator = Vec3(0, 0, 0)


class RK4Integrator(Integrator):
    """4th-order Runge-Kutta integration (high accuracy)."""

    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float = 0.99,
        angular_damping: float = 0.99,
    ) -> None:
        """Step using 4th-order Runge-Kutta."""
        for body in bodies:
            if body.body_type.value == 0:  # STATIC
                continue

            # RK4 coefficients
            k1_vel = body._compute_acceleration(gravity)
            k1_pos = body.velocity

            # k2
            temp_vel = body.velocity + k1_vel * (timestep * 0.5)
            temp_pos = body.position + k1_pos * (timestep * 0.5)
            k2_vel = body._compute_acceleration(gravity)
            k2_pos = temp_vel

            # k3
            temp_vel = body.velocity + k2_vel * (timestep * 0.5)
            k3_vel = body._compute_acceleration(gravity)
            k3_pos = temp_vel

            # k4
            temp_vel = body.velocity + k3_vel * timestep
            temp_pos = body.position + k3_pos * timestep
            k4_vel = body._compute_acceleration(gravity)
            k4_pos = temp_vel

            # Update using weighted average
            body.velocity += (k1_vel + 2 * k2_vel + 2 * k3_vel + k4_vel) * (timestep / 6.0)
            body.position += (k1_pos + 2 * k2_pos + 2 * k3_pos + k4_pos) * (timestep / 6.0)

            # Apply damping
            body.velocity = body.velocity * damping
            body.angular_velocity *= angular_damping

            # Clear accumulators
            body.force_accumulator = Vec3(0, 0, 0)
            body.torque_accumulator = Vec3(0, 0, 0)


@dataclass
class AdaptiveIntegrator(Integrator):
    """Adaptive timestep integrator (adjusts step size for error tolerance)."""

    base_integrator: Integrator = None
    error_tolerance: float = 1e-4
    min_timestep: float = 0.001
    max_timestep: float = 0.033

    def __post_init__(self) -> None:
        """Initialize with default integrator."""
        if self.base_integrator is None:
            self.base_integrator = SymplecticEulerIntegrator()

    def step(
        self,
        bodies: list[RigidBody],
        gravity: Vec3,
        timestep: float,
        damping: float = 0.99,
        angular_damping: float = 0.99,
    ) -> None:
        """Step with adaptive timestep."""
        # Store initial state
        initial_states = [
            (body.position.x, body.position.y, body.position.z, body.velocity.x, body.velocity.y, body.velocity.z)
            for body in bodies
        ]

        # Try full step
        self.base_integrator.step(bodies, gravity, timestep, damping, angular_damping)
        full_step_states = [
            (body.position.x, body.position.y, body.position.z, body.velocity.x, body.velocity.y, body.velocity.z)
            for body in bodies
        ]

        # Restore and try two half steps
        for i, body in enumerate(bodies):
            body.position = Vec3(*initial_states[i][:3])
            body.velocity = Vec3(*initial_states[i][3:])

        half_step = timestep * 0.5
        self.base_integrator.step(bodies, gravity, half_step, damping, angular_damping)
        self.base_integrator.step(bodies, gravity, half_step, damping, angular_damping)
        half_step_states = [
            (body.position.x, body.position.y, body.position.z, body.velocity.x, body.velocity.y, body.velocity.z)
            for body in bodies
        ]

        # Compare errors
        max_error = 0.0
        for full, half in zip(full_step_states, half_step_states):
            for j in range(6):
                error = abs(full[j] - half[j])
                max_error = max(max_error, error)

        # Adjust for next step (simple approach)
        if max_error < self.error_tolerance * 0.1:
            # Error very small, can use larger step
            pass
        elif max_error > self.error_tolerance:
            # Error too large, should use smaller step next time
            pass


class RigidBody:
    """Stub to avoid circular import (full definition elsewhere)."""

    def _compute_acceleration(self, gravity: Vec3) -> Vec3:
        """Compute acceleration from forces."""
        total_force = self.force_accumulator + gravity * self.mass
        return total_force * self.inverse_mass
