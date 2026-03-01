"""API Gateway core - routing, rate limiting, and auth middleware.

Provides API gateway functionality with request routing, rate limiting,
and authentication middleware for managing API traffic.
"""

import hashlib
import logging
import os
import secrets
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class RateLimitStrategy(str, Enum):
    """Rate limiting strategies."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    requests_per_second: float = 100.0
    burst_size: int = 200
    window_size_seconds: int = 60


@dataclass
class Route:
    """API route definition."""

    path: str
    method: str
    handler: Callable
    auth_required: bool = False
    rate_limit: RateLimitConfig | None = None
    description: str = ""


@dataclass
class RateLimiter:
    """Token bucket rate limiter."""

    config: RateLimitConfig
    tokens: float = field(default_factory=lambda: 200.0)
    last_refill: datetime = field(default_factory=datetime.now)
    request_times: list[datetime] = field(default_factory=list)

    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit."""
        if self.config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            return self._token_bucket_check()
        elif self.config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            return self._sliding_window_check()
        else:  # FIXED_WINDOW
            return self._fixed_window_check()

    def _token_bucket_check(self) -> bool:
        """Token bucket algorithm check."""
        now = datetime.now()
        elapsed = (now - self.last_refill).total_seconds()
        refill_rate = self.config.requests_per_second

        self.tokens = min(self.config.burst_size, self.tokens + elapsed * refill_rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def _sliding_window_check(self) -> bool:
        """Sliding window rate limiting."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.config.window_size_seconds)

        self.request_times = [t for t in self.request_times if t > cutoff]

        if len(self.request_times) < self.config.requests_per_second * self.config.window_size_seconds:
            self.request_times.append(now)
            return True
        return False

    def _fixed_window_check(self) -> bool:
        """Fixed window rate limiting."""
        now = datetime.now()
        cutoff = now - timedelta(seconds=self.config.window_size_seconds)

        self.request_times = [t for t in self.request_times if t > cutoff]

        if len(self.request_times) < self.config.requests_per_second * self.config.window_size_seconds:
            self.request_times.append(now)
            return True
        return False


@dataclass
class AuthToken:
    """Authentication token."""

    token: str
    client_id: str
    scope: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """Check if token is still valid."""
        if self.expires_at and datetime.now() > self.expires_at:
            return False
        return True


class AuthMiddleware:
    """Authentication middleware for API gateway."""

    def __init__(self):
        self.tokens: dict[str, AuthToken] = {}
        self.secret_key: str = os.environ.get("THOMAS_SECRET_KEY", "")
        if not self.secret_key:
            warnings.warn(
                "THOMAS_SECRET_KEY not set — using random key. Set this env var for production.",
                stacklevel=2,
            )
            self.secret_key = secrets.token_hex(32)

    def register_token(self, token: AuthToken) -> None:
        """Register an authentication token."""
        self.tokens[token.token] = token

    def revoke_token(self, token: str) -> bool:
        """Revoke an authentication token."""
        if token in self.tokens:
            del self.tokens[token]
            return True
        return False

    def verify_token(self, token: str, required_scope: list[str] | None = None) -> bool:
        """Verify an authentication token."""
        if token not in self.tokens:
            return False

        auth_token = self.tokens[token]
        if not auth_token.is_valid():
            return False

        if required_scope:
            if not any(scope in auth_token.scope for scope in required_scope):
                return False

        return True

    def generate_token(self, client_id: str, scope: list[str], ttl_hours: int = 24) -> str:
        """Generate a new authentication token."""
        token = secrets.token_hex(32)

        expires_at = datetime.now() + timedelta(hours=ttl_hours)
        auth_token = AuthToken(token=token, client_id=client_id, scope=scope, expires_at=expires_at)
        self.register_token(auth_token)
        return token


class APIGateway:
    """Main API Gateway class."""

    def __init__(self, name: str = "api_gateway"):
        self.name = name
        self.routes: dict[str, Route] = {}
        self.auth_middleware = AuthMiddleware()
        self.rate_limiters: dict[str, RateLimiter] = {}
        self.request_log: list[dict[str, Any]] = []
        self.response_interceptors: list[Callable] = []
        self.error_handlers: dict[type, Callable] = {}

    def add_route(self, route: Route) -> None:
        """Add a route to the gateway."""
        route_key = f"{route.method} {route.path}"
        self.routes[route_key] = route

    def remove_route(self, path: str, method: str = "GET") -> bool:
        """Remove a route from the gateway."""
        route_key = f"{method} {path}"
        if route_key in self.routes:
            del self.routes[route_key]
            return True
        return False

    def register_error_handler(self, error_type: type, handler: Callable) -> None:
        """Register an error handler."""
        self.error_handlers[error_type] = handler

    def add_response_interceptor(self, interceptor: Callable) -> None:
        """Add a response interceptor."""
        self.response_interceptors.append(interceptor)

    async def handle_request(
        self,
        path: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        """Handle an incoming request."""
        route_key = f"{method} {path}"

        # Log request
        self.request_log.append(
            {"timestamp": datetime.now().isoformat(), "path": path, "method": method, "client_id": client_id}
        )
        if len(self.request_log) > 10000:
            self.request_log = self.request_log[-5000:]

        # Check authentication
        if headers and "Authorization" in headers:
            token = headers["Authorization"].replace("Bearer ", "")
            if not self.auth_middleware.verify_token(token):
                return {"status": 401, "error": "Unauthorized", "message": "Invalid or expired token"}

        # Find and execute route
        if route_key not in self.routes:
            return {"status": 404, "error": "Not Found", "message": f"Route not found: {route_key}"}

        route = self.routes[route_key]

        # Check auth requirement
        if route.auth_required and (not headers or "Authorization" not in headers):
            return {"status": 403, "error": "Forbidden", "message": "Authentication required"}

        # Rate limiting
        limiter_key = client_id or "anonymous"
        if limiter_key not in self.rate_limiters and route.rate_limit:
            self.rate_limiters[limiter_key] = RateLimiter(route.rate_limit)

        if limiter_key in self.rate_limiters:
            if not self.rate_limiters[limiter_key].is_allowed():
                return {"status": 429, "error": "Too Many Requests", "message": "Rate limit exceeded"}

        # Execute handler
        try:
            result = await route.handler(body or {})
            response = {"status": 200, "data": result}
        except Exception as e:
            handler = self.error_handlers.get(type(e))
            if handler:
                response = await handler(e)
            else:
                log.exception("Handler error for %s", route_key)
                response = {"status": 500, "error": "Internal Server Error", "message": "An unexpected error occurred"}

        # Apply interceptors
        for interceptor in self.response_interceptors:
            response = await interceptor(response)

        return response

    def get_routes(self) -> list[dict[str, Any]]:
        """Get all registered routes."""
        return [
            {
                "path": route.path,
                "method": route.method,
                "auth_required": route.auth_required,
                "description": route.description,
            }
            for route in self.routes.values()
        ]

    def get_request_stats(self) -> dict[str, Any]:
        """Get request statistics."""
        total_requests = len(self.request_log)

        return {
            "total_requests": total_requests,
            "unique_clients": len(set(r.get("client_id") for r in self.request_log)),
            "recent_requests": self.request_log[-10:],
            "routes_count": len(self.routes),
            "rate_limiters_active": len(self.rate_limiters),
        }

    def get_auth_tokens(self) -> list[dict[str, Any]]:
        """Get all registered tokens (metadata only)."""
        return [
            {
                "client_id": token.client_id,
                "scope": token.scope,
                "created_at": token.created_at.isoformat(),
                "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                "valid": token.is_valid(),
            }
            for token in self.auth_middleware.tokens.values()
        ]
