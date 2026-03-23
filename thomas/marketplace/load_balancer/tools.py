"""Tools for load balancer infrastructure - routing, health checks, and traffic management."""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class LoadBalancerAddBackendTool(Tool):
    """Add a backend server to a load balancer."""

    name = "load_balancer.add_backend"
    category = "infrastructure"
    description = "Add a backend server to the load balancer pool with weight and health check settings"
    parameters = {
        "type": "object",
        "properties": {
            "pool_id": {"type": "string", "description": "Load balancer pool identifier"},
            "host": {"type": "string", "description": "Backend server host or IP"},
            "port": {"type": "integer", "description": "Backend server port"},
            "weight": {"type": "integer", "description": "Server weight for traffic distribution"},
            "enabled": {"type": "boolean", "description": "Initial enabled state"},
        },
        "required": ["pool_id", "host", "port"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pool_id = args["pool_id"]
            host = args["host"]
            port = args["port"]
            weight = args.get("weight", 1)

            return ToolResult(
                ok=True,
                data={
                    "backend_id": f"{host}:{port}",
                    "pool_id": pool_id,
                    "status": "added",
                    "weight": weight,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LoadBalancerRemoveBackendTool(Tool):
    """Remove a backend server from a load balancer."""

    name = "load_balancer.remove_backend"
    category = "infrastructure"
    description = "Remove a backend server from the load balancer pool gracefully"
    parameters = {
        "type": "object",
        "properties": {
            "pool_id": {"type": "string", "description": "Load balancer pool identifier"},
            "backend_id": {"type": "string", "description": "Backend server identifier"},
            "drain_connections": {"type": "boolean", "description": "Wait for existing connections to close"},
        },
        "required": ["pool_id", "backend_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pool_id = args["pool_id"]
            backend_id = args["backend_id"]
            drain = args.get("drain_connections", True)

            return ToolResult(
                ok=True,
                data={
                    "backend_id": backend_id,
                    "pool_id": pool_id,
                    "status": "removed",
                    "active_connections_drained": drain,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LoadBalancerGetHealthStatusTool(Tool):
    """Get health status of backends in a pool."""

    name = "load_balancer.get_health_status"
    category = "infrastructure"
    description = "Get detailed health status of all backend servers in a pool including check results"
    parameters = {
        "type": "object",
        "properties": {
            "pool_id": {"type": "string", "description": "Load balancer pool identifier"},
        },
        "required": ["pool_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pool_id = args["pool_id"]

            return ToolResult(
                ok=True,
                data={
                    "pool_id": pool_id,
                    "healthy_backends": 3,
                    "unhealthy_backends": 0,
                    "total_backends": 3,
                    "backends": [
                        {"id": "server1", "status": "healthy", "response_time_ms": 45},
                    ],
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LoadBalancerGetPoolStatisticsTool(Tool):
    """Get traffic statistics for a load balancer pool."""

    name = "load_balancer.get_pool_statistics"
    category = "infrastructure"
    description = "Get traffic metrics, request distribution, and performance statistics for a pool"
    parameters = {
        "type": "object",
        "properties": {
            "pool_id": {"type": "string", "description": "Load balancer pool identifier"},
            "time_window_minutes": {"type": "integer", "description": "Time window for metrics (default 60)"},
        },
        "required": ["pool_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pool_id = args["pool_id"]
            time_window = args.get("time_window_minutes", 60)

            return ToolResult(
                ok=True,
                data={
                    "pool_id": pool_id,
                    "time_window_minutes": time_window,
                    "total_requests": 50000,
                    "requests_per_second": 14.0,
                    "error_rate_percent": 0.5,
                    "average_response_time_ms": 125,
                    "p99_response_time_ms": 450,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LoadBalancerSetRoutingPolicyTool(Tool):
    """Set routing policy for a load balancer pool."""

    name = "load_balancer.set_routing_policy"
    category = "infrastructure"
    description = "Set the load balancing algorithm (round-robin, least-connections, ip-hash, etc.)"
    parameters = {
        "type": "object",
        "properties": {
            "pool_id": {"type": "string", "description": "Load balancer pool identifier"},
            "policy": {
                "type": "string",
                "enum": ["round_robin", "least_connections", "ip_hash", "random", "weighted_round_robin"],
                "description": "Routing policy",
            },
        },
        "required": ["pool_id", "policy"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pool_id = args["pool_id"]
            policy = args["policy"]

            return ToolResult(
                ok=True,
                data={
                    "pool_id": pool_id,
                    "routing_policy": policy,
                    "status": "applied",
                    "effective_immediately": True,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_load_balancer_tools(registry):
    """Register all load balancer tools with the registry."""
    registry.register(LoadBalancerAddBackendTool())
    registry.register(LoadBalancerRemoveBackendTool())
    registry.register(LoadBalancerGetHealthStatusTool())
    registry.register(LoadBalancerGetPoolStatisticsTool())
    registry.register(LoadBalancerSetRoutingPolicyTool())
