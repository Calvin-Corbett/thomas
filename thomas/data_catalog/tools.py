"""Tools for Data Catalog module.

Provides tools for metadata management, discovery, and lineage tracking.
"""

from typing import Any

from thomas.data_catalog import core
from thomas.tools.base import Tool, ToolResult


class DatasetManagementTool(Tool):
    """Manage datasets in the catalog."""

    name = "data_catalog_datasets"
    category = "data_catalog"
    description = "Register and manage datasets"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register_dataset", "list_datasets", "get_dataset"],
                "description": "Dataset action",
            },
            "dataset_name": {"type": "string", "description": "Name of the dataset"},
            "dataset_id": {"type": "string", "description": "Dataset identifier"},
            "owner": {"type": "string", "description": "Dataset owner"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.catalog = core.DataCatalog()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register_dataset":
                dataset_name = args.get("dataset_name", "dataset")
                owner = args.get("owner", "unknown")

                dataset = core.Dataset(name=dataset_name, owner=owner)
                self.catalog.register_dataset(dataset)

                return ToolResult(
                    ok=True, data={"dataset_id": dataset.id, "dataset_name": dataset_name, "owner": owner}
                )

            elif action == "list_datasets":
                datasets = [d.to_dict() for d in self.catalog.datasets.values()]
                return ToolResult(ok=True, data={"datasets": datasets})

            elif action == "get_dataset":
                dataset_id = args.get("dataset_id", "")
                if not dataset_id:
                    return ToolResult(ok=False, error="dataset_id required")

                dataset = self.catalog.get_dataset(dataset_id)
                if not dataset:
                    return ToolResult(ok=False, error=f"Dataset not found: {dataset_id}")

                return ToolResult(ok=True, data=dataset.to_dict())

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CatalogSearchTool(Tool):
    """Search and discover datasets."""

    name = "data_catalog_search"
    category = "data_catalog"
    description = "Search and discover datasets by name, tag, or owner"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "find_by_tag", "find_by_owner"],
                "description": "Search action",
            },
            "query": {"type": "string", "description": "Search query or tag/owner name"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.catalog = core.DataCatalog()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            query = args.get("query", "")

            if action == "search":
                results = self.catalog.search(query)
                return ToolResult(ok=True, data={"results": [d.to_dict() for d in results], "count": len(results)})

            elif action == "find_by_tag":
                results = self.catalog.find_by_tag(query)
                return ToolResult(ok=True, data={"results": [d.to_dict() for d in results], "tag": query})

            elif action == "find_by_owner":
                results = self.catalog.find_by_owner(query)
                return ToolResult(ok=True, data={"results": [d.to_dict() for d in results], "owner": query})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LineageTrackingTool(Tool):
    """Track data lineage and dependencies."""

    name = "data_catalog_lineage"
    category = "data_catalog"
    description = "Track data lineage and impact analysis"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_dependency", "get_lineage", "get_impact"],
                "description": "Lineage action",
            },
            "dataset_id": {"type": "string", "description": "Dataset identifier"},
            "upstream_id": {"type": "string", "description": "Upstream dataset ID"},
        },
        "required": ["action", "dataset_id"],
    }

    def __init__(self):
        self.catalog = core.DataCatalog()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            dataset_id = args.get("dataset_id", "")

            if action == "add_dependency":
                upstream_id = args.get("upstream_id", "")
                if not upstream_id:
                    return ToolResult(ok=False, error="upstream_id required")

                self.catalog.lineage.add_dependency(dataset_id, upstream_id)
                return ToolResult(ok=True, data={"dependency_added": True})

            elif action == "get_lineage":
                lineage = self.catalog.get_dataset_lineage(dataset_id)
                return ToolResult(ok=True, data=lineage)

            elif action == "get_impact":
                impact = self.catalog.lineage.get_impact(dataset_id)
                return ToolResult(ok=True, data={"dataset_id": dataset_id, "impacted_datasets": list(impact)})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CatalogStatsTool(Tool):
    """Get catalog statistics."""

    name = "data_catalog_stats"
    category = "data_catalog"
    description = "Get catalog statistics and metadata"
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["get_stats"], "description": "Stats action"}},
        "required": ["action"],
    }

    def __init__(self):
        self.catalog = core.DataCatalog()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_stats":
                stats = self.catalog.get_catalog_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_data_catalog_tools(registry):
    """Register all data catalog tools."""
    registry.register(DatasetManagementTool())
    registry.register(CatalogSearchTool())
    registry.register(LineageTrackingTool())
    registry.register(CatalogStatsTool())
