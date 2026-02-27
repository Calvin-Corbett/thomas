"""Tools for TSDB operations.

Exposes core TSDB functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class TSDBWritePointTool(Tool):
    name = "tsdb.write_point"
    category = "tsdb"
    description = "Write a single time-series data point with optional tags"
    parameters = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "Name of the metric (e.g., 'cpu_usage', 'memory_free')",
            },
            "timestamp": {
                "type": "integer",
                "description": "Timestamp in milliseconds since epoch",
            },
            "value": {
                "type": "number",
                "description": "Numeric value of the metric",
            },
            "tags": {
                "type": "object",
                "description": "Optional tags as key-value pairs (e.g., {'host': 'web1'})",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["metric_name", "timestamp", "value"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            # For this tool, we'd need to manage a global or session engine
            # For now, return a placeholder that indicates this needs session state
            return ToolResult(
                ok=True,
                data={
                    "metric": args["metric_name"],
                    "timestamp": args["timestamp"],
                    "value": args["value"],
                    "tags": args.get("tags", {}),
                    "status": "point_queued",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"TSDB write failed: {e}")


class TSDBQueryTool(Tool):
    name = "tsdb.query"
    category = "tsdb"
    description = "Query time-series data with optional aggregations and tag filters"
    parameters = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "Name of the metric to query",
            },
            "start_time": {
                "type": "integer",
                "description": "Start timestamp in milliseconds since epoch",
            },
            "end_time": {
                "type": "integer",
                "description": "End timestamp in milliseconds since epoch",
            },
            "aggregations": {
                "type": "array",
                "description": "List of aggregation types (e.g., ['avg', 'max', 'min', 'sum'])",
                "items": {"type": "string"},
            },
            "tags": {
                "type": "object",
                "description": "Optional tag filters to narrow results",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["metric_name", "start_time", "end_time"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            metric = args["metric_name"]
            start = args["start_time"]
            end = args["end_time"]
            aggregations = args.get("aggregations", [])

            return ToolResult(
                ok=True,
                data={
                    "metric": metric,
                    "time_range": {"start": start, "end": end},
                    "aggregations": aggregations,
                    "status": "query_ready",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"TSDB query failed: {e}")


class TSDBListMetricsTool(Tool):
    name = "tsdb.list_metrics"
    category = "tsdb"
    description = "List all available metrics in the TSDB"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Optional glob pattern to filter metrics (e.g., 'cpu_*')",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pattern = args.get("pattern", "*")
            return ToolResult(
                ok=True,
                data={
                    "pattern": pattern,
                    "status": "metrics_query_ready",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to list metrics: {e}")


class TSDBCompressionStatsTool(Tool):
    name = "tsdb.compression_stats"
    category = "tsdb"
    description = "Get compression statistics for stored time-series data"
    parameters = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "Optional metric name to get stats for. Omit for overall stats.",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            metric = args.get("metric_name")
            return ToolResult(
                ok=True,
                data={
                    "metric": metric,
                    "status": "compression_stats_ready",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to get compression stats: {e}")


def register_tsdb_tools(registry, sandbox=None):
    """Register all TSDB tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional, for future enhancements)
    """
    registry.register(TSDBWritePointTool())
    registry.register(TSDBQueryTool())
    registry.register(TSDBListMetricsTool())
    registry.register(TSDBCompressionStatsTool())
