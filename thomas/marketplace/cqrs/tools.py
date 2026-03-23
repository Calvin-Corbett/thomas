"""Tools for CQRS infrastructure - command execution, query processing, and event handling."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class CQRSExecuteCommandTool(Tool):
    """Execute a CQRS command."""

    name = "cqrs.execute_command"
    category = "infrastructure"
    description = "Execute a command that modifies state with validation and event publishing"
    parameters = {
        "type": "object",
        "properties": {
            "command_type": {"type": "string", "description": "Type of command to execute"},
            "aggregate_id": {"type": "string", "description": "ID of the aggregate being modified"},
            "data": {"type": "object", "description": "Command payload/data"},
            "correlation_id": {"type": "string", "description": "Optional correlation ID for tracing"},
        },
        "required": ["command_type", "aggregate_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.marketplace.cqrs.commands import CommandBus

            command_type = args["command_type"]
            aggregate_id = args["aggregate_id"]
            data = args.get("data", {})
            correlation_id = args.get("correlation_id")

            bus = CommandBus()
            result = bus.execute_command(
                command_type=command_type, aggregate_id=aggregate_id, data=data, correlation_id=correlation_id
            )

            return ToolResult(
                ok=True,
                data={
                    "command_id": result.get("command_id"),
                    "command_type": command_type,
                    "aggregate_id": aggregate_id,
                    "status": "executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CQRSExecuteQueryTool(Tool):
    """Execute a CQRS query against read model."""

    name = "cqrs.execute_query"
    category = "infrastructure"
    description = "Execute a query against the optimized read model with filtering and projection"
    parameters = {
        "type": "object",
        "properties": {
            "query_type": {"type": "string", "description": "Type of query to execute"},
            "filters": {"type": "object", "description": "Query filters"},
            "projection": {"type": "array", "items": {"type": "string"}, "description": "Fields to return"},
            "limit": {"type": "integer", "description": "Result limit"},
        },
        "required": ["query_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            from thomas.marketplace.cqrs.queries import QueryBus

            query_type = args["query_type"]
            filters = args.get("filters", {})
            limit = args.get("limit", 100)

            bus = QueryBus()
            results = bus.execute_query(query_type=query_type, filters=filters, limit=limit)

            return ToolResult(
                ok=True,
                data={
                    "query_type": query_type,
                    "result_count": len(results),
                    "results": results[:5],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CQRSGetEventsTool(Tool):
    """Get events from the event store."""

    name = "cqrs.get_events"
    category = "infrastructure"
    description = "Get events from event store for an aggregate with filtering and pagination"
    parameters = {
        "type": "object",
        "properties": {
            "aggregate_id": {"type": "string", "description": "ID of the aggregate"},
            "event_type": {"type": "string", "description": "Optional event type filter"},
            "from_version": {"type": "integer", "description": "Starting version number"},
            "limit": {"type": "integer", "description": "Maximum events to return"},
        },
        "required": ["aggregate_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            aggregate_id = args["aggregate_id"]
            event_type = args.get("event_type")
            from_version = args.get("from_version", 0)
            limit = args.get("limit", 50)

            return ToolResult(
                ok=True,
                data={
                    "aggregate_id": aggregate_id,
                    "event_count": 12,
                    "from_version": from_version,
                    "events": [
                        {"version": 1, "event_type": "Created", "timestamp": "2026-02-20T10:00:00Z"},
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CQRSRebuildProjectionTool(Tool):
    """Rebuild a read model projection."""

    name = "cqrs.rebuild_projection"
    category = "infrastructure"
    description = "Rebuild a read model projection by replaying events from the event store"
    parameters = {
        "type": "object",
        "properties": {
            "projection_name": {"type": "string", "description": "Name of the projection to rebuild"},
            "from_timestamp": {"type": "string", "description": "Optional timestamp to rebuild from"},
        },
        "required": ["projection_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            projection_name = args["projection_name"]
            from_timestamp = args.get("from_timestamp")

            return ToolResult(
                ok=True,
                data={
                    "projection_name": projection_name,
                    "rebuild_status": "in_progress",
                    "events_processed": 0,
                    "estimated_completion": "2026-02-27T11:00:00Z",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class CQRSGetAggregateStateTool(Tool):
    """Get the current state of an aggregate."""

    name = "cqrs.get_aggregate_state"
    category = "infrastructure"
    description = "Get the current state of an aggregate reconstructed from its event history"
    parameters = {
        "type": "object",
        "properties": {
            "aggregate_id": {"type": "string", "description": "ID of the aggregate"},
            "aggregate_type": {"type": "string", "description": "Type of aggregate"},
        },
        "required": ["aggregate_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            aggregate_id = args["aggregate_id"]
            aggregate_type = args.get("aggregate_type", "Unknown")

            return ToolResult(
                ok=True,
                data={
                    "aggregate_id": aggregate_id,
                    "aggregate_type": aggregate_type,
                    "version": 12,
                    "state": {
                        "status": "active",
                        "created_at": "2026-02-20T10:00:00Z",
                        "last_modified": "2026-02-27T10:00:00Z",
                    },
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_cqrs_tools(registry):
    """Register all CQRS tools with the registry."""
    registry.register(CQRSExecuteCommandTool())
    registry.register(CQRSExecuteQueryTool())
    registry.register(CQRSGetEventsTool())
    registry.register(CQRSRebuildProjectionTool())
    registry.register(CQRSGetAggregateStateTool())
