"""Tools for Data Warehouse module.

Provides tools for schema management, ETL, and data operations.
"""

from typing import Any

from thomas.marketplace.data_warehouse import core
from thomas.tools.base import Tool, ToolResult


class SchemaManagementTool(Tool):
    """Manage data warehouse schemas."""

    name = "dw_schema"
    category = "data_warehouse"
    description = "Create and manage star schemas"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_schema", "list_schemas", "get_schema"],
                "description": "Schema action",
            },
            "schema_name": {"type": "string", "description": "Name of the schema"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.warehouse = core.DataWarehouse()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_schema":
                schema_name = args.get("schema_name", "schema")
                schema = self.warehouse.create_schema(schema_name)
                return ToolResult(ok=True, data={"schema_id": schema.id, "schema_name": schema_name})

            elif action == "list_schemas":
                schemas = list(self.warehouse.schemas.keys())
                return ToolResult(ok=True, data={"schemas": schemas})

            elif action == "get_schema":
                schema_name = args.get("schema_name", "")
                schema = self.warehouse.get_schema(schema_name)
                if schema:
                    return ToolResult(ok=True, data=schema.to_dict())
                else:
                    return ToolResult(ok=False, error=f"Schema not found: {schema_name}")

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DimensionFactTool(Tool):
    """Manage dimensions and facts."""

    name = "dw_dimensions_facts"
    category = "data_warehouse"
    description = "Create and manage dimensions and fact tables"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create_dimension", "create_fact_table"], "description": "Action"},
            "schema_name": {"type": "string", "description": "Target schema"},
            "name": {"type": "string", "description": "Dimension or table name"},
        },
        "required": ["action", "schema_name"],
    }

    def __init__(self):
        self.warehouse = core.DataWarehouse()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            schema_name = args.get("schema_name", "")

            schema = self.warehouse.get_schema(schema_name)
            if not schema:
                return ToolResult(ok=False, error=f"Schema not found: {schema_name}")

            if action == "create_dimension":
                dim_name = args.get("name", "dimension")
                dimension = core.Dimension(dim_name, "id")
                schema.add_dimension(dimension)
                return ToolResult(ok=True, data={"dimension_id": dimension.id, "dimension_name": dim_name})

            elif action == "create_fact_table":
                fact_name = args.get("name", "facts")
                fact_table = core.FactTable(fact_name)
                schema.add_fact_table(fact_table)
                return ToolResult(ok=True, data={"fact_table_id": fact_table.id, "fact_table_name": fact_name})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ETLManagementTool(Tool):
    """Manage ETL jobs."""

    name = "dw_etl"
    category = "data_warehouse"
    description = "Create and manage ETL jobs"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_job", "start_job", "complete_job", "list_jobs"],
                "description": "ETL action",
            },
            "job_name": {"type": "string", "description": "Job name"},
            "job_id": {"type": "string", "description": "Job ID"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.warehouse = core.DataWarehouse()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_job":
                job_name = args.get("job_name", "job")
                job = self.warehouse.create_etl_job(job_name)
                return ToolResult(ok=True, data={"job_id": job.id, "job_name": job_name, "status": job.status})

            elif action == "start_job":
                job_id = args.get("job_id", "")
                job = self.warehouse.get_etl_job(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job not found: {job_id}")

                job.start()
                return ToolResult(ok=True, data={"job_id": job_id, "status": job.status})

            elif action == "complete_job":
                job_id = args.get("job_id", "")
                records = args.get("records_processed", 0)
                job = self.warehouse.get_etl_job(job_id)
                if not job:
                    return ToolResult(ok=False, error=f"Job not found: {job_id}")

                job.complete(records)
                return ToolResult(ok=True, data=job.to_dict())

            elif action == "list_jobs":
                jobs = [j.to_dict() for j in self.warehouse.etl_jobs]
                return ToolResult(ok=True, data={"jobs": jobs})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class WarehouseMonitoringTool(Tool):
    """Monitor warehouse."""

    name = "dw_monitor"
    category = "data_warehouse"
    description = "Monitor warehouse stats and performance"
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["get_stats"], "description": "Monitoring action"}},
        "required": ["action"],
    }

    def __init__(self):
        self.warehouse = core.DataWarehouse()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_stats":
                stats = self.warehouse.get_warehouse_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_data_warehouse_tools(registry):
    """Register all data warehouse tools."""
    registry.register(SchemaManagementTool())
    registry.register(DimensionFactTool())
    registry.register(ETLManagementTool())
    registry.register(WarehouseMonitoringTool())
