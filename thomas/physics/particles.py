"""
Particle system: emitters, forces, pooling, lifetime management.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from thomas.physics._types import Vec3


@dataclass
class Particle:
    """Individual particle in system."""

    position: Vec3
    velocity: Vec3
    acceleration: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    lifetime: float = 1.0
    age: float = 0.0
    alive: bool = True
    mass: float = 1.0

    def is_alive(self) -> bool:
        """Check if particle is still alive."""
        return self.alive and self.age < self.lifetime

    def update(self, timestep: float) -> None:
        """Update particle position and age.

        Args:
            timestep: Time step
        """
        if not self.alive:
            return

        # v += a*dt
        self.velocity += self.acceleration * timestep

        # x += v*dt
        self.position += self.velocity * timestep

        self.age += timestep

        if self.age >= self.lifetime:
            self.alive = False


@dataclass
class ParticleEmitter:
    """Particle emitter configuration."""

    position: Vec3
    velocity_min: Vec3 = field(default_factory=lambda: Vec3(-1, -1, -1))
    velocity_max: Vec3 = field(default_factory=lambda: Vec3(1, 1, 1))
    lifetime_min: float = 1.0
    lifetime_max: float = 2.0
    emission_rate: float = 10.0  # Particles per second
    mass: float = 1.0
    burst_count: int = 0  # 0 = continuous, >0 = burst
    enable_emission: bool = True

    def get_random_velocity(self) -> Vec3:
        """Get random velocity within configured range.

        Returns:
            Random velocity
        """
        return Vec3(
            random.uniform(self.velocity_min.x, self.velocity_max.x),
            random.uniform(self.velocity_min.y, self.velocity_max.y),
            random.uniform(self.velocity_min.z, self.velocity_max.z),
        )

    def get_random_lifetime(self) -> float:
        """Get random lifetime within configured range.

        Returns:
            Random lifetime
        """
        return random.uniform(self.lifetime_min, self.lifetime_max)


@dataclass
class ParticleSystem:
    """Particle system with pooling and force management."""

    particles: list[Particle] = field(default_factory=list)
    emitters: list[ParticleEmitter] = field(default_factory=list)
    forces: list[tuple[str, Vec3]] = field(default_factory=list)  # (type, data)
    max_particles: int = 1000
    emission_accumulator: float = 0.0
    gravity: Vec3 = field(default_factory=lambda: Vec3(0, -9.81, 0))
    air_resistance: float = 0.99

    def add_emitter(self, emitter: ParticleEmitter) -> None:
        """Add particle emitter.

        Args:
            emitter: Emitter to add
        """
        self.emitters.append(emitter)

    def remove_emitter(self, emitter: ParticleEmitter) -> None:
        """Remove particle emitter.

        Args:
            emitter: Emitter to remove
        """
        self.emitters.remove(emitter)

    def add_force(self, force_type: str, data: Vec3) -> None:
        """Add force to all particles.

        Args:
            force_type: Type of force ("gravity", "wind", "drag", "attractor", "repulsor")
            data: Force data (direction/magnitude or position)
        """
        self.forces.append((force_type, data))

    def remove_force(self, force_type: str) -> None:
        """Remove force by type.

        Args:
            force_type: Type of force to remove
        """
        self.forces = [(t, d) for t, d in self.forces if t != force_type]

    def update(self, timestep: float) -> None:
        """Update particle system.

        Args:
            timestep: Time step
        """
        # Emit new particles
        self._emit_particles(timestep)

        # Update existing particles
        for particle in self.particles:
            if particle.is_alive():
                # Reset acceleration
                particle.acceleration = Vec3(0, 0, 0)

                # Apply forces
                self._apply_forces(particle)

                # Update particle
                particle.update(timestep)

                # Apply air resistance
                particle.velocity = particle.velocity * self.air_resistance

        # Remove dead particles (reuse later)
        self.particles = [p for p in self.particles if p.alive]

    def _emit_particles(self, timestep: float) -> None:
        """Emit particles from active emitters.

        Args:
            timestep: Time step
        """
        for emitter in self.emitters:
            if not emitter.enable_emission:
                continue

            if emitter.burst_count > 0:
                # Burst emission
                for _ in range(emitter.burst_count):
                    if len(self.particles) < self.max_particles:
                        particle = Particle(
                            position=emitter.position,
                            velocity=emitter.get_random_velocity(),
                            lifetime=emitter.get_random_lifetime(),
                            mass=emitter.mass,
                        )
                        self.particles.append(particle)
                emitter.burst_count = 0
            else:
                # Continuous emission
                self.emission_accumulator += emitter.emission_rate * timestep

                while self.emission_accumulator >= 1.0 and len(self.particles) < self.max_particles:
                    particle = Particle(
                        position=emitter.position,
                        velocity=emitter.get_random_velocity(),
                        lifetime=emitter.get_random_lifetime(),
                        mass=emitter.mass,
                    )
                    self.particles.append(particle)
                    self.emission_accumulator -= 1.0

    def _apply_forces(self, particle: Particle) -> None:
        """Apply forces to particle.

        Args:
            particle: Particle to apply forces to
        """
        for force_type, data in self.forces:
            if force_type == "gravity":
                # Gravity: acceleration = F/m
                particle.acceleration += data / particle.mass

            elif force_type == "wind":
                # Wind: constant force
                particle.acceleration += data / particle.mass

            elif force_type == "drag":
                # Drag: F = -c * v
                drag_force = -data * particle.velocity.magnitude()
                particle.acceleration += drag_force / particle.mass

            elif force_type == "attractor":
                # Attractor: gravitational pull toward point
                attractor_pos = data
                direction = attractor_pos - particle.position
                distance = direction.magnitude()
                if distance > 0.1:
                    # F = -G * m1 * m2 / r^2
                    strength = 10.0
                    force = direction.normalize() * (strength / (distance * distance + 1e-6))
                    particle.acceleration += force / particle.mass

            elif force_type == "repulsor":
                # Repulsor: push away from point
                repulsor_pos = data
                direction = particle.position - repulsor_pos
                distance = direction.magnitude()
                if distance > 0.1:
                    strength = 10.0
                    force = direction.normalize() * (strength / (distance * distance + 1e-6))
                    particle.acceleration += force / particle.mass

    def burst_emit(self, emitter_index: int, count: int) -> None:
        """Trigger burst emission from emitter.

        Args:
            emitter_index: Index of emitter
            count: Number of particles to emit
        """
        if 0 <= emitter_index < len(self.emitters):
            self.emitters[emitter_index].burst_count = count

    def clear(self) -> None:
        """Clear all particles."""
        self.particles.clear()
        self.emission_accumulator = 0.0

    def get_particle_count(self) -> int:
        """Get current particle count.

        Returns:
            Number of alive particles
        """
        return sum(1 for p in self.particles if p.alive)

    def get_render_data(self) -> list[tuple]:
        """Get particle data for rendering.

        Returns:
            List of (position, age, lifetime) tuples
        """
        return [
            (
                (p.position.x, p.position.y, p.position.z),
                p.age,
                p.lifetime,
            )
            for p in self.particles
            if p.alive
        ]
