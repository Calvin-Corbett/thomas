"""Entity Component System (ECS) implementation with generational indices and sparse sets."""

import copy
from collections.abc import Callable
from typing import Any

from thomas.gaming_platform._exceptions import ComponentError, EntityError, SystemError
from thomas.gaming_platform._types import Component, Entity, System


class SparseSet:
    """
    Efficient storage for sparse component data using the sparse set pattern.

    Maps entity IDs to component data with O(1) lookup and cache-friendly iteration.
    Uses two arrays: sparse (indirect) and dense (direct).
    """

    def __init__(self) -> None:
        """Initialize an empty sparse set."""
        self.sparse: dict[int, int] = {}  # entity_id -> dense_index
        self.dense: list[Entity] = []  # ordered entities
        self.components: list[Any] = []  # components parallel to dense

    def contains(self, entity: Entity) -> bool:
        """Check if entity has this component."""
        return entity.index in self.sparse

    def insert(self, entity: Entity, component: Component) -> None:
        """Insert component for entity."""
        if entity.index in self.sparse:
            # Update existing
            idx = self.sparse[entity.index]
            self.components[idx] = component
        else:
            # Add new
            idx = len(self.dense)
            self.sparse[entity.index] = idx
            self.dense.append(entity)
            self.components.append(component)

    def remove(self, entity: Entity) -> None:
        """Remove component for entity."""
        if entity.index not in self.sparse:
            return

        idx = self.sparse[entity.index]
        last_entity = self.dense[-1]
        last_component = self.components[-1]

        # Swap with last
        self.dense[idx] = last_entity
        self.components[idx] = last_component
        self.sparse[last_entity.index] = idx

        # Remove last
        del self.sparse[entity.index]
        self.dense.pop()
        self.components.pop()

    def get(self, entity: Entity) -> Component | None:
        """Get component for entity."""
        if entity.index not in self.sparse:
            return None
        idx = self.sparse[entity.index]
        return self.components[idx]

    def iter_components(self) -> list[Component]:
        """Get all components in cache-friendly order."""
        return self.components.copy()

    def iter_entities(self) -> list[Entity]:
        """Get all entities with this component."""
        return self.dense.copy()

    def clear(self) -> None:
        """Clear all data."""
        self.sparse.clear()
        self.dense.clear()
        self.components.clear()


class Archetype:
    """
    Archetype for efficient querying.

    Groups entities that have the same set of components.
    """

    def __init__(self, component_types: tuple[type[Component], ...]) -> None:
        """Initialize archetype with component types."""
        self.component_types = component_types
        self.entities: list[Entity] = []

    def matches(self, component_mask: int) -> bool:
        """Check if entities of this archetype match the query mask."""
        return True  # Simplified for this implementation

    def add_entity(self, entity: Entity) -> None:
        """Add entity to this archetype."""
        if entity not in self.entities:
            self.entities.append(entity)

    def remove_entity(self, entity: Entity) -> None:
        """Remove entity from this archetype."""
        if entity in self.entities:
            self.entities.remove(entity)


class EntityComponentSystem:
    """
    Complete Entity Component System with generational indices and sparse sets.

    Features:
    - Generational indices for safe entity recycling
    - Sparse sets for cache-friendly component storage
    - Archetype-based query caching
    - Entity prefabs (templates)
    - World snapshots for save/load
    """

    def __init__(self, initial_capacity: int = 256) -> None:
        """
        Initialize the ECS.

        Args:
            initial_capacity: Initial capacity for entity pool.
        """
        self.initial_capacity = initial_capacity
        self.entity_generations: list[int] = [0] * initial_capacity
        self.entity_archetypes: list[Archetype | None] = [None] * initial_capacity
        self.free_entities: list[int] = list(range(initial_capacity - 1, -1, -1))

        self.component_stores: dict[type[Component], SparseSet] = {}
        self.systems: dict[str, System] = {}
        self.system_order: list[str] = []
        self.prefabs: dict[str, list[Component]] = {}
        self.archetypes: dict[tuple[type[Component], ...], Archetype] = {}

        self.event_handlers: dict[str, list[Callable[[Any], None]]] = {}
        self.last_entity_count = 0

    def create_entity(self) -> Entity:
        """
        Create a new entity with generational index.

        Returns:
            New Entity instance.

        Raises:
            EntityError: If entity pool is exhausted.
        """
        if not self.free_entities:
            # Expand pool
            old_size = len(self.entity_generations)
            new_size = old_size * 2
            self.entity_generations.extend([0] * old_size)
            self.entity_archetypes.extend([None] * old_size)
            self.free_entities.extend(range(new_size - 1, old_size - 1, -1))

        index = self.free_entities.pop()
        generation = self.entity_generations[index]
        entity = Entity(index, generation)
        return entity

    def destroy_entity(self, entity: Entity) -> None:
        """
        Destroy entity and recycle its index.

        Args:
            entity: Entity to destroy.

        Raises:
            EntityError: If entity is invalid.
        """
        if entity.index < 0 or entity.index >= len(self.entity_generations):
            raise EntityError(f"Invalid entity index: {entity.index}")

        if entity.generation != self.entity_generations[entity.index]:
            raise EntityError(f"Entity is invalid (stale generation): {entity}")

        # Remove all components
        for store in self.component_stores.values():
            store.remove(entity)

        # Update archetype
        if self.entity_archetypes[entity.index]:
            self.entity_archetypes[entity.index].remove_entity(entity)

        # Increment generation and recycle
        self.entity_generations[entity.index] += 1
        self.free_entities.append(entity.index)

    def add_component(self, entity: Entity, component: Component) -> None:
        """
        Add component to entity.

        Args:
            entity: Target entity.
            component: Component instance.

        Raises:
            EntityError: If entity is invalid.
            ComponentError: If component type already exists.
        """
        if entity.generation != self.entity_generations[entity.index]:
            raise EntityError(f"Entity is invalid: {entity}")

        comp_type = type(component)

        # Initialize store if needed
        if comp_type not in self.component_stores:
            self.component_stores[comp_type] = SparseSet()

        store = self.component_stores[comp_type]
        if store.contains(entity):
            raise ComponentError(f"Entity already has {comp_type.__name__}")

        store.insert(entity, component)
        self._update_archetype(entity)

    def remove_component(self, entity: Entity, component_type: type[Component]) -> None:
        """
        Remove component from entity.

        Args:
            entity: Target entity.
            component_type: Type of component to remove.

        Raises:
            EntityError: If entity is invalid.
            ComponentError: If component doesn't exist.
        """
        if entity.generation != self.entity_generations[entity.index]:
            raise EntityError(f"Entity is invalid: {entity}")

        if component_type not in self.component_stores:
            raise ComponentError(f"No store for {component_type.__name__}")

        store = self.component_stores[component_type]
        if not store.contains(entity):
            raise ComponentError(f"Entity doesn't have {component_type.__name__}")

        store.remove(entity)
        self._update_archetype(entity)

    def get_component(self, entity: Entity, component_type: type[Component]) -> Component | None:
        """
        Get component from entity.

        Args:
            entity: Target entity.
            component_type: Type of component to retrieve.

        Returns:
            Component instance or None.
        """
        if entity.generation != self.entity_generations[entity.index]:
            return None

        if component_type not in self.component_stores:
            return None

        return self.component_stores[component_type].get(entity)

    def has_component(self, entity: Entity, component_type: type[Component]) -> bool:
        """
        Check if entity has component.

        Args:
            entity: Target entity.
            component_type: Type of component.

        Returns:
            True if entity has component.
        """
        if entity.generation != self.entity_generations[entity.index]:
            return False

        if component_type not in self.component_stores:
            return False

        return self.component_stores[component_type].contains(entity)

    def query(self, *component_types: type[Component]) -> list[Entity]:
        """
        Query entities with specific components.

        Args:
            *component_types: Component types to query.

        Returns:
            List of entities matching query.
        """
        if not component_types:
            return []

        # Get first store
        first_store = self.component_stores.get(component_types[0])
        if first_store is None:
            return []

        entities = first_store.iter_entities()

        # Filter by additional components
        for comp_type in component_types[1:]:
            if comp_type not in self.component_stores:
                return []

            store = self.component_stores[comp_type]
            entities = [e for e in entities if store.contains(e)]

        return entities

    def register_system(self, name: str, system: System, priority: int = 0) -> None:
        """
        Register a system for execution.

        Args:
            name: Unique system name.
            system: System instance.
            priority: Execution priority (higher = earlier).

        Raises:
            SystemError: If name already exists.
        """
        if name in self.systems:
            raise SystemError(f"System '{name}' already registered")

        system.priority = priority
        self.systems[name] = system
        self._rebuild_system_order()

    def unregister_system(self, name: str) -> None:
        """
        Unregister a system.

        Args:
            name: System name.
        """
        if name in self.systems:
            del self.systems[name]
            self._rebuild_system_order()

    def update_systems(self, dt: float) -> None:
        """
        Update all registered systems.

        Args:
            dt: Delta time in seconds.
        """
        for name in self.system_order:
            system = self.systems[name]
            if system.enabled:
                system.update(dt)

    def add_prefab(self, name: str, components: list[Component]) -> None:
        """
        Register an entity prefab (template).

        Args:
            name: Prefab name.
            components: List of component templates.
        """
        self.prefabs[name] = components

    def instantiate_prefab(self, name: str) -> Entity | None:
        """
        Create entity from prefab.

        Args:
            name: Prefab name.

        Returns:
            New entity or None if prefab not found.
        """
        if name not in self.prefabs:
            return None

        entity = self.create_entity()
        for component in self.prefabs[name]:
            self.add_component(entity, component.clone())

        return entity

    def save_snapshot(self) -> dict[str, Any]:
        """
        Save complete world state snapshot.

        Returns:
            Snapshot dict containing all entities and components.
        """
        snapshot = {
            "entities": [],
            "components": {},
        }

        for comp_type, store in self.component_stores.items():
            comp_name = comp_type.__name__
            snapshot["components"][comp_name] = []

            for entity, component in zip(store.iter_entities(), store.iter_components()):
                snapshot["components"][comp_name].append(
                    {
                        "entity": (entity.index, entity.generation),
                        "data": copy.deepcopy(component.__dict__),
                    }
                )

        return snapshot

    def load_snapshot(self, snapshot: dict[str, Any]) -> None:
        """
        Load world state from snapshot.

        Args:
            snapshot: Snapshot dict from save_snapshot.
        """
        # Clear current state
        for store in self.component_stores.values():
            store.clear()

        self.free_entities.clear()
        self.entity_generations = [0] * self.initial_capacity
        self.free_entities = list(range(self.initial_capacity - 1, -1, -1))

        # Restore components. Resolve types by name from all known Component
        # subclasses so snapshots can be loaded into a fresh ECS instance.
        def _all_component_types() -> list[type[Component]]:
            discovered: list[type[Component]] = []
            seen: set[type[Component]] = set()
            stack: list[type[Component]] = list(Component.__subclasses__())

            while stack:
                comp_cls = stack.pop()
                if comp_cls in seen:
                    continue
                seen.add(comp_cls)
                discovered.append(comp_cls)
                stack.extend(comp_cls.__subclasses__())

            return discovered

        component_type_map: dict[str, type[Component]] = {}
        for comp_type in _all_component_types():
            component_type_map[comp_type.__name__] = comp_type
        for comp_type in self.component_stores.keys():
            component_type_map[comp_type.__name__] = comp_type

        for comp_name, components_data in snapshot["components"].items():
            if comp_name not in component_type_map:
                continue

            comp_type = component_type_map[comp_name]
            for item in components_data:
                entity_idx, generation = item["entity"]
                entity = Entity(entity_idx, generation)

                # Update generation tracking
                if entity_idx >= len(self.entity_generations):
                    self.entity_generations.extend([0] * (entity_idx - len(self.entity_generations) + 1))
                if entity_idx >= len(self.entity_archetypes):
                    self.entity_archetypes.extend([None] * (entity_idx - len(self.entity_archetypes) + 1))
                self.entity_generations[entity_idx] = generation

                # Remove from free list if present
                if entity_idx in self.free_entities:
                    self.free_entities.remove(entity_idx)

                # Create component
                try:
                    component = comp_type()
                except Exception:
                    component = comp_type.__new__(comp_type)
                for key, value in item["data"].items():
                    setattr(component, key, value)

                # Add to world
                if comp_type not in self.component_stores:
                    self.component_stores[comp_type] = SparseSet()
                self.component_stores[comp_type].insert(entity, component)

    def _update_archetype(self, entity: Entity) -> None:
        """Update entity's archetype based on current components."""
        component_types = tuple(
            comp_type for comp_type, store in self.component_stores.items() if store.contains(entity)
        )

        if component_types not in self.archetypes:
            self.archetypes[component_types] = Archetype(component_types)

        archetype = self.archetypes[component_types]
        archetype.add_entity(entity)
        self.entity_archetypes[entity.index] = archetype

    def _rebuild_system_order(self) -> None:
        """Rebuild system execution order based on priorities."""
        self.system_order = sorted(
            self.systems.keys(),
            key=lambda name: self.systems[name].priority,
            reverse=True,
        )

    def get_world_stats(self) -> dict[str, Any]:
        """
        Get statistics about world state.

        Returns:
            Dict with entity count, component counts, etc.
        """
        entity_count = sum(len(store.iter_entities()) for store in self.component_stores.values()) // max(
            len(self.component_stores), 1
        )

        return {
            "entity_count": len(self.free_entities) == 0
            and self.initial_capacity
            or len([g for g in self.entity_generations if g > 0]),
            "component_types": len(self.component_stores),
            "archetypes": len(self.archetypes),
            "systems": len(self.systems),
            "free_slots": len(self.free_entities),
        }

    def subscribe_event(self, event_type: str, handler: Callable[[Any], None]) -> None:
        """
        Subscribe to event type.

        Args:
            event_type: Event type string.
            handler: Callback function.
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    def emit_event(self, event_type: str, event: Any) -> None:
        """
        Emit event to all subscribers.

        Args:
            event_type: Event type string.
            event: Event data.
        """
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                handler(event)
