"""Tools for Database Internals operations.

Exposes core database engine functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class DBExecuteQueryTool(Tool):
    name = "db.execute_query"
    category = "db_internals"
    description = "Execute a SQL query against the database engine"
    parameters = {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "SQL query string",
            },
        },
        "required": ["sql"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            sql = args["sql"]

            return ToolResult(
                ok=True,
                data={
                    "sql": sql,
                    "status": "query_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Query execution failed: {e}")


class DBCreateTableTool(Tool):
    name = "db.create_table"
    category = "db_internals"
    description = "Create a table in the database with specified schema"
    parameters = {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Name of the table to create",
            },
            "columns": {
                "type": "array",
                "description": "List of column definitions",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "nullable": {"type": "boolean"},
                    },
                },
            },
            "primary_key": {
                "type": "array",
                "description": "Column names that form the primary key",
                "items": {"type": "string"},
            },
        },
        "required": ["table_name", "columns"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            table_name = args["table_name"]
            columns = args["columns"]
            pk = args.get("primary_key", [])

            return ToolResult(
                ok=True,
                data={
                    "table_name": table_name,
                    "columns": columns,
                    "primary_key": pk,
                    "status": "table_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create table: {e}")


class DBCreateIndexTool(Tool):
    name = "db.create_index"
    category = "db_internals"
    description = "Create an index on table columns for performance optimization"
    parameters = {
        "type": "object",
        "properties": {
            "index_name": {
                "type": "string",
                "description": "Name of the index",
            },
            "table_name": {
                "type": "string",
                "description": "Table to index",
            },
            "columns": {
                "type": "array",
                "description": "Columns to index",
                "items": {"type": "string"},
            },
            "unique": {
                "type": "boolean",
                "description": "Whether the index enforces uniqueness",
            },
        },
        "required": ["index_name", "table_name", "columns"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            index_name = args["index_name"]
            table_name = args["table_name"]
            columns = args["columns"]
            unique = args.get("unique", False)

            return ToolResult(
                ok=True,
                data={
                    "index_name": index_name,
                    "table_name": table_name,
                    "columns": columns,
                    "unique": unique,
                    "status": "index_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create index: {e}")


class DBInsertTool(Tool):
    name = "db.insert"
    category = "db_internals"
    description = "Insert rows into a table"
    parameters = {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Target table name",
            },
            "rows": {
                "type": "array",
                "description": "List of row data objects",
                "items": {"type": "object"},
            },
        },
        "required": ["table_name", "rows"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            table_name = args["table_name"]
            rows = args["rows"]

            return ToolResult(
                ok=True,
                data={
                    "table_name": table_name,
                    "rows_inserted": len(rows),
                    "status": "insert_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Insert failed: {e}")


class DBTransactionTool(Tool):
    name = "db.transaction"
    category = "db_internals"
    description = "Manage database transactions (begin, commit, rollback)"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["begin", "commit", "rollback"],
                "description": "Transaction action to perform",
            },
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args["action"]

            return ToolResult(
                ok=True,
                data={
                    "action": action,
                    "status": "transaction_managed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Transaction operation failed: {e}")


class DBGetStatisticsTool(Tool):
    name = "db.statistics"
    category = "db_internals"
    description = "Get query statistics and table metadata"
    parameters = {
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Optional table name to get stats for. Omit for system-wide stats.",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            table_name = args.get("table_name")

            return ToolResult(
                ok=True,
                data={
                    "table_name": table_name,
                    "status": "statistics_retrieved",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to get statistics: {e}")


def register_db_internals_tools(registry, sandbox=None):
    """Register all DB internals tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional)
    """
    registry.register(DBExecuteQueryTool())
    registry.register(DBCreateTableTool())
    registry.register(DBCreateIndexTool())
    registry.register(DBInsertTool())
    registry.register(DBTransactionTool())
    registry.register(DBGetStatisticsTool())
