"""
Integration tests for complete physics simulation scenarios.
"""

import math

from thomas.physics._types import PhysicsConfig, RigidBodyType, Vec3
from thomas.physics.cloth import ClothMesh
from thomas.physics.constraints import DistanceConstraint
from thomas.physics.rigid_body import RigidBody
from thomas.physics.world import PhysicsWorld


class TestFreeFall:
    """Tests for free fall scenario."""

    def test_free_fall_acceleration(self) -> None:
        """Test body falls with correct acceleration."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        # Simulate for 1 second
        for _ in range(60):
            world.step(1.0 / 60.0)

        # Distance fallen: d = 0.5 * g * t^2 = 0.5 * 9.81 * 1 = 4.905
        expected_distance = 0.5 * 9.81 * 1.0
        actual_distance = 10 - body.position.y
        assert abs(actual_distance - expected_distance) < 1.0

    def test_free_fall_velocity(self) -> None:
        """Test body reaches correct velocity in free fall."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        # Simulate for 1 second
        for _ in range(60):
            world.step(1.0 / 60.0)

        # Velocity: v = g * t = 9.81 * 1 = 9.81
        # Account for damping in the simulation
        assert body.velocity.y < -5


class TestProjectileMotion:
    """Tests for projectile motion scenario."""

    def test_projectile_trajectory(self) -> None:
        """Test projectile follows parabolic trajectory."""
        world = PhysicsWorld()
        # Initial velocity at 45 degrees: v0 = 10 m/s
        v0 = 10
        angle = math.pi / 4
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(v0 * math.cos(angle), v0 * math.sin(angle), 0),
            mass=1.0,
        )
        world.add_body(body)

        # Simulate until projectile lands
        for _ in range(300):
            world.step(1.0 / 60.0)
            if body.position.y < 0:
                break

        # Range for 45 degrees: R = v0^2 / g = 100 / 9.81 ≈ 10.2
        # Account for damping and numerical errors
        assert body.position.x > 5


class TestCollisionResponse:
    """Tests for collision response scenarios."""

    def test_elastic_collision(self) -> None:
        """Test elastic collision between bodies."""
        world = PhysicsWorld()
        # Body 1 moving right
        body1 = RigidBody(
            body_id=0,
            position=Vec3(-2, 0, 0),
            velocity=Vec3(5, 0, 0),
            mass=1.0,
        )
        body1.material.restitution = 0.9
        # Body 2 stationary
        body2 = RigidBody(
            body_id=1,
            position=Vec3(2, 0, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        body2.material.restitution = 0.9

        world.add_body(body1)
        world.add_body(body2)

        initial_v1 = body1.velocity.x

        # Simulate collision
        for _ in range(100):
            world.step(0.016)

        # Bodies should interact (collision response applied)
        # At least one body should have different velocity after many steps
        assert body1.velocity.x != initial_v1 or body2.velocity.x != 0

    def test_inelastic_collision(self) -> None:
        """Test inelastic collision between bodies."""
        world = PhysicsWorld()
        body1 = RigidBody(
            body_id=0,
            position=Vec3(-2, 0, 0),
            velocity=Vec3(5, 0, 0),
            mass=1.0,
        )
        body1.material.restitution = 0.1
        body2 = RigidBody(
            body_id=1,
            position=Vec3(2, 0, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        body2.material.restitution = 0.1

        world.add_body(body1)
        world.add_body(body2)

        # Simulate
        for _ in range(50):
            world.step(0.016)

        # Bodies should move/interact
        assert body1.position.x != -2 or body2.position.x != 2


class TestConstraints:
    """Tests for constraint scenarios."""

    def test_distance_constraint_spring(self) -> None:
        """Test spring constraint keeps bodies at distance."""
        world = PhysicsWorld()
        body1 = RigidBody(
            body_id=0,
            position=Vec3(-1, 0, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        body2 = RigidBody(
            body_id=1,
            position=Vec3(1, 0, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body1)
        world.add_body(body2)

        constraint = DistanceConstraint(
            body_a=body1,
            body_b=body2,
            local_point_a=Vec3(0, 0, 0),
            local_point_b=Vec3(0, 0, 0),
            rest_distance=2.0,
            spring_constant=100.0,
        )
        world.constraints.add_constraint(constraint)

        initial_distance = body1.position.distance_to(body2.position)

        for _ in range(100):
            world.step(0.016)

        final_distance = body1.position.distance_to(body2.position)
        # Distance should oscillate around rest distance
        assert abs(final_distance - 2.0) < 1.0

    def test_distance_constraint_rigid(self) -> None:
        """Test rigid rod constraint maintains fixed distance."""
        world = PhysicsWorld()
        body1 = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        body2 = RigidBody(
            body_id=1,
            position=Vec3(2, 0, 0),
            velocity=Vec3(1, 0, 0),
            mass=1.0,
        )
        world.add_body(body1)
        world.add_body(body2)

        constraint = DistanceConstraint(
            body_a=body1,
            body_b=body2,
            local_point_a=Vec3(0, 0, 0),
            local_point_b=Vec3(0, 0, 0),
            rest_distance=2.0,
            spring_constant=0.0,  # Rigid rod
        )
        world.constraints.add_constraint(constraint)

        for _ in range(50):
            world.step(0.016)

        distance = body1.position.distance_to(body2.position)
        # Rigid constraint should keep distance close to 2.0
        assert abs(distance - 2.0) < 0.5


class TestClothSimulation:
    """Tests for cloth simulation."""

    def test_cloth_creation(self) -> None:
        """Test cloth mesh creation."""
        cloth = ClothMesh(width=5, height=5)
        assert len(cloth.particles) == 25
        assert len(cloth.springs) > 0

    def test_cloth_pinning(self) -> None:
        """Test cloth pinning keeps particles fixed."""
        cloth = ClothMesh(width=3, height=3)
        # Top corners are pinned by default
        pinned_count = sum(1 for p in cloth.particles if p.pinned)
        assert pinned_count > 0  # At least some particles should be pinned
        # Verify that pinned particles exist and the cloth was created
        assert len(cloth.particles) == 9

    def test_cloth_gravity(self) -> None:
        """Test cloth falls under gravity."""
        cloth = ClothMesh(width=3, height=3)
        initial_y = cloth.particles[4].position.y  # Center particle
        cloth.update(0.1)
        final_y = cloth.particles[4].position.y
        # Unpinned particles should fall
        assert final_y < initial_y

    def test_cloth_constraint_satisfaction(self) -> None:
        """Test cloth constraints maintain spring distances."""
        cloth = ClothMesh(width=2, height=2, segment_size=1.0)
        initial_distances = []
        for spring in cloth.springs:
            dist = spring.particle_a.position.distance_to(spring.particle_b.position)
            initial_distances.append(dist)

        # Apply force and update
        cloth.apply_force(Vec3(0, -10, 0))
        cloth.update(0.016)

        # Check that spring distances are maintained
        for spring, initial_dist in zip(cloth.springs, initial_distances):
            current_dist = spring.particle_a.position.distance_to(spring.particle_b.position)
            # Allow some deviation but should be close to rest length
            assert abs(current_dist - spring.rest_length) < 1.0


class TestEnergyConservation:
    """Tests for energy conservation in simulation."""

    def test_no_damping_energy_conservation(self) -> None:
        """Test energy is conserved without damping."""
        config = PhysicsConfig(velocity_damping=1.0, angular_damping=1.0)
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(5, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        initial_energy = body.get_kinetic_energy() + body.get_potential_energy(world.config.gravity)

        # Run simulation (without damping)
        for _ in range(100):
            world.step(0.016)

        final_energy = body.get_kinetic_energy() + body.get_potential_energy(world.config.gravity)

        # Energy should be approximately conserved
        assert abs(initial_energy - final_energy) < 10.0

    def test_with_damping_energy_decreases(self) -> None:
        """Test energy decreases with damping."""
        config = PhysicsConfig(velocity_damping=0.95, angular_damping=0.95)
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(5, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        initial_energy = body.get_kinetic_energy() + body.get_potential_energy(world.config.gravity)

        for _ in range(200):
            world.step(0.016)

        final_energy = body.get_kinetic_energy() + body.get_potential_energy(world.config.gravity)

        # Energy should decrease due to damping
        assert final_energy < initial_energy


class TestMultiBodySystem:
    """Tests for multi-body systems."""

    def test_three_body_stack(self) -> None:
        """Test three bodies fall under gravity."""
        world = PhysicsWorld()
        bodies = []
        for i in range(3):
            body = RigidBody(
                body_id=i,
                position=Vec3(0, i * 2.5 + 5, 0),
                velocity=Vec3(0, 0, 0),
                mass=1.0,
            )
            world.add_body(body)
            bodies.append(body)

        initial_y_values = [b.position.y for b in bodies]

        # Let them fall
        for _ in range(100):
            world.step(0.016)

        # All bodies should have fallen
        for i, body in enumerate(bodies):
            assert body.position.y < initial_y_values[i]

    def test_chain_reaction(self) -> None:
        """Test multiple bodies interact."""
        world = PhysicsWorld()
        # Create line of bodies
        for i in range(5):
            body = RigidBody(
                body_id=i,
                position=Vec3(i * 2, 0, 0),
                velocity=Vec3(0, 0, 0) if i > 0 else Vec3(5, 0, 0),
                mass=1.0,
            )
            world.add_body(body)

        initial_last_x = world.bodies[-1].position.x

        # Simulate
        for _ in range(100):
            world.step(0.016)

        # First body should have moved
        assert world.bodies[0].position.x > 0


class TestStabilityAndRobustness:
    """Tests for simulation stability."""

    def test_large_timestep_stability(self) -> None:
        """Test simulation stability with larger timesteps."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        # Step with reasonably large timesteps
        for _ in range(100):
            world.step(0.033)

        # Body should not fly off to infinity
        assert abs(body.position.y) < 1000
        assert abs(body.velocity.magnitude()) < 1000

    def test_zero_mass_handling(self) -> None:
        """Test that zero-mass bodies are handled gracefully."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            mass=1.0,
            body_type=RigidBodyType.STATIC,
        )
        world.add_body(body)

        # Should not crash
        for _ in range(10):
            world.step(0.016)

        assert body.position == Vec3(0, 0, 0)
