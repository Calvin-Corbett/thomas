"""Tests for Entity Component System."""

import pytest

from thomas.gaming_platform._exceptions import ComponentError, EntityError
from thomas.gaming_platform._types import Component, Entity, Transform
from thomas.gaming_platform.ecs import EntityComponentSystem, SparseSet


class HealthComponent(Component):
    """Test component for health."""

    def __init__(self, health: float = 100.0) -> None:
        """Initialize health component."""
        self.health = health

    def clone(self) -> "HealthComponent":
        """Clone component."""
        return HealthComponent(self.health)


class VelocityComponent(Component):
    """Test component for velocity."""

    def __init__(self, vx: float = 0.0, vy: float = 0.0) -> None:
        """Initialize velocity component."""
        self.vx = vx
        self.vy = vy

    def clone(self) -> "VelocityComponent":
        """Clone component."""
        return VelocityComponent(self.vx, self.vy)


class TestSparseSet:
    """Test sparse set data structure."""

    def test_insert_and_get(self) -> None:
        """Test inserting and retrieving components."""
        sparse_set = SparseSet()
        entity = Entity(0, 0)
        component = HealthComponent(80.0)

        sparse_set.insert(entity, component)
        retrieved = sparse_set.get(entity)

        assert retrieved is not None
        assert retrieved.health == 80.0

    def test_contains(self) -> None:
        """Test checking if entity has component."""
        sparse_set = SparseSet()
        entity1 = Entity(0, 0)
        entity2 = Entity(1, 0)
        component = HealthComponent()

        sparse_set.insert(entity1, component)

        assert sparse_set.contains(entity1)
        assert not sparse_set.contains(entity2)

    def test_remove(self) -> None:
        """Test removing components."""
        sparse_set = SparseSet()
        entity1 = Entity(0, 0)
        entity2 = Entity(1, 0)

        sparse_set.insert(entity1, HealthComponent(100.0))
        sparse_set.insert(entity2, HealthComponent(50.0))

        sparse_set.remove(entity1)

        assert not sparse_set.contains(entity1)
        assert sparse_set.contains(entity2)
        assert len(sparse_set.dense) == 1

    def test_iteration(self) -> None:
        """Test iterating over components."""
        sparse_set = SparseSet()

        for i in range(5):
            entity = Entity(i, 0)
            component = HealthComponent(float(100 - i * 10))
            sparse_set.insert(entity, component)

        components = sparse_set.iter_components()
        assert len(components) == 5

        entities = sparse_set.iter_entities()
        assert len(entities) == 5

    def test_clear(self) -> None:
        """Test clearing sparse set."""
        sparse_set = SparseSet()

        for i in range(3):
            entity = Entity(i, 0)
            sparse_set.insert(entity, HealthComponent())

        sparse_set.clear()

        assert len(sparse_set.dense) == 0
        assert len(sparse_set.sparse) == 0


class TestEntityComponentSystem:
    """Test Entity Component System."""

    def test_create_entity(self) -> None:
        """Test entity creation."""
        ecs = EntityComponentSystem()
        entity1 = ecs.create_entity()
        entity2 = ecs.create_entity()

        assert entity1.index != entity2.index
        assert entity1.generation == 0
        assert entity2.generation == 0

    def test_destroy_entity(self) -> None:
        """Test entity destruction and recycling."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        index = entity.index

        ecs.destroy_entity(entity)

        # Index should be recycled
        assert index in ecs.free_entities

        # Old entity should be invalid
        assert not ecs.has_component(entity, Transform)

    def test_destroy_invalid_entity(self) -> None:
        """Test destroying invalid entity raises error."""
        ecs = EntityComponentSystem()
        entity = Entity(999, 0)

        with pytest.raises(EntityError):
            ecs.destroy_entity(entity)

    def test_add_component(self) -> None:
        """Test adding components to entity."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        component = HealthComponent(75.0)

        ecs.add_component(entity, component)

        assert ecs.has_component(entity, HealthComponent)

    def test_add_duplicate_component(self) -> None:
        """Test adding duplicate component type raises error."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        ecs.add_component(entity, HealthComponent(100.0))

        with pytest.raises(ComponentError):
            ecs.add_component(entity, HealthComponent(50.0))

    def test_get_component(self) -> None:
        """Test retrieving components."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        component = HealthComponent(85.0)

        ecs.add_component(entity, component)
        retrieved = ecs.get_component(entity, HealthComponent)

        assert retrieved is not None
        assert retrieved.health == 85.0

    def test_get_missing_component(self) -> None:
        """Test getting non-existent component returns None."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        result = ecs.get_component(entity, HealthComponent)
        assert result is None

    def test_remove_component(self) -> None:
        """Test removing components."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        ecs.add_component(entity, HealthComponent())
        assert ecs.has_component(entity, HealthComponent)

        ecs.remove_component(entity, HealthComponent)
        assert not ecs.has_component(entity, HealthComponent)

    def test_query_single_component(self) -> None:
        """Test querying entities with single component."""
        ecs = EntityComponentSystem()

        for i in range(5):
            entity = ecs.create_entity()
            if i % 2 == 0:
                ecs.add_component(entity, HealthComponent())

        results = ecs.query(HealthComponent)
        assert len(results) == 3

    def test_query_multiple_components(self) -> None:
        """Test querying entities with multiple components."""
        ecs = EntityComponentSystem()

        for i in range(5):
            entity = ecs.create_entity()
            ecs.add_component(entity, HealthComponent())
            if i % 2 == 0:
                ecs.add_component(entity, VelocityComponent())

        results = ecs.query(HealthComponent, VelocityComponent)
        assert len(results) == 3

    def test_query_empty(self) -> None:
        """Test querying with no components returns empty."""
        ecs = EntityComponentSystem()
        results = ecs.query()
        assert len(results) == 0

    def test_prefab_system(self) -> None:
        """Test entity prefabs."""
        ecs = EntityComponentSystem()

        # Create prefab
        template = [HealthComponent(100.0), VelocityComponent(10.0, 5.0)]
        ecs.add_prefab("player", template)

        # Instantiate
        entity = ecs.instantiate_prefab("player")

        assert entity is not None
        assert ecs.has_component(entity, HealthComponent)
        assert ecs.has_component(entity, VelocityComponent)

        # Verify values
        health = ecs.get_component(entity, HealthComponent)
        assert health is not None
        assert health.health == 100.0

    def test_prefab_not_found(self) -> None:
        """Test instantiating non-existent prefab."""
        ecs = EntityComponentSystem()
        entity = ecs.instantiate_prefab("nonexistent")
        assert entity is None

    def test_world_snapshot(self) -> None:
        """Test saving and loading world snapshot."""
        ecs = EntityComponentSystem()

        # Create entities with components
        for i in range(3):
            entity = ecs.create_entity()
            ecs.add_component(entity, HealthComponent(100.0 - i * 10))
            ecs.add_component(entity, VelocityComponent(float(i), float(i)))

        # Save snapshot
        snapshot = ecs.save_snapshot()
        assert "components" in snapshot

        # Create new ECS and load
        ecs2 = EntityComponentSystem()
        ecs2.load_snapshot(snapshot)

        # Verify loaded data
        results = ecs2.query(HealthComponent, VelocityComponent)
        assert len(results) == 3

    def test_generation_indices(self) -> None:
        """Test generational indices prevent use-after-free."""
        ecs = EntityComponentSystem()

        entity1 = ecs.create_entity()
        index = entity1.index
        gen = entity1.generation

        ecs.destroy_entity(entity1)

        # Create new entity with same index
        entity2 = ecs.create_entity()

        # Old entity should be invalid
        assert not ecs.has_component(entity1, HealthComponent)

        # New entity should work
        ecs.add_component(entity2, HealthComponent())
        assert ecs.has_component(entity2, HealthComponent)

    def test_get_world_stats(self) -> None:
        """Test world statistics."""
        ecs = EntityComponentSystem()

        for i in range(5):
            entity = ecs.create_entity()
            ecs.add_component(entity, HealthComponent())

        stats = ecs.get_world_stats()

        assert "entity_count" in stats
        assert "component_types" in stats
        assert stats["component_types"] >= 1

    def test_component_type_isolation(self) -> None:
        """Test components are isolated by type."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        ecs.add_component(entity, HealthComponent(100.0))
        ecs.add_component(entity, VelocityComponent(1.0, 2.0))

        health = ecs.get_component(entity, HealthComponent)
        velocity = ecs.get_component(entity, VelocityComponent)

        assert health.health == 100.0
        assert velocity.vx == 1.0
        assert velocity.vy == 2.0

    def test_large_entity_pool(self) -> None:
        """Test ECS with many entities."""
        ecs = EntityComponentSystem(initial_capacity=16)

        entities = []
        for i in range(100):
            entity = ecs.create_entity()
            ecs.add_component(entity, HealthComponent(float(i)))
            entities.append(entity)

        # Verify all created
        assert len([e for e in entities if ecs.has_component(e, HealthComponent)]) == 100

        # Destroy some
        for entity in entities[::2]:
            ecs.destroy_entity(entity)

        # Verify count
        results = ecs.query(HealthComponent)
        assert len(results) == 50
