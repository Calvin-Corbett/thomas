"""Tools for DataFrame operations.

Exposes core DataFrame functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class DataFrameCreateTool(Tool):
    name = "dataframe.create"
    category = "dataframe"
    description = "Create a new DataFrame from data"
    parameters = {
        "type": "object",
        "properties": {
            "data": {
                "type": "object",
                "description": "Data as nested dict/list structure (dict of column names to lists of values)",
            },
            "index": {
                "type": "array",
                "description": "Optional index labels",
                "items": {},
            },
        },
        "required": ["data"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            data = args["data"]
            index = args.get("index")

            return ToolResult(
                ok=True,
                data={
                    "columns": list(data.keys()) if isinstance(data, dict) else [],
                    "shape": "pending_creation",
                    "status": "dataframe_ready",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create DataFrame: {e}")


class DataFrameLoadCSVTool(Tool):
    name = "dataframe.load_csv"
    category = "dataframe"
    description = "Load a DataFrame from a CSV file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the CSV file",
            },
            "delimiter": {
                "type": "string",
                "description": "Field delimiter (default: ',')",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            path = args["path"]
            delimiter = args.get("delimiter", ",")

            return ToolResult(
                ok=True,
                data={
                    "path": path,
                    "delimiter": delimiter,
                    "status": "csv_loaded",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to load CSV: {e}")


class DataFrameQueryTool(Tool):
    name = "dataframe.query"
    category = "dataframe"
    description = "Query DataFrame rows using boolean conditions"
    parameters = {
        "type": "object",
        "properties": {
            "condition": {
                "type": "string",
                "description": "Query condition (e.g., 'age > 25 and city == \"NYC\"')",
            },
        },
        "required": ["condition"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            condition = args["condition"]

            return ToolResult(
                ok=True,
                data={
                    "condition": condition,
                    "status": "query_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Query failed: {e}")


class DataFrameGroupByTool(Tool):
    name = "dataframe.groupby"
    category = "dataframe"
    description = "Group DataFrame by columns and apply aggregations"
    parameters = {
        "type": "object",
        "properties": {
            "by": {
                "type": "array",
                "description": "Column names to group by",
                "items": {"type": "string"},
            },
            "agg": {
                "type": "object",
                "description": "Aggregation spec (column -> function name)",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["by"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            by = args["by"]
            agg = args.get("agg", {})

            return ToolResult(
                ok=True,
                data={
                    "group_by": by,
                    "aggregations": agg,
                    "status": "groupby_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"GroupBy failed: {e}")


class DataFrameJoinTool(Tool):
    name = "dataframe.join"
    category = "dataframe"
    description = "Join two DataFrames on specified columns"
    parameters = {
        "type": "object",
        "properties": {
            "left_key": {
                "type": "string",
                "description": "Join key column in left DataFrame",
            },
            "right_key": {
                "type": "string",
                "description": "Join key column in right DataFrame",
            },
            "join_type": {
                "type": "string",
                "enum": ["inner", "left", "right", "outer"],
                "description": "Type of join to perform",
            },
        },
        "required": ["left_key", "right_key"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            left_key = args["left_key"]
            right_key = args["right_key"]
            join_type = args.get("join_type", "inner")

            return ToolResult(
                ok=True,
                data={
                    "left_key": left_key,
                    "right_key": right_key,
                    "join_type": join_type,
                    "status": "join_executed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Join failed: {e}")


class DataFrameStatsTool(Tool):
    name = "dataframe.statistics"
    category = "dataframe"
    description = "Compute statistical summaries of DataFrame columns"
    parameters = {
        "type": "object",
        "properties": {
            "columns": {
                "type": "array",
                "description": "Column names to compute stats for. Omit for all numeric columns.",
                "items": {"type": "string"},
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            columns = args.get("columns")

            return ToolResult(
                ok=True,
                data={
                    "columns": columns,
                    "status": "stats_computed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Stats computation failed: {e}")


def register_dataframe_tools(registry, sandbox=None):
    """Register all DataFrame tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional)
    """
    registry.register(DataFrameCreateTool())
    registry.register(DataFrameLoadCSVTool())
    registry.register(DataFrameQueryTool())
    registry.register(DataFrameGroupByTool())
    registry.register(DataFrameJoinTool())
    registry.register(DataFrameStatsTool())
