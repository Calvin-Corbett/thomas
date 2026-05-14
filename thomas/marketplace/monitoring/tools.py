"""Tools for monitoring infrastructure - metrics collection, alerting, and anomaly detection."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class MonitoringGetMetricsTool(Tool):
    """Query monitoring metrics for a resource."""

    name = "monitoring.get_metrics"
    category = "infrastructure"
    description = "Query metrics for resources with time-range filtering and aggregation options"
    parameters = {
        "type": "object",
        "properties": {
            "metric_name": {
                "type": "string",
                "description": "Name of the metric (cpu_usage, memory_usage, requests_per_second, etc.)",
            },
            "resource_id": {"type": "string", "description": "Resource identifier"},
            "start_time": {"type": "string", "description": "Start time (ISO 8601)"},
            "end_time": {"type": "string", "description": "End time (ISO 8601)"},
            "aggregation": {
                "type": "string",
                "enum": ["avg", "sum", "min", "max", "count"],
                "description": "Aggregation method",
            },
        },
        "required": ["metric_name", "resource_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            metric_name = args["metric_name"]
            resource_id = args["resource_id"]
            aggregation = args.get("aggregation", "avg")

            return ToolResult(
                ok=True,
                data={
                    "metric_name": metric_name,
                    "resource_id": resource_id,
                    "aggregation": aggregation,
                    "data_points": 120,
                    "values": [{"timestamp": "2026-02-27T10:00:00Z", "value": 45.5}],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MonitoringCreateAlertTool(Tool):
    """Create a monitoring alert for a metric threshold."""

    name = "monitoring.create_alert"
    category = "infrastructure"
    description = "Create an alert that triggers when a metric crosses a threshold"
    parameters = {
        "type": "object",
        "properties": {
            "alert_name": {"type": "string", "description": "Alert name"},
            "metric_name": {"type": "string", "description": "Metric to monitor"},
            "threshold": {"type": "number", "description": "Threshold value"},
            "comparison": {
                "type": "string",
                "enum": ["greater_than", "less_than", "equals"],
                "description": "Comparison operator",
            },
            "duration_seconds": {"type": "integer", "description": "Duration for condition to be true before alerting"},
            "severity": {
                "type": "string",
                "enum": ["critical", "warning", "info"],
                "description": "Alert severity level",
            },
        },
        "required": ["alert_name", "metric_name", "threshold", "comparison"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            alert_name = args["alert_name"]
            metric_name = args["metric_name"]
            threshold = args["threshold"]

            return ToolResult(
                ok=True,
                data={
                    "alert_id": f"alert_{alert_name}",
                    "alert_name": alert_name,
                    "metric_name": metric_name,
                    "threshold": threshold,
                    "status": "created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MonitoringGetAnomaliesTool(Tool):
    """Detect anomalies in metrics."""

    name = "monitoring.get_anomalies"
    category = "infrastructure"
    description = "Detect anomalies in metric data using statistical analysis or ML models"
    parameters = {
        "type": "object",
        "properties": {
            "metric_name": {"type": "string", "description": "Metric to analyze"},
            "resource_id": {"type": "string", "description": "Resource identifier"},
            "time_window_hours": {"type": "integer", "description": "Time window for analysis"},
            "sensitivity": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "Anomaly detection sensitivity",
            },
        },
        "required": ["metric_name", "resource_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            metric_name = args["metric_name"]
            resource_id = args["resource_id"]
            sensitivity = args.get("sensitivity", "medium")

            return ToolResult(
                ok=True,
                data={
                    "metric_name": metric_name,
                    "resource_id": resource_id,
                    "anomalies_detected": 2,
                    "sensitivity": sensitivity,
                    "anomalies": [
                        {"timestamp": "2026-02-27T08:30:00Z", "value": 98.5, "expected_range": [40, 60]},
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MonitoringGetDashboardTool(Tool):
    """Get monitoring dashboard data."""

    name = "monitoring.get_dashboard"
    category = "infrastructure"
    description = "Get aggregated dashboard view with multiple metrics and alerts"
    parameters = {
        "type": "object",
        "properties": {
            "dashboard_name": {"type": "string", "description": "Dashboard name or predefined template"},
        },
        "required": ["dashboard_name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            dashboard_name = args["dashboard_name"]

            return ToolResult(
                ok=True,
                data={
                    "dashboard_name": dashboard_name,
                    "last_updated": "2026-02-27T10:15:00Z",
                    "widgets": [
                        {"name": "cpu_usage", "current_value": 45.5, "status": "normal"},
                        {"name": "memory_usage", "current_value": 62.0, "status": "normal"},
                    ],
                    "active_alerts": 0,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MonitoringGetHealthChecksTool(Tool):
    """Get health check status for services."""

    name = "monitoring.get_health_checks"
    category = "infrastructure"
    description = "Get health check status for all monitored services and endpoints"
    parameters = {
        "type": "object",
        "properties": {
            "service_filter": {"type": "string", "description": "Optional service name filter"},
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            args.get("service_filter")

            return ToolResult(
                ok=True,
                data={
                    "total_services": 12,
                    "healthy": 11,
                    "unhealthy": 1,
                    "last_check": "2026-02-27T10:15:00Z",
                    "services": [
                        {"name": "api_server", "status": "healthy", "response_time_ms": 45},
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_monitoring_tools(registry):
    """Register all monitoring tools with the registry."""
    registry.register(MonitoringGetMetricsTool())
    registry.register(MonitoringCreateAlertTool())
    registry.register(MonitoringGetAnomaliesTool())
    registry.register(MonitoringGetDashboardTool())
    registry.register(MonitoringGetHealthChecksTool())
