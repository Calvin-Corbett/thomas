"""Tools for configuration management - resource state, compliance, and playbook execution."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class ConfigMgmtCheckComplianceTool(Tool):
    """Check compliance status of all managed resources."""

    name = "config_mgmt.check_compliance"
    category = "infrastructure"
    description = "Check compliance status of all managed infrastructure resources and detect drift"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.config_mgmt.core_manager import ConfigManager

            manager = ConfigManager.create()
            compliance = manager.check_compliance()
            return ToolResult(ok=True, data=compliance)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConfigMgmtListResourcesTool(Tool):
    """List all managed infrastructure resources with optional filtering."""

    name = "config_mgmt.list_resources"
    category = "infrastructure"
    description = "List all managed resources with filtering by type and tags"
    parameters = {
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "description": "Filter by resource type (file, package, service, user, etc.)",
            },
            "tags": {"type": "object", "description": "Filter by tags (key-value pairs)"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.config_mgmt.core import ResourceType
            from thomas.config_mgmt.core_manager import ConfigManager

            manager = ConfigManager.create()
            resource_type = None
            if args.get("resource_type"):
                resource_type = ResourceType[args["resource_type"].upper()]

            resources = manager.list_resources(resource_type=resource_type, tags=args.get("tags"))

            return ToolResult(
                ok=True,
                data=[
                    {
                        "id": r.id,
                        "name": r.name,
                        "type": r.resource_type.value,
                        "state": r.state.value,
                        "tags": r.tags,
                    }
                    for r in resources
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConfigMgmtGetStatisticsTool(Tool):
    """Get statistics about configuration management operations."""

    name = "config_mgmt.get_statistics"
    category = "infrastructure"
    description = "Retrieve statistics about managed resources, executions, and state transitions"
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.config_mgmt.core_manager import ConfigManager

            manager = ConfigManager.create()
            stats = manager.get_statistics()
            return ToolResult(ok=True, data=stats)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ConfigMgmtCreateSnapshotTool(Tool):
    """Create a configuration snapshot for backup and rollback."""

    name = "config_mgmt.create_snapshot"
    category = "infrastructure"
    description = "Create a configuration snapshot with optional name for backup/recovery purposes"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Optional name for the snapshot"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.config_mgmt.core_manager import ConfigManager

            manager = ConfigManager.create()
            snapshot = manager.create_snapshot(name=args.get("name", ""))
            return ToolResult(
                ok=True,
                data={
                    "snapshot_id": snapshot.snapshot_id,
                    "timestamp": snapshot.timestamp.isoformat(),
                    "name": snapshot.name,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_config_mgmt_tools(registry):
    """Register all configuration management tools with the registry."""
    registry.register(ConfigMgmtCheckComplianceTool())
    registry.register(ConfigMgmtListResourcesTool())
    registry.register(ConfigMgmtGetStatisticsTool())
    registry.register(ConfigMgmtCreateSnapshotTool())
