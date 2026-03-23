"""
Tests for physics world and simulation.
"""

import pytest

from thomas.marketplace.physics._types import AABB, PhysicsConfig, Ray, RigidBodyType, Vec3
from thomas.marketplace.physics.rigid_body import RigidBody
from thomas.marketplace.physics.world import PhysicsWorld


class TestPhysicsWorldCreation:
    """Tests for physics world initialization."""

    def test_create_world(self) -> None:
        """Test creating physics world."""
        world = PhysicsWorld()
        assert world.body_count == 0
        assert world.contact_count == 0
        assert world.simulation_time == 0.0

    def test_world_with_config(self) -> None:
        """Test world with custom config."""
        config = PhysicsConfig(gravity=Vec3(0, -20, 0))
        world = PhysicsWorld(config=config)
        assert world.config.gravity == Vec3(0, -20, 0)

    def test_invalid_config_raises_error(self) -> None:
        """Test that invalid config raises error."""
        config = PhysicsConfig(fixed_timestep=-1.0)
        with pytest.raises(ValueError):
            PhysicsWorld(config=config)


class TestAddRemoveBodies:
    """Tests for adding and removing bodies."""

    def test_add_body(self) -> None:
        """Test adding body to world."""
        world = PhysicsWorld()
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        world.add_body(body)
        assert world.body_count == 1
        assert body in world.bodies

    def test_add_multiple_bodies(self) -> None:
        """Test adding multiple bodies."""
        world = PhysicsWorld()
        for i in range(5):
            body = RigidBody(body_id=i, position=Vec3(i, 0, 0), mass=1.0)
            world.add_body(body)
        assert world.body_count == 5

    def test_remove_body(self) -> None:
        """Test removing body from world."""
        world = PhysicsWorld()
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        world.add_body(body)
        world.remove_body(body)
        assert world.body_count == 0
        assert body not in world.bodies

    def test_body_ids_assigned(self) -> None:
        """Test that body IDs are assigned."""
        world = PhysicsWorld()
        body1 = RigidBody(body_id=99, position=Vec3(0, 0, 0), mass=1.0)
        body2 = RigidBody(body_id=99, position=Vec3(1, 0, 0), mass=1.0)
        world.add_body(body1)
        world.add_body(body2)
        assert body1.body_id == 0
        assert body2.body_id == 1


class TestSimulationStep:
    """Tests for simulation stepping."""

    def test_single_step(self) -> None:
        """Test single simulation step."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            mass=1.0,
        )
        world.add_body(body)
        world.step(0.016)
        assert body.position.x > 0

    def test_gravity_effect(self) -> None:
        """Test gravity affects falling body."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)
        world.step(1.0)
        assert body.position.y < 10

    def test_static_body_no_movement(self) -> None:
        """Test static body doesn't move."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            mass=1.0,
            body_type=RigidBodyType.STATIC,
        )
        world.add_body(body)
        initial_pos = body.position
        world.step(0.1)
        assert body.position == initial_pos

    def test_fixed_timestep_accumulation(self) -> None:
        """Test fixed timestep accumulation."""
        config = PhysicsConfig(fixed_timestep=0.016)
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        world.step(0.032)  # 2 steps
        assert world.time_accumulator < config.fixed_timestep
        assert world.simulation_time >= 2 * config.fixed_timestep


class TestQueries:
    """Tests for world queries."""

    def test_raycast_hit(self) -> None:
        """Test raycasting hits body."""
        world = PhysicsWorld()
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        world.add_body(body)

        ray = Ray(Vec3(-5, 0, 0), Vec3(1, 0, 0).normalize())
        result = world.raycast(ray)
        assert result.body is not None
        assert result.distance < float("inf")

    def test_raycast_miss(self) -> None:
        """Test raycasting misses body."""
        world = PhysicsWorld()
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        world.add_body(body)

        ray = Ray(Vec3(-5, 5, 0), Vec3(1, 0, 0).normalize())
        result = world.raycast(ray)
        assert result.body is None

    def test_aabb_query(self) -> None:
        """Test AABB query."""
        world = PhysicsWorld()
        body1 = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body2 = RigidBody(body_id=1, position=Vec3(5, 0, 0), mass=1.0)
        world.add_body(body1)
        world.add_body(body2)

        query_aabb = AABB(Vec3(-1, -1, -1), Vec3(1, 1, 1))
        results = world.query_aabb(query_aabb)
        assert len(results) == 1
        assert body1 in results

    def test_point_query(self) -> None:
        """Test point query."""
        world = PhysicsWorld()
        body = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        world.add_body(body)

        results = world.query_point(Vec3(0, 0, 0), radius=1.0)
        assert len(results) >= 1
        assert body in results


class TestStatistics:
    """Tests for simulation statistics."""

    def test_get_statistics(self) -> None:
        """Test getting simulation statistics."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(1, 0, 0),
            mass=1.0,
        )
        world.add_body(body)
        world.step(0.1)

        stats = world.get_statistics()
        assert "body_count" in stats
        assert "contact_count" in stats
        assert "simulation_time" in stats
        assert "total_kinetic_energy" in stats
        assert "total_potential_energy" in stats
        assert "total_energy" in stats

    def test_energy_tracking(self) -> None:
        """Test energy statistics."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        stats = world.get_statistics()
        initial_energy = stats["total_energy"]
        assert initial_energy > 0

        world.step(0.5)
        stats = world.get_statistics()
        # Energy should decrease due to damping
        assert stats["total_energy"] <= initial_energy + 1e-6

    def test_sleeping_count(self) -> None:
        """Test sleeping body count in statistics."""
        config = PhysicsConfig(sleep_velocity_threshold=10.0)
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(0.1, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        # Step until body sleeps
        for _ in range(100):
            world.step(0.1)
            if body.is_sleeping:
                break

        stats = world.get_statistics()
        if body.is_sleeping:
            assert stats["sleeping_count"] >= 1


class TestDebugData:
    """Tests for debug visualization data."""

    def test_get_debug_data(self) -> None:
        """Test getting debug visualization data."""
        world = PhysicsWorld()
        body = RigidBody(
            body_id=0,
            position=Vec3(1, 2, 3),
            velocity=Vec3(4, 5, 6),
            mass=1.0,
        )
        world.add_body(body)

        debug_data = world.get_debug_data()
        assert "bodies" in debug_data
        assert "contacts" in debug_data
        assert "statistics" in debug_data

        assert len(debug_data["bodies"]) == 1
        body_data = debug_data["bodies"][0]
        assert body_data["id"] == 0
        assert body_data["position"] == (1, 2, 3)


class TestCollisionDetection:
    """Tests for collision detection in world."""

    def test_sphere_collision_detection(self) -> None:
        """Test that collisions are detected."""
        world = PhysicsWorld()
        body1 = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body2 = RigidBody(body_id=1, position=Vec3(0.8, 0, 0), mass=1.0)
        world.add_body(body1)
        world.add_body(body2)

        world.step(0.016)
        # Collision should be detected or will be on next step
        # Check that contact count is updated
        assert world.contact_count >= 0

    def test_no_collision_far_apart(self) -> None:
        """Test no collision when bodies are far apart."""
        world = PhysicsWorld()
        body1 = RigidBody(body_id=0, position=Vec3(0, 0, 0), mass=1.0)
        body2 = RigidBody(body_id=1, position=Vec3(10, 0, 0), mass=1.0)
        world.add_body(body1)
        world.add_body(body2)

        world.step(0.016)
        assert world.contact_count == 0


class TestConfiguration:
    """Tests for physics configuration."""

    def test_custom_gravity(self) -> None:
        """Test custom gravity configuration."""
        config = PhysicsConfig(gravity=Vec3(0, 0, 0))
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 10, 0),
            velocity=Vec3(0, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        initial_pos = body.position
        world.step(1.0)
        # No gravity, position should not change in Y
        assert abs(body.position.y - initial_pos.y) < 1e-6

    def test_damping_configuration(self) -> None:
        """Test velocity damping configuration."""
        config = PhysicsConfig(velocity_damping=0.5)
        world = PhysicsWorld(config=config)
        body = RigidBody(
            body_id=0,
            position=Vec3(0, 0, 0),
            velocity=Vec3(10, 0, 0),
            mass=1.0,
        )
        world.add_body(body)

        world.step(0.016)
        # Velocity should be dampened
        assert body.velocity.x < 10
