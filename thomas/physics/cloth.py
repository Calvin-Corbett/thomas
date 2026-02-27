"""
Cloth simulation: mass-spring system, constraint satisfaction, collision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.physics._types import Plane, Sphere, Vec3


@dataclass
class ClothParticle:
    """Particle in cloth mesh."""

    position: Vec3
    old_position: Vec3
    pinned: bool = False
    mass: float = 1.0

    def apply_force(self, force: Vec3, timestep: float) -> None:
        """Apply force to particle using Verlet integration.

        Args:
            force: Force vector
            timestep: Time step
        """
        if self.pinned:
            return

        acceleration = force / self.mass
        dt_sq = timestep * timestep

        new_position = self.position * 2.0 - self.old_position + acceleration * dt_sq

        self.old_position = self.position
        self.position = new_position

    def constrain_to_sphere(self, sphere: Sphere) -> None:
        """Constrain particle to stay outside sphere.

        Args:
            sphere: Sphere to constrain against
        """
        if self.pinned:
            return

        distance = sphere.center.distance_to(self.position)
        if distance < sphere.radius:
            direction = (self.position - sphere.center).normalize()
            self.position = sphere.center + direction * sphere.radius

    def constrain_to_plane(self, plane: Plane) -> None:
        """Constrain particle to plane.

        Args:
            plane: Plane to constrain to
        """
        if self.pinned:
            return

        distance = plane.distance_to_point(self.position)
        if distance < 0:
            self.position = plane.closest_point_on_plane(self.position)


@dataclass
class ClothSpring:
    """Spring connecting two cloth particles."""

    particle_a: ClothParticle
    particle_b: ClothParticle
    rest_length: float
    spring_constant: float = 100.0
    damping: float = 0.5

    def constrain(self, iterations: int = 1) -> None:
        """Iteratively satisfy spring constraint (distance preservation).

        Args:
            iterations: Number of constraint iterations
        """
        for _ in range(iterations):
            delta = self.particle_b.position - self.particle_a.position
            current_length = delta.magnitude()

            if current_length < 1e-6:
                return

            difference = (current_length - self.rest_length) / current_length

            # Distribute correction equally if both particles free
            correction_a = difference * 0.5
            correction_b = difference * 0.5

            # Adjust if one is pinned
            if self.particle_a.pinned:
                correction_b = difference
            elif self.particle_b.pinned:
                correction_a = difference

            self.particle_a.position += delta * correction_a
            self.particle_b.position -= delta * correction_b


@dataclass
class ClothMesh:
    """Cloth simulation mesh."""

    width: int = 10
    height: int = 10
    segment_size: float = 1.0
    particles: list[ClothParticle] = field(default_factory=list)
    springs: list[ClothSpring] = field(default_factory=list)
    gravity: Vec3 = field(default_factory=lambda: Vec3(0, -9.81, 0))
    air_resistance: float = 0.99
    constraint_iterations: int = 3
    wind: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))

    def __post_init__(self) -> None:
        """Initialize cloth mesh."""
        self._create_mesh()

    def _create_mesh(self) -> None:
        """Create particle and spring network."""
        # Create particles in grid
        for y in range(self.height):
            for x in range(self.width):
                position = Vec3(
                    x * self.segment_size,
                    -y * self.segment_size,
                    0,
                )
                particle = ClothParticle(position=position, old_position=position)

                # Pin top corners
                if y == 0 and (x == 0 or x == self.width - 1):
                    particle.pinned = True

                self.particles.append(particle)

        # Create springs
        for y in range(self.height):
            for x in range(self.width):
                idx = y * self.width + x

                # Structural springs (horizontal)
                if x < self.width - 1:
                    self.springs.append(
                        ClothSpring(
                            self.particles[idx],
                            self.particles[idx + 1],
                            self.segment_size,
                        )
                    )

                # Structural springs (vertical)
                if y < self.height - 1:
                    self.springs.append(
                        ClothSpring(
                            self.particles[idx],
                            self.particles[idx + self.width],
                            self.segment_size,
                        )
                    )

                # Shear springs (diagonal)
                if x < self.width - 1 and y < self.height - 1:
                    diagonal_length = self.segment_size * (2**0.5)
                    self.springs.append(
                        ClothSpring(
                            self.particles[idx],
                            self.particles[idx + self.width + 1],
                            diagonal_length,
                            spring_constant=100.0 * 0.5,  # Weaker shear
                        )
                    )

                # Bend springs (skip one)
                if y < self.height - 2:
                    self.springs.append(
                        ClothSpring(
                            self.particles[idx],
                            self.particles[idx + 2 * self.width],
                            self.segment_size * 2,
                            spring_constant=100.0 * 0.25,  # Weaker bending
                        )
                    )

    def update(self, timestep: float) -> None:
        """Update cloth simulation.

        Args:
            timestep: Time step
        """
        # Apply forces
        for particle in self.particles:
            force = self.gravity * particle.mass + self.wind
            particle.apply_force(force, timestep)
            particle.velocity = (particle.position - particle.old_position) / timestep
            particle.velocity *= self.air_resistance

        # Satisfy constraints
        for _ in range(self.constraint_iterations):
            for spring in self.springs:
                spring.constrain()

    def constrain_sphere(self, sphere: Sphere) -> None:
        """Constrain cloth against sphere.

        Args:
            sphere: Sphere to constrain against
        """
        for particle in self.particles:
            particle.constrain_to_sphere(sphere)

    def constrain_plane(self, plane: Plane) -> None:
        """Constrain cloth to plane.

        Args:
            plane: Plane to constrain to
        """
        for particle in self.particles:
            particle.constrain_to_plane(plane)

    def pin_particle(self, x: int, y: int) -> None:
        """Pin particle at grid position.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = y * self.width + x
            self.particles[idx].pinned = True

    def unpin_particle(self, x: int, y: int) -> None:
        """Unpin particle at grid position.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            idx = y * self.width + x
            self.particles[idx].pinned = False

    def apply_force(self, force: Vec3) -> None:
        """Apply force to all particles.

        Args:
            force: Force vector
        """
        for particle in self.particles:
            if not particle.pinned:
                particle.apply_force(force, 0.016)

    def get_render_data(self) -> tuple[list[tuple], list[tuple[int, int]]]:
        """Get data for rendering cloth mesh.

        Returns:
            Tuple of (particle_positions, spring_indices)
        """
        positions = [(p.position.x, p.position.y, p.position.z) for p in self.particles]

        spring_indices = []
        for spring in self.springs:
            idx_a = self.particles.index(spring.particle_a)
            idx_b = self.particles.index(spring.particle_b)
            spring_indices.append((idx_a, idx_b))

        return positions, spring_indices

    def get_statistics(self) -> dict:
        """Get cloth statistics.

        Returns:
            Dictionary with statistics
        """
        total_kinetic_energy = 0.0
        for particle in self.particles:
            vel = particle.position - particle.old_position
            ke = 0.5 * particle.mass * vel.magnitude_squared()
            total_kinetic_energy += ke

        pinned_count = sum(1 for p in self.particles if p.pinned)

        return {
            "particle_count": len(self.particles),
            "spring_count": len(self.springs),
            "pinned_count": pinned_count,
            "total_kinetic_energy": total_kinetic_energy,
        }
