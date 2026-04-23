"""
Physics world: simulation loop, body management, queries, debug visualization.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.marketplace.physics._types import AABB, PhysicsConfig, Ray, RigidBodyType, Sphere, Vec3
from thomas.marketplace.physics.broadphase import AABBTree, SpatialHashGrid, SweepAndPrune
from thomas.marketplace.physics.collision_detection import (
    collide_aabb_aabb,
    collide_sphere_sphere,
)
from thomas.marketplace.physics.collision_response import (
    Contact,
    sequential_impulse_solver,
    warm_start_contact,
)
from thomas.marketplace.physics.constraints import ConstraintSolver
from thomas.marketplace.physics.integrator import Integrator, SymplecticEulerIntegrator
from thomas.marketplace.physics.rigid_body import RigidBody


@dataclass
class RaycastResult:
    """Result of ray cast query."""

    body: RigidBody | None = None
    distance: float = float("inf")
    point: Vec3 | None = None
    normal: Vec3 | None = None


@dataclass
class PhysicsWorld:
    """Physics world containing bodies and simulation."""

    config: PhysicsConfig = field(default_factory=PhysicsConfig)
    bodies: list[RigidBody] = field(default_factory=list)
    constraints: ConstraintSolver = field(default_factory=ConstraintSolver)
    integrator: Integrator = field(default_factory=SymplecticEulerIntegrator)
    broadphase: SpatialHashGrid | SweepAndPrune | AABBTree = field(default_factory=SpatialHashGrid)
    # Simulation state
    contacts: list[Contact] = field(default_factory=list)
    time_accumulator: float = 0.0
    simulation_time: float = 0.0
    # Statistics
    body_count: int = 0
    contact_count: int = 0
    constraint_iterations: int = 0

    def __post_init__(self) -> None:
        """Validate configuration."""
        self.config.validate()

    def add_body(self, body: RigidBody) -> None:
        """Add body to world.

        Args:
            body: Body to add
        """
        body.body_id = len(self.bodies)
        self.bodies.append(body)
        self.body_count = len(self.bodies)

        if isinstance(self.broadphase, AABBTree):
            self.broadphase.insert(body)

    def remove_body(self, body: RigidBody) -> None:
        """Remove body from world.

        Args:
            body: Body to remove
        """
        if body in self.bodies:
            self.bodies.remove(body)
            self.body_count = len(self.bodies)

            if isinstance(self.broadphase, AABBTree):
                self.broadphase.remove(body.body_id)

    def step(self, frame_time: float) -> None:
        """Step simulation forward.

        Args:
            frame_time: Elapsed time since last frame
        """
        # Clamp frame time
        frame_time = min(frame_time, self.config.max_frame_time)
        self.time_accumulator += frame_time

        # Fixed timestep loop
        while self.time_accumulator >= self.config.fixed_timestep:
            self._step_fixed(self.config.fixed_timestep)
            self.time_accumulator -= self.config.fixed_timestep
            self.simulation_time += self.config.fixed_timestep

    def _step_fixed(self, timestep: float) -> None:
        """Single fixed timestep.

        Args:
            timestep: Fixed timestep size
        """
        # Apply forces and integrate
        for body in self.bodies:
            if body.body_type == RigidBodyType.STATIC:
                continue
            body.integrate_forces(self.config.gravity, timestep)

        # Broad-phase collision detection
        if isinstance(self.broadphase, AABBTree):
            candidate_pairs = self.broadphase.get_broad_phase_pairs()
        elif isinstance(self.broadphase, SweepAndPrune):
            candidate_pairs = self.broadphase.get_broad_phase_pairs(self.bodies)
        else:
            self.broadphase.update(self.bodies)
            candidate_pairs = self.broadphase.get_broad_phase_pairs()

        # Narrow-phase collision detection
        self.contacts.clear()
        for body_a, body_b in candidate_pairs:
            manifold = self._test_collision(body_a, body_b)
            if manifold:
                contact = Contact(body_a, body_b, manifold)
                self.contacts.append(contact)

        self.contact_count = len(self.contacts)

        # Warm starting
        for contact in self.contacts:
            warm_start_contact(contact)

        # Constraint solving (sequential impulse)
        sequential_impulse_solver(
            self.contacts,
            self.config.constraint_iterations,
            gravity=self.config.gravity,
            contact_slop=self.config.contact_slop,
            baumgarte_bias=self.config.baumgarte_bias,
        )

        # Custom constraints
        self.constraints.solve()

        # Integrate velocity and position
        for body in self.bodies:
            if body.body_type == RigidBodyType.STATIC:
                continue
            body.integrate_velocity(
                timestep,
                self.config.velocity_damping,
            )
            body.angular_velocity *= self.config.angular_damping

        # Sleep detection
        for body in self.bodies:
            if body.body_type == RigidBodyType.DYNAMIC:
                body.check_sleep(
                    self.config.sleep_velocity_threshold,
                    self.config.sleep_angular_velocity_threshold,
                    self.config.sleep_time_threshold,
                    timestep,
                )

    def _test_collision(self, body_a: RigidBody, body_b: RigidBody) -> Sphere | None:
        """Test collision between two bodies (simplified with spheres).

        Args:
            body_a: First body
            body_b: Second body

        Returns:
            Collision manifold if collision, None otherwise
        """
        # Simplified: treat all bodies as spheres
        sphere_a = Sphere(body_a.position, 0.5)
        sphere_b = Sphere(body_b.position, 0.5)
        return collide_sphere_sphere(sphere_a, sphere_b)

    def raycast(self, ray: Ray) -> RaycastResult:
        """Cast ray and find closest intersection.

        Args:
            ray: Ray to cast

        Returns:
            RaycastResult with closest hit information
        """
        result = RaycastResult()

        for body in self.bodies:
            sphere = Sphere(body.position, 0.5)
            from thomas.marketplace.physics.collision_detection import ray_sphere_intersection

            t = ray_sphere_intersection(ray, sphere)

            if t is not None and t < result.distance:
                result.distance = t
                result.body = body
                result.point = ray.at(t)
                result.normal = (result.point - sphere.center).normalize()

        return result

    def query_aabb(self, aabb: AABB) -> list[RigidBody]:
        """Query bodies overlapping AABB.

        Args:
            aabb: AABB to query

        Returns:
            List of bodies overlapping AABB
        """
        results = []
        for body in self.bodies:
            body_aabb = AABB(
                body.position - Vec3(0.5, 0.5, 0.5),
                body.position + Vec3(0.5, 0.5, 0.5),
            )
            if collide_aabb_aabb(aabb, body_aabb):
                results.append(body)
        return results

    def query_point(self, point: Vec3, radius: float = 0.1) -> list[RigidBody]:
        """Query bodies near point.

        Args:
            point: Point to query
            radius: Search radius

        Returns:
            List of bodies within radius
        """
        results = []
        sphere = Sphere(point, radius)

        for body in self.bodies:
            body_sphere = Sphere(body.position, 0.5)
            from thomas.marketplace.physics.collision_detection import collide_sphere_sphere

            if collide_sphere_sphere(sphere, body_sphere):
                results.append(body)

        return results

    def get_statistics(self) -> dict:
        """Get simulation statistics.

        Returns:
            Dictionary with statistics
        """
        total_kinetic_energy = sum(b.get_kinetic_energy() for b in self.bodies)
        total_potential_energy = sum(b.get_potential_energy(self.config.gravity) for b in self.bodies)
        total_energy = total_kinetic_energy + total_potential_energy

        sleeping_count = sum(1 for b in self.bodies if b.is_sleeping)

        return {
            "body_count": self.body_count,
            "contact_count": self.contact_count,
            "sleeping_count": sleeping_count,
            "simulation_time": self.simulation_time,
            "total_kinetic_energy": total_kinetic_energy,
            "total_potential_energy": total_potential_energy,
            "total_energy": total_energy,
            "time_accumulator": self.time_accumulator,
        }

    def get_debug_data(self) -> dict:
        """Get debug visualization data.

        Returns:
            Dictionary with debug information
        """
        bodies_data = []
        for body in self.bodies:
            bodies_data.append(
                {
                    "id": body.body_id,
                    "position": (body.position.x, body.position.y, body.position.z),
                    "velocity": (body.velocity.x, body.velocity.y, body.velocity.z),
                    "type": body.body_type.name,
                    "sleeping": body.is_sleeping,
                }
            )

        contacts_data = []
        for contact in self.contacts:
            contacts_data.append(
                {
                    "body_a_id": contact.body_a.body_id,
                    "body_b_id": contact.body_b.body_id,
                    "contact_point": (
                        contact.manifold.contact_point.x,
                        contact.manifold.contact_point.y,
                        contact.manifold.contact_point.z,
                    ),
                    "penetration_depth": contact.manifold.penetration_depth,
                }
            )

        return {
            "bodies": bodies_data,
            "contacts": contacts_data,
            "statistics": self.get_statistics(),
        }
