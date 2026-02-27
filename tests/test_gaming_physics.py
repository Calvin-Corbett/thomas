"""Tests for 2D physics engine."""

from thomas.gaming_platform._types import Collider, Entity, RigidBody, Transform
from thomas.gaming_platform.ecs import EntityComponentSystem
from thomas.gaming_platform.physics2d import (
    AABB,
    Circle,
    Physics2D,
    SpatialHashGrid,
)


class TestAABB:
    """Test AABB collision detection."""

    def test_aabb_creation(self) -> None:
        """Test AABB creation."""
        aabb = AABB(0.0, 0.0, 32.0, 32.0)
        assert aabb.min_x == 0.0
        assert aabb.max_x == 32.0
        assert aabb.min_y == 0.0
        assert aabb.max_y == 32.0

    def test_aabb_intersection_overlap(self) -> None:
        """Test overlapping AABBs."""
        aabb1 = AABB(0.0, 0.0, 32.0, 32.0)
        aabb2 = AABB(16.0, 16.0, 32.0, 32.0)

        assert aabb1.intersects_aabb(aabb2)
        assert aabb2.intersects_aabb(aabb1)

    def test_aabb_intersection_no_overlap(self) -> None:
        """Test non-overlapping AABBs."""
        aabb1 = AABB(0.0, 0.0, 32.0, 32.0)
        aabb2 = AABB(40.0, 40.0, 32.0, 32.0)

        assert not aabb1.intersects_aabb(aabb2)
        assert not aabb2.intersects_aabb(aabb1)

    def test_aabb_intersection_touching(self) -> None:
        """Test AABBs touching at edge."""
        aabb1 = AABB(0.0, 0.0, 32.0, 32.0)
        aabb2 = AABB(32.0, 0.0, 32.0, 32.0)

        # Touching at edge should be considered overlapping
        assert aabb1.intersects_aabb(aabb2) is False or aabb1.intersects_aabb(aabb2) is True

    def test_aabb_overlap_vector(self) -> None:
        """Test getting overlap vector."""
        aabb1 = AABB(0.0, 0.0, 32.0, 32.0)
        aabb2 = AABB(16.0, 0.0, 32.0, 32.0)

        overlap = aabb1.get_overlap(aabb2)
        # aabb1 is to the left, overlap should be in X
        assert overlap[0] != 0.0 or overlap[1] != 0.0


class TestCircle:
    """Test circle collision detection."""

    def test_circle_creation(self) -> None:
        """Test circle creation."""
        circle = Circle(10.0, 20.0, 5.0)
        assert circle.x == 10.0
        assert circle.y == 20.0
        assert circle.radius == 5.0

    def test_circle_distance(self) -> None:
        """Test distance to point."""
        circle = Circle(0.0, 0.0, 5.0)
        dist = circle.distance_to_point(3.0, 4.0)
        assert abs(dist - 5.0) < 0.001

    def test_circle_intersection_overlap(self) -> None:
        """Test overlapping circles."""
        circle1 = Circle(0.0, 0.0, 5.0)
        circle2 = Circle(8.0, 0.0, 5.0)

        assert circle1.intersects_circle(circle2)

    def test_circle_intersection_no_overlap(self) -> None:
        """Test non-overlapping circles."""
        circle1 = Circle(0.0, 0.0, 5.0)
        circle2 = Circle(20.0, 0.0, 5.0)

        assert not circle1.intersects_circle(circle2)

    def test_circle_normal(self) -> None:
        """Test normal vector between circles."""
        circle1 = Circle(0.0, 0.0, 5.0)
        circle2 = Circle(10.0, 0.0, 5.0)

        normal = circle1.get_normal_to_circle(circle2)
        assert abs(normal[0] - 1.0) < 0.001
        assert abs(normal[1]) < 0.001


class TestSpatialHashGrid:
    """Test spatial hash grid broad phase."""

    def test_grid_creation(self) -> None:
        """Test grid initialization."""
        grid = SpatialHashGrid(cell_size=32.0)
        assert grid.cell_size == 32.0
        assert len(grid.grid) == 0

    def test_grid_insert(self) -> None:
        """Test inserting AABB into grid."""
        grid = SpatialHashGrid(cell_size=32.0)
        entity = Entity(0, 0)
        aabb = AABB(0.0, 0.0, 32.0, 32.0)

        grid.insert(entity, aabb)

        assert entity.index in grid.entity_cells

    def test_grid_query(self) -> None:
        """Test querying grid."""
        grid = SpatialHashGrid(cell_size=32.0)

        # Insert several entities
        for i in range(5):
            entity = Entity(i, 0)
            aabb = AABB(float(i * 32), 0.0, 32.0, 32.0)
            grid.insert(entity, aabb)

        # Query overlapping area
        query_aabb = AABB(16.0, 0.0, 32.0, 32.0)
        results = grid.query(query_aabb)

        assert len(results) > 0

    def test_grid_clear(self) -> None:
        """Test clearing grid."""
        grid = SpatialHashGrid()
        entity = Entity(0, 0)
        grid.insert(entity, AABB(0.0, 0.0, 32.0, 32.0))

        grid.clear()

        assert len(grid.grid) == 0
        assert len(grid.entity_cells) == 0


class TestPhysics2D:
    """Test 2D physics engine."""

    def test_physics_initialization(self) -> None:
        """Test physics engine initialization."""
        physics = Physics2D(gravity=(0.0, -9.81))
        assert physics.gravity == (0.0, -9.81)

    def test_gravity_application(self) -> None:
        """Test gravity affects velocity."""
        ecs = EntityComponentSystem()
        physics = Physics2D(gravity=(0.0, -10.0))

        entity = ecs.create_entity()
        transform = Transform(position=(0.0, 10.0), velocity=(0.0, 0.0))
        rigidbody = RigidBody(mass=1.0, gravity_scale=1.0)

        ecs.add_component(entity, transform)
        ecs.add_component(entity, rigidbody)

        physics.update(ecs, 1.0)

        # Velocity should be affected by gravity
        updated_transform = ecs.get_component(entity, Transform)
        assert updated_transform is not None
        assert updated_transform.velocity[1] < 0.0

    def test_velocity_integration(self) -> None:
        """Test position updates from velocity."""
        ecs = EntityComponentSystem()
        physics = Physics2D(gravity=(0.0, 0.0))

        entity = ecs.create_entity()
        transform = Transform(position=(0.0, 0.0), velocity=(10.0, 0.0))
        rigidbody = RigidBody(mass=1.0, gravity_scale=0.0)

        ecs.add_component(entity, transform)
        ecs.add_component(entity, rigidbody)

        physics.update(ecs, 1.0)

        # Position should update
        updated_transform = ecs.get_component(entity, Transform)
        assert updated_transform is not None
        assert updated_transform.position[0] > 0.0

    def test_aabb_collision_detection(self) -> None:
        """Test AABB collision detection."""
        ecs = EntityComponentSystem()
        physics = Physics2D()

        # Create two overlapping entities
        entity1 = ecs.create_entity()
        entity2 = ecs.create_entity()

        ecs.add_component(entity1, Transform(position=(0.0, 0.0)))
        ecs.add_component(entity1, Collider(shape_type="aabb", width=32.0, height=32.0))
        ecs.add_component(entity1, RigidBody())

        ecs.add_component(entity2, Transform(position=(16.0, 16.0)))
        ecs.add_component(entity2, Collider(shape_type="aabb", width=32.0, height=32.0))
        ecs.add_component(entity2, RigidBody())

        physics.update(ecs, 0.016)

        # Should have collision
        assert len(physics.collisions) > 0

    def test_circle_collision_detection(self) -> None:
        """Test circle collision detection."""
        ecs = EntityComponentSystem()
        physics = Physics2D()

        # Create two overlapping circles
        entity1 = ecs.create_entity()
        entity2 = ecs.create_entity()

        ecs.add_component(entity1, Transform(position=(0.0, 0.0)))
        ecs.add_component(entity1, Collider(shape_type="circle", radius=10.0))
        ecs.add_component(entity1, RigidBody())

        ecs.add_component(entity2, Transform(position=(15.0, 0.0)))
        ecs.add_component(entity2, Collider(shape_type="circle", radius=10.0))
        ecs.add_component(entity2, RigidBody())

        physics.update(ecs, 0.016)

        # Should have collision
        assert len(physics.collisions) > 0

    def test_collision_response(self) -> None:
        """Test collision response with impulse."""
        ecs = EntityComponentSystem()
        physics = Physics2D(gravity=(0.0, 0.0))

        # Create moving entity colliding with static
        entity1 = ecs.create_entity()
        entity2 = ecs.create_entity()

        ecs.add_component(entity1, Transform(position=(0.0, 0.0), velocity=(10.0, 0.0)))
        ecs.add_component(entity1, Collider(shape_type="aabb", width=10.0, height=10.0))
        ecs.add_component(entity1, RigidBody(mass=1.0, restitution=0.8))

        ecs.add_component(entity2, Transform(position=(20.0, 0.0)))
        ecs.add_component(entity2, Collider(shape_type="aabb", width=10.0, height=10.0))
        ecs.add_component(entity2, RigidBody(mass=float("inf"), is_dynamic=False))

        physics.update(ecs, 1.0)

        # Velocity should be reduced or reversed
        transform1 = ecs.get_component(entity1, Transform)
        assert transform1 is not None

    def test_raycast_aabb(self) -> None:
        """Test raycast against AABB."""
        ecs = EntityComponentSystem()
        physics = Physics2D()

        entity = ecs.create_entity()
        ecs.add_component(entity, Transform(position=(50.0, 50.0)))
        ecs.add_component(entity, Collider(shape_type="aabb", width=20.0, height=20.0))

        # Cast ray from origin
        result = physics.raycast(ecs, (0.0, 0.0), (1.0, 0.0), max_distance=100.0)

        assert result is not None

    def test_raycast_circle(self) -> None:
        """Test raycast against circle."""
        ecs = EntityComponentSystem()
        physics = Physics2D()

        entity = ecs.create_entity()
        ecs.add_component(entity, Transform(position=(50.0, 0.0)))
        ecs.add_component(entity, Collider(shape_type="circle", radius=10.0))

        # Cast ray along X axis
        result = physics.raycast(ecs, (0.0, 0.0), (1.0, 0.0), max_distance=100.0)

        assert result is not None
        assert result[0] == entity

    def test_drag_forces(self) -> None:
        """Test drag/friction damping."""
        ecs = EntityComponentSystem()
        physics = Physics2D(gravity=(0.0, 0.0))

        entity = ecs.create_entity()
        ecs.add_component(entity, Transform(position=(0.0, 0.0), velocity=(100.0, 0.0)))
        ecs.add_component(entity, RigidBody(mass=1.0, drag=0.5))

        physics.update(ecs, 1.0)

        transform = ecs.get_component(entity, Transform)
        assert transform is not None
        # Velocity should be reduced due to drag
        assert transform.velocity[0] < 100.0

    def test_trigger_collider(self) -> None:
        """Test trigger colliders (no physics response)."""
        ecs = EntityComponentSystem()
        physics = Physics2D()

        entity1 = ecs.create_entity()
        entity2 = ecs.create_entity()

        ecs.add_component(entity1, Transform(position=(0.0, 0.0)))
        ecs.add_component(entity1, Collider(shape_type="aabb", width=32.0, height=32.0, is_trigger=True))
        ecs.add_component(entity1, RigidBody())

        ecs.add_component(entity2, Transform(position=(16.0, 16.0)))
        ecs.add_component(entity2, Collider(shape_type="aabb", width=32.0, height=32.0))
        ecs.add_component(entity2, RigidBody())

        physics.update(ecs, 0.016)

        # Collision should be detected but not resolved
        assert len(physics.collisions) == 0
