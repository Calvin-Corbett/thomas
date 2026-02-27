"""Tools for API gateway operations."""

from typing import Any

from thomas.gateway import core
from thomas.tools.base import Tool, ToolResult


class ServiceRegistrationTool(Tool):
    """Register and manage services."""

    name = "gateway_services"
    category = "gateway"
    description = "Register and manage service instances"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["register", "deregister", "list_instances", "update_status"],
                "description": "Service action",
            },
            "service_name": {"type": "string", "description": "Service name"},
            "instance_id": {"type": "string", "description": "Instance ID"},
            "host": {"type": "string", "description": "Host address"},
            "port": {"type": "integer", "description": "Port number"},
            "status": {
                "type": "string",
                "enum": ["healthy", "unhealthy", "degraded", "unknown"],
                "description": "Instance status",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "register":
                service_name = args.get("service_name", "")
                instance_id = args.get("instance_id", "")
                host = args.get("host", "")
                port = args.get("port", 0)

                if not all([service_name, instance_id, host, port]):
                    return ToolResult(ok=False, error="service_name, instance_id, host, port required")

                instance = core.ServiceInstance(
                    instance_id=instance_id, service_name=service_name, host=host, port=port
                )
                self.gateway.registry.register_service(instance)
                return ToolResult(ok=True, data={"registered": True})

            elif action == "deregister":
                service_name = args.get("service_name", "")
                instance_id = args.get("instance_id", "")

                if not service_name or not instance_id:
                    return ToolResult(ok=False, error="service_name and instance_id required")

                success = self.gateway.registry.deregister_service(service_name, instance_id)
                return ToolResult(ok=True, data={"deregistered": success})

            elif action == "list_instances":
                service_name = args.get("service_name", "")
                if not service_name:
                    return ToolResult(ok=False, error="service_name required")

                instances = self.gateway.registry.get_service_instances(service_name)
                return ToolResult(
                    ok=True, data={"instances": [i.to_dict() for i in instances], "count": len(instances)}
                )

            elif action == "update_status":
                service_name = args.get("service_name", "")
                instance_id = args.get("instance_id", "")
                status_str = args.get("status", "unknown")

                if not service_name or not instance_id:
                    return ToolResult(ok=False, error="service_name and instance_id required")

                self.gateway.registry.update_instance_status(service_name, instance_id, core.ServiceStatus(status_str))
                return ToolResult(ok=True, data={"updated": True})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RoutingTool(Tool):
    """Configure and manage routes."""

    name = "gateway_routing"
    category = "gateway"
    description = "Configure API routes and routing rules"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_route", "list_routes", "route_request", "gateway_stats"],
                "description": "Routing action",
            },
            "path": {"type": "string", "description": "Path pattern"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
            "service_name": {"type": "string", "description": "Target service"},
            "rate_limit": {"type": "integer", "description": "Rate limit (requests/second)"},
            "timeout_ms": {"type": "integer", "description": "Timeout in milliseconds"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "add_route":
                path = args.get("path", "")
                method = args.get("method", "GET")
                service_name = args.get("service_name", "")
                rate_limit = args.get("rate_limit", 1000)
                timeout_ms = args.get("timeout_ms", 5000)

                if not path or not service_name:
                    return ToolResult(ok=False, error="path and service_name required")

                route_id = self.gateway.register_route(path, method, service_name, rate_limit, timeout_ms)
                return ToolResult(ok=True, data={"route_id": route_id})

            elif action == "list_routes":
                routes = self.gateway.get_routes()
                return ToolResult(ok=True, data={"routes": routes, "count": len(routes)})

            elif action == "route_request":
                method = args.get("method", "GET")
                path = args.get("path", "")

                if not path:
                    return ToolResult(ok=False, error="path required")

                instance = self.gateway.route_request(method, path)
                if not instance:
                    return ToolResult(ok=False, error="No healthy service instance found")

                return ToolResult(
                    ok=True, data={"service": instance.service_name, "host": instance.host, "port": instance.port}
                )

            elif action == "gateway_stats":
                stats = self.gateway.get_gateway_stats()
                return ToolResult(ok=True, data=stats)

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_gateway_tools(registry):
    """Register all gateway tools."""
    registry.register(ServiceRegistrationTool())
    registry.register(RoutingTool())
