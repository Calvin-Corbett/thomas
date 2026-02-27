"""Tools for Asset Studio module.

Provides tools for asset creation, connector management, and job orchestration.
"""

from typing import Any

from thomas import asset_studio
from thomas.tools.base import Tool, ToolResult


class ConnectorManagementTool(Tool):
    """Manage asset studio connectors and actions."""

    name = "asset_connector_manage"
    category = "asset_studio"
    description = "Manage connectors, list actions, and retrieve connector information"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_connectors", "get_connector", "list_actions", "get_action"],
                "description": "Management action to perform",
            },
            "connector_id": {"type": "string", "description": "ID of the connector"},
            "action_id": {"type": "string", "description": "ID of the action"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "list_connectors":
                catalog = asset_studio.default_connector_catalog()
                connectors = [
                    {
                        "id": conn.id,
                        "label": conn.label,
                        "category": conn.category,
                        "license": conn.license,
                        "website": conn.website,
                        "num_actions": len(conn.actions),
                    }
                    for conn in catalog.connectors.values()
                ]
                return ToolResult(ok=True, data={"connectors": connectors})

            elif action == "get_connector":
                connector_id = args.get("connector_id", "")
                if not connector_id:
                    return ToolResult(ok=False, error="connector_id required for get_connector")

                catalog = asset_studio.default_connector_catalog()
                connector = catalog.connectors.get(connector_id)
                if not connector:
                    return ToolResult(ok=False, error=f"Connector not found: {connector_id}")

                return ToolResult(ok=True, data=connector.to_dict())

            elif action == "list_actions":
                connector_id = args.get("connector_id", "")
                if not connector_id:
                    return ToolResult(ok=False, error="connector_id required for list_actions")

                catalog = asset_studio.default_connector_catalog()
                connector = catalog.connectors.get(connector_id)
                if not connector:
                    return ToolResult(ok=False, error=f"Connector not found: {connector_id}")

                actions = [action.to_dict() for action in connector.actions]
                return ToolResult(ok=True, data={"connector_id": connector_id, "actions": actions})

            elif action == "get_action":
                connector_id = args.get("connector_id", "")
                action_id = args.get("action_id", "")

                if not connector_id or not action_id:
                    return ToolResult(ok=False, error="connector_id and action_id required")

                catalog = asset_studio.default_connector_catalog()
                connector = catalog.connectors.get(connector_id)
                if not connector:
                    return ToolResult(ok=False, error=f"Connector not found: {connector_id}")

                action_def = connector.action_by_id(action_id)
                if not action_def:
                    return ToolResult(ok=False, error=f"Action not found: {action_id}")

                return ToolResult(ok=True, data=action_def.to_dict())

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RuntimeTool(Tool):
    """Control asset studio runtime execution."""

    name = "asset_runtime_control"
    category = "asset_studio"
    description = "Create and manage asset studio runtime environments"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create_runtime", "get_status"], "description": "Runtime action"}
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_runtime":
                runtime = asset_studio.AssetStudioRuntime()
                return ToolResult(ok=True, data={"status": "runtime_created", "runtime_type": "AssetStudioRuntime"})

            elif action == "get_status":
                return ToolResult(ok=True, data={"status": "ready"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_asset_studio_tools(registry):
    """Register all asset studio tools."""
    registry.register(ConnectorManagementTool())
    registry.register(RuntimeTool())
