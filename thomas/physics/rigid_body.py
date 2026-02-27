"""
Rigid body physics: mass, forces, torques, and motion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.physics._types import Material, RigidBodyType, Vec3


@dataclass
class RigidBody:
    """Rigid body with position, velocity, forces, and rotation."""

    body_id: int
    position: Vec3
    velocity: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    acceleration: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    mass: float = 1.0
    material: Material = field(default_factory=Material)
    body_type: RigidBodyType = RigidBodyType.DYNAMIC
    # Rotation (3D: quaternion simplified as angle + axis; 2D: angle)
    angle: float = 0.0  # For 2D or rotation around Z
    angular_velocity: float = 0.0
    angular_acceleration: float = 0.0
    # Accumulated forces and torques (cleared after integration)
    force_accumulator: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    torque_accumulator: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    # Inertia
    inverse_mass: float = 1.0
    inverse_inertia: float = 1.0
    inertia: float = 1.0
    # Sleep state
    is_sleeping: bool = False
    sleep_time: float = 0.0
    # Caching
    linear_velocity_cached: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    _previous_position: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))

    def __post_init__(self) -> None:
        """Initialize derived properties."""
        self._update_mass_properties()

    def _update_mass_properties(self) -> None:
        """Update inverse mass and inertia based on mass and type."""
        if self.body_type == RigidBodyType.STATIC:
            self.inverse_mass = 0.0
            self.inverse_inertia = 0.0
        elif self.body_type == RigidBodyType.DYNAMIC:
            self.inverse_mass = 1.0 / self.mass if self.mass > 0 else 0.0
            self.inverse_inertia = 1.0 / self.inertia if self.inertia > 0 else 0.0
        elif self.body_type == RigidBodyType.KINEMATIC:
            self.inverse_mass = 0.0
            self.inverse_inertia = 0.0

    def set_mass(self, mass: float) -> None:
        """Set mass and update inverse mass."""
        if mass <= 0:
            raise ValueError("Mass must be positive")
        self.mass = mass
        self._update_mass_properties()

    def set_body_type(self, body_type: RigidBodyType) -> None:
        """Set body type and update properties."""
        self.body_type = body_type
        self._update_mass_properties()

    def set_moment_of_inertia_circle(self, radius: float) -> None:
        """Set moment of inertia for a circle/disk."""
        # I = (1/2) * m * r^2
        self.inertia = 0.5 * self.mass * radius * radius
        self._update_mass_properties()

    def set_moment_of_inertia_rectangle(self, width: float, height: float) -> None:
        """Set moment of inertia for a rectangle."""
        # I = (1/12) * m * (w^2 + h^2)
        self.inertia = (self.mass / 12.0) * (width * width + height * height)
        self._update_mass_properties()

    def set_moment_of_inertia_box(self, width: float, height: float, depth: float) -> None:
        """Set moment of inertia for a box."""
        # I = (1/12) * m * (w^2 + h^2) for simplification
        self.inertia = (self.mass / 12.0) * (width * width + height * height)
        self._update_mass_properties()

    def apply_force(self, force: Vec3) -> None:
        """Apply force at center of mass."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return
        self.force_accumulator += force

    def apply_force_at_point(self, force: Vec3, point: Vec3) -> None:
        """Apply force at a point, creating torque."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return
        self.apply_force(force)
        # Torque = r × F (cross product)
        radius = point - self.position
        torque = radius.cross(force)
        self.torque_accumulator += torque

    def apply_impulse(self, impulse: Vec3) -> None:
        """Apply impulse (change in momentum)."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return
        self.velocity += impulse * self.inverse_mass

    def apply_impulse_at_point(self, impulse: Vec3, point: Vec3) -> None:
        """Apply impulse at a point, creating angular impulse."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return
        self.apply_impulse(impulse)
        # Angular impulse = r × impulse
        radius = point - self.position
        angular_impulse = radius.cross(impulse)
        self.angular_velocity += angular_impulse.magnitude() * self.inverse_inertia

    def apply_torque(self, torque: Vec3) -> None:
        """Apply torque directly."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return
        self.torque_accumulator += torque

    def integrate_forces(self, gravity: Vec3, timestep: float) -> None:
        """Integrate forces to update acceleration and velocity."""
        if self.body_type != RigidBodyType.DYNAMIC:
            return

        # F = ma, a = F/m
        total_force = self.force_accumulator + gravity * self.mass
        self.acceleration = total_force * self.inverse_mass

        # v += a*dt (semi-implicit Euler)
        self.velocity += self.acceleration * timestep

        # Angular: α = τ/I
        angular_acceleration = self.torque_accumulator.magnitude() * self.inverse_inertia
        self.angular_velocity += angular_acceleration * timestep

        # Clear accumulators
        self.force_accumulator = Vec3(0, 0, 0)
        self.torque_accumulator = Vec3(0, 0, 0)

    def integrate_velocity(self, timestep: float, damping: float) -> None:
        """Integrate velocity to update position (Verlet-like)."""
        if self.body_type == RigidBodyType.STATIC:
            return

        # Store previous position for Verlet
        self._previous_position = self.position

        # Apply damping
        self.velocity = self.velocity * damping
        self.angular_velocity *= damping

        # x += v*dt
        self.position += self.velocity * timestep

        # Update angle (2D rotation)
        self.angle += self.angular_velocity * timestep

    def set_velocity(self, velocity: Vec3) -> None:
        """Set velocity directly."""
        self.velocity = velocity

    def set_angular_velocity(self, angular_velocity: float) -> None:
        """Set angular velocity directly."""
        self.angular_velocity = angular_velocity

    def get_velocity_at_point(self, point: Vec3) -> Vec3:
        """Get velocity at a point on the body."""
        # v_point = v_cm + ω × r
        radius = point - self.position
        # For 2D: angular_velocity is around Z, so cross product gives (x, y, 0)
        angular_component = Vec3(
            -self.angular_velocity * radius.y,
            self.angular_velocity * radius.x,
            0,
        )
        return self.velocity + angular_component

    def put_to_sleep(self) -> None:
        """Put body to sleep."""
        self.is_sleeping = True
        self.sleep_time = 0.0
        self.velocity = Vec3(0, 0, 0)
        self.angular_velocity = 0.0

    def wake_up(self) -> None:
        """Wake up sleeping body."""
        self.is_sleeping = False
        self.sleep_time = 0.0

    def check_sleep(
        self,
        velocity_threshold: float,
        angular_velocity_threshold: float,
        time_threshold: float,
        timestep: float,
    ) -> None:
        """Check if body should sleep."""
        vel_mag = self.velocity.magnitude()
        ang_vel_mag = abs(self.angular_velocity)

        if vel_mag < velocity_threshold and ang_vel_mag < angular_velocity_threshold:
            self.sleep_time += timestep
            if self.sleep_time >= time_threshold:
                self.put_to_sleep()
        else:
            self.wake_up()

    def get_kinetic_energy(self) -> float:
        """Calculate kinetic energy."""
        linear_ke = 0.5 * self.mass * self.velocity.magnitude_squared()
        angular_ke = 0.5 * self.inertia * self.angular_velocity * self.angular_velocity
        return linear_ke + angular_ke

    def get_potential_energy(self, gravity: Vec3) -> float:
        """Calculate gravitational potential energy."""
        # U = -m * g · r (where g is gravity acceleration)
        return -self.mass * gravity.dot(self.position)

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"RigidBody(id={self.body_id}, type={self.body_type.name}, "
            f"pos={self.position}, vel={self.velocity}, mass={self.mass})"
        )
