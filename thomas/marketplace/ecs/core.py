"""Entity Component System for managing entities with components and systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Component:
    """Base component class. Subclass to create specific components."""

    pass


@dataclass
class Entity:
    """Entity with attached components."""

    entity_id: str
    name: str = ""
    components: dict[type[Component], Component] = field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_component(self, component: Component) -> None:
        """Add a component to this entity."""
        self.components[type(component)] = component

    def remove_component(self, component_type: type[Component]) -> Component | None:
        """Remove a component from this entity."""
        return self.components.pop(component_type, None)

    def get_component(self, component_type: type[Component]) -> Component | None:
        """Get a component by type."""
        return self.components.get(component_type)

    def has_component(self, component_type: type[Component]) -> bool:
        """Check if entity has a component."""
        return component_type in self.components

    def get_components(self) -> list[Component]:
        """Get all components."""
        return list(self.components.values())


@dataclass
class SystemExecution:
    """System execution result."""

    system_name: str
    entities_processed: int
    duration_ms: float = 0.0
    error: str | None = None


class System:
    """Base system class. Override execute() to process entities."""

    def __init__(self, name: str):
        self.name = name
        self.enabled = True
        self.query_components: list[type[Component]] = []
        self.execution_order = 0

    def set_query(self, *component_types: type[Component]) -> None:
        """Set which components this system queries for."""
        self.query_components = list(component_types)

    async def execute(self, entities: list[Entity]) -> SystemExecution:
        """Execute system on entities. Override in subclasses."""
        raise NotImplementedError

    def matches_query(self, entity: Entity) -> bool:
        """Check if entity matches this system's query."""
        if not self.query_components:
            return True
        return all(entity.has_component(ct) for ct in self.query_components)


class World:
    """Game world containing entities and systems."""

    def __init__(self, name: str = "world"):
        self.name = name
        self.entities: dict[str, Entity] = {}
        self.systems: dict[str, System] = {}
        self.system_order: list[str] = []
        self._entity_counter = 0

    def create_entity(self, name: str = "", entity_id: str | None = None) -> Entity:
        """Create a new entity."""
        if entity_id is None:
            self._entity_counter += 1
            entity_id = f"entity_{self._entity_counter}"

        if entity_id in self.entities:
            raise ValueError(f"Entity {entity_id} already exists")

        entity = Entity(entity_id=entity_id, name=name)
        self.entities[entity_id] = entity
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get entity by ID."""
        return self.entities.get(entity_id)

    def destroy_entity(self, entity_id: str) -> bool:
        """Destroy an entity."""
        if entity_id in self.entities:
            del self.entities[entity_id]
            return True
        return False

    def find_entities_with_components(self, *component_types: type[Component]) -> list[Entity]:
        """Find all entities with specific components."""
        results = []
        for entity in self.entities.values():
            if all(entity.has_component(ct) for ct in component_types):
                results.append(entity)
        return results

    def add_system(self, system: System) -> None:
        """Register a system."""
        if system.name in self.systems:
            raise ValueError(f"System {system.name} already registered")

        self.systems[system.name] = system
        self.system_order.append(system.name)
        self.system_order.sort(key=lambda s: self.systems[s].execution_order)

    def remove_system(self, system_name: str) -> bool:
        """Unregister a system."""
        if system_name in self.systems:
            del self.systems[system_name]
            self.system_order.remove(system_name)
            return True
        return False

    def get_system(self, system_name: str) -> System | None:
        """Get a system by name."""
        return self.systems.get(system_name)

    async def update(self) -> list[SystemExecution]:
        """Update all systems in order."""
        results = []
        for system_name in self.system_order:
            system = self.systems[system_name]

            if not system.enabled:
                continue

            matching_entities = [e for e in self.entities.values() if system.matches_query(e) and e.enabled]

            try:
                import time

                start = time.monotonic()
                result = await system.execute(matching_entities)
                result.duration_ms = (time.monotonic() - start) * 1000
                results.append(result)
            except Exception as e:
                results.append(SystemExecution(system_name=system.name, entities_processed=0, error=str(e)))

        return results

    def get_stats(self) -> dict[str, Any]:
        """Get world statistics."""
        return {
            "name": self.name,
            "entities": len(self.entities),
            "systems": len(self.systems),
            "components_total": sum(len(e.components) for e in self.entities.values()),
        }


class SimpleMovementSystem(System):
    """Example: Simple movement system."""

    def __init__(self):
        super().__init__("movement")
        self.execution_order = 1

    async def execute(self, entities: list[Entity]) -> SystemExecution:
        """Process movement for entities with Position and Velocity."""
        processed = 0
        for entity in entities:
            # Example: entities with Position and Velocity components
            processed += 1

        return SystemExecution(system_name=self.name, entities_processed=processed)


class SimpleRenderSystem(System):
    """Example: Simple render system."""

    def __init__(self):
        super().__init__("render")
        self.execution_order = 100

    async def execute(self, entities: list[Entity]) -> SystemExecution:
        """Render entities."""
        return SystemExecution(system_name=self.name, entities_processed=len(entities))
