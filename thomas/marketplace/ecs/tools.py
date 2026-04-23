"""Tools for Entity Component System operations."""

from typing import Any

from thomas.marketplace.ecs import core
from thomas.tools.base import Tool, ToolResult


class EntityManagementTool(Tool):
    """Create, query, and manage entities."""

    name = "ecs_entities"
    category = "ecs"
    description = "Create, destroy, and query entities"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "destroy", "list", "get_info"],
                "description": "Entity action",
            },
            "entity_id": {"type": "string", "description": "Entity identifier"},
            "name": {"type": "string", "description": "Entity name"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.world = core.World()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            entity_id = args.get("entity_id", "")
            name = args.get("name", "")

            if action == "create":
                entity = self.world.create_entity(name=name, entity_id=entity_id if entity_id else None)
                return ToolResult(ok=True, data={"entity_id": entity.entity_id, "name": entity.name})

            elif action == "destroy":
                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")
                success = self.world.destroy_entity(entity_id)
                return ToolResult(ok=True, data={"destroyed": success})

            elif action == "list":
                entities = [
                    {"id": e.entity_id, "name": e.name, "components": len(e.components)}
                    for e in self.world.entities.values()
                ]
                return ToolResult(ok=True, data={"entities": entities, "count": len(entities)})

            elif action == "get_info":
                if not entity_id:
                    return ToolResult(ok=False, error="entity_id required")
                entity = self.world.get_entity(entity_id)
                if not entity:
                    return ToolResult(ok=False, error=f"Entity {entity_id} not found")
                return ToolResult(
                    ok=True,
                    data={
                        "entity_id": entity.entity_id,
                        "name": entity.name,
                        "enabled": entity.enabled,
                        "component_count": len(entity.components),
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class SystemManagementTool(Tool):
    """Register and manage systems."""

    name = "ecs_systems"
    category = "ecs"
    description = "Add, remove, and manage systems"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_system", "remove_system", "list_systems", "enable_system", "disable_system"],
                "description": "System action",
            },
            "system_name": {"type": "string", "description": "System name"},
            "system_type": {
                "type": "string",
                "enum": ["movement", "render"],
                "description": "System type to instantiate",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self.world = core.World()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            system_name = args.get("system_name", "")
            system_type = args.get("system_type", "")

            if action == "add_system":
                if system_type == "movement":
                    system = core.SimpleMovementSystem()
                elif system_type == "render":
                    system = core.SimpleRenderSystem()
                else:
                    return ToolResult(ok=False, error=f"Unknown system type: {system_type}")

                self.world.add_system(system)
                return ToolResult(ok=True, data={"system": system.name, "enabled": system.enabled})

            elif action == "remove_system":
                if not system_name:
                    return ToolResult(ok=False, error="system_name required")
                success = self.world.remove_system(system_name)
                return ToolResult(ok=True, data={"removed": success})

            elif action == "list_systems":
                systems = [
                    {"name": s.name, "enabled": s.enabled, "order": s.execution_order}
                    for s in self.world.systems.values()
                ]
                return ToolResult(ok=True, data={"systems": systems, "count": len(systems)})

            elif action == "enable_system":
                if not system_name:
                    return ToolResult(ok=False, error="system_name required")
                system = self.world.get_system(system_name)
                if not system:
                    return ToolResult(ok=False, error=f"System {system_name} not found")
                system.enabled = True
                return ToolResult(ok=True, data={"system": system_name, "enabled": True})

            elif action == "disable_system":
                if not system_name:
                    return ToolResult(ok=False, error="system_name required")
                system = self.world.get_system(system_name)
                if not system:
                    return ToolResult(ok=False, error=f"System {system_name} not found")
                system.enabled = False
                return ToolResult(ok=True, data={"system": system_name, "enabled": False})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WorldStatsTool(Tool):
    """Get world statistics and state."""

    name = "ecs_stats"
    category = "ecs"
    description = "Get world statistics and system execution info"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["world_stats", "entity_count", "system_count"],
                "description": "Stats action",
            }
        },
        "required": ["action"],
    }

    def __init__(self):
        self.world = core.World()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "world_stats":
                stats = self.world.get_stats()
                return ToolResult(ok=True, data=stats)

            elif action == "entity_count":
                count = len(self.world.entities)
                return ToolResult(ok=True, data={"entity_count": count})

            elif action == "system_count":
                count = len(self.world.systems)
                return ToolResult(ok=True, data={"system_count": count})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_ecs_tools(registry):
    """Register all ECS tools."""
    registry.register(EntityManagementTool())
    registry.register(SystemManagementTool())
    registry.register(WorldStatsTool())
