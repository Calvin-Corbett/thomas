"""Tools for API Gateway module.

Provides tools for managing routes, authentication, and rate limiting.
"""

from typing import Any

from thomas.api_gateway import core
from thomas.tools.base import Tool, ToolResult


class RouteManagementTool(Tool):
    """Manage API gateway routes and routing."""

    name = "api_gateway_routes"
    category = "api_gateway"
    description = "List, add, and manage API routes"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_routes", "route_count", "route_details"],
                "description": "Route management action",
            },
            "path": {"type": "string", "description": "Route path pattern"},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                "description": "HTTP method",
            },
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "list_routes":
                routes = self.gateway.get_routes()
                return ToolResult(ok=True, data={"routes": routes})

            elif action == "route_count":
                count = len(self.gateway.routes)
                return ToolResult(ok=True, data={"total_routes": count})

            elif action == "route_details":
                routes = self.gateway.get_routes()
                return ToolResult(ok=True, data={"details": routes})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AuthenticationTool(Tool):
    """Manage authentication tokens and access control."""

    name = "api_gateway_auth"
    category = "api_gateway"
    description = "Generate, verify, and revoke authentication tokens"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_token", "verify_token", "revoke_token", "list_tokens"],
                "description": "Authentication action",
            },
            "client_id": {"type": "string", "description": "Client identifier"},
            "token": {"type": "string", "description": "Token string"},
            "scope": {"type": "array", "items": {"type": "string"}, "description": "Token scope/permissions"},
            "ttl_hours": {"type": "integer", "description": "Token time-to-live in hours"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "generate_token":
                client_id = args.get("client_id", "")
                scope = args.get("scope", ["read"])
                ttl_hours = args.get("ttl_hours", 24)

                if not client_id:
                    return ToolResult(ok=False, error="client_id required")

                token = self.gateway.auth_middleware.generate_token(client_id, scope, ttl_hours)
                return ToolResult(ok=True, data={"token": token, "client_id": client_id})

            elif action == "verify_token":
                token = args.get("token", "")
                scope = args.get("scope")

                if not token:
                    return ToolResult(ok=False, error="token required")

                valid = self.gateway.auth_middleware.verify_token(token, scope)
                return ToolResult(ok=True, data={"token_valid": valid})

            elif action == "revoke_token":
                token = args.get("token", "")

                if not token:
                    return ToolResult(ok=False, error="token required")

                revoked = self.gateway.auth_middleware.revoke_token(token)
                return ToolResult(ok=True, data={"revoked": revoked})

            elif action == "list_tokens":
                tokens = self.gateway.get_auth_tokens()
                return ToolResult(ok=True, data={"tokens": tokens})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class RateLimitingTool(Tool):
    """Manage rate limiting policies."""

    name = "api_gateway_rate_limit"
    category = "api_gateway"
    description = "Configure and monitor rate limiting"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["get_limits", "check_limit"], "description": "Rate limit action"},
            "client_id": {"type": "string", "description": "Client identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_limits":
                limits = {}
                for client_id, limiter in self.gateway.rate_limiters.items():
                    limits[client_id] = {
                        "strategy": limiter.config.strategy.value,
                        "requests_per_second": limiter.config.requests_per_second,
                        "burst_size": limiter.config.burst_size,
                        "current_tokens": limiter.tokens,
                    }
                return ToolResult(ok=True, data={"limits": limits})

            elif action == "check_limit":
                client_id = args.get("client_id", "anonymous")

                if client_id in self.gateway.rate_limiters:
                    limiter = self.gateway.rate_limiters[client_id]
                    allowed = limiter.is_allowed()
                    return ToolResult(ok=True, data={"client_id": client_id, "allowed": allowed})
                else:
                    return ToolResult(
                        ok=True, data={"client_id": client_id, "allowed": True, "message": "No limit configured"}
                    )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GatewayMonitoringTool(Tool):
    """Monitor gateway statistics and health."""

    name = "api_gateway_monitor"
    category = "api_gateway"
    description = "Get gateway stats, request logs, and health metrics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get_stats", "get_request_log", "health_check"],
                "description": "Monitoring action",
            }
        },
        "required": ["action"],
    }

    def __init__(self):
        self.gateway = core.APIGateway()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "get_stats":
                stats = self.gateway.get_request_stats()
                return ToolResult(ok=True, data=stats)

            elif action == "get_request_log":
                log = self.gateway.request_log[-20:]
                return ToolResult(ok=True, data={"recent_requests": log})

            elif action == "health_check":
                return ToolResult(
                    ok=True,
                    data={
                        "status": "healthy",
                        "gateway_name": self.gateway.name,
                        "routes_configured": len(self.gateway.routes),
                        "auth_middleware": "active",
                    },
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_api_gateway_tools(registry):
    """Register all API gateway tools."""
    registry.register(RouteManagementTool())
    registry.register(AuthenticationTool())
    registry.register(RateLimitingTool())
    registry.register(GatewayMonitoringTool())
