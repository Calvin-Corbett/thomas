"""
Layer 7 (application-layer) routing.

Implements path-based, header-based, and host-based routing with regex support.
"""

import re
import threading
from enum import Enum

from thomas.marketplace.load_balancer._types import Backend, RequestContext


class RouteMatchType(Enum):
    """Type of route matching."""

    EXACT = "exact"
    PREFIX = "prefix"
    REGEX = "regex"


class Route:
    """Represents a routing rule."""

    def __init__(
        self,
        path: str,
        backend: Backend,
        match_type: RouteMatchType = RouteMatchType.PREFIX,
        priority: int = 0,
        conditions: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize a route.

        Args:
            path: Path pattern to match.
            backend: Backend to route to.
            match_type: How to match the path (exact, prefix, regex).
            priority: Route priority (higher = checked first).
            conditions: Additional conditions (headers, hosts, etc).
        """
        self.path = path
        self.backend = backend
        self.match_type = match_type
        self.priority = priority
        self.conditions = conditions or {}
        self.request_count = 0

        # Compile regex if needed
        if match_type == RouteMatchType.REGEX:
            self.regex = re.compile(path)
        else:
            self.regex = None

    def matches(self, context: RequestContext) -> bool:
        """
        Check if request matches this route.

        Args:
            context: Request context.

        Returns:
            True if route matches, False otherwise.
        """
        # Check path
        if self.match_type == RouteMatchType.EXACT:
            if context.path != self.path:
                return False
        elif self.match_type == RouteMatchType.PREFIX:
            if not context.path.startswith(self.path):
                return False
        elif self.match_type == RouteMatchType.REGEX:
            if not self.regex.match(context.path):
                return False

        # Check additional conditions
        for header_name, expected_value in self.conditions.items():
            actual_value = context.headers.get(header_name, "")
            if actual_value != expected_value:
                return False

        return True

    def record_request(self) -> None:
        """Record that this route was used."""
        self.request_count += 1


class L7Router:
    """
    Layer 7 router for application-layer routing.

    Supports path-based, header-based, and host-based routing with priorities.
    """

    def __init__(self, default_backend: Backend | None = None) -> None:
        """
        Initialize L7 router.

        Args:
            default_backend: Default backend if no routes match.
        """
        self.default_backend = default_backend
        self._routes: list[Route] = []
        self._lock = threading.Lock()

    def add_route(
        self,
        path: str,
        backend: Backend,
        match_type: RouteMatchType = RouteMatchType.PREFIX,
        priority: int = 0,
        conditions: dict[str, str] | None = None,
    ) -> Route:
        """
        Add a routing rule.

        Args:
            path: Path pattern.
            backend: Target backend.
            match_type: Matching type (exact, prefix, regex).
            priority: Priority (higher = checked first).
            conditions: Header/host conditions.

        Returns:
            Route object added.
        """
        route = Route(path, backend, match_type, priority, conditions)

        with self._lock:
            self._routes.append(route)
            # Sort by priority (descending)
            self._routes.sort(key=lambda r: r.priority, reverse=True)

        return route

    def add_path_prefix_route(self, prefix: str, backend: Backend, priority: int = 0) -> Route:
        """
        Add a path prefix route.

        Args:
            prefix: Path prefix to match.
            backend: Target backend.
            priority: Route priority.

        Returns:
            Route object added.
        """
        return self.add_route(prefix, backend, RouteMatchType.PREFIX, priority)

    def add_exact_path_route(self, path: str, backend: Backend, priority: int = 0) -> Route:
        """
        Add an exact path route.

        Args:
            path: Exact path to match.
            backend: Target backend.
            priority: Route priority.

        Returns:
            Route object added.
        """
        return self.add_route(path, backend, RouteMatchType.EXACT, priority)

    def add_regex_route(self, pattern: str, backend: Backend, priority: int = 0) -> Route:
        """
        Add a regex path route.

        Args:
            pattern: Regex pattern to match.
            backend: Target backend.
            priority: Route priority.

        Returns:
            Route object added.
        """
        return self.add_route(pattern, backend, RouteMatchType.REGEX, priority)

    def add_header_route(
        self,
        path: str,
        backend: Backend,
        headers: dict[str, str],
        priority: int = 0,
    ) -> Route:
        """
        Add a route with header conditions.

        Args:
            path: Path pattern.
            backend: Target backend.
            headers: Required headers.
            priority: Route priority.

        Returns:
            Route object added.
        """
        return self.add_route(path, backend, RouteMatchType.PREFIX, priority, headers)

    def add_host_route(self, host: str, backend: Backend, priority: int = 0) -> Route:
        """
        Add a host-based route.

        Args:
            host: Host to match (in Host header).
            backend: Target backend.
            priority: Route priority.

        Returns:
            Route object added.
        """
        return self.add_route(
            "/",
            backend,
            RouteMatchType.PREFIX,
            priority,
            {"host": host},
        )

    def route(self, context: RequestContext) -> Backend | None:
        """
        Route a request to a backend.

        Args:
            context: Request context.

        Returns:
            Backend to route to, or None if no routes match.
        """
        with self._lock:
            for route in self._routes:
                if route.matches(context):
                    route.record_request()
                    return route.backend

        return self.default_backend

    def remove_route(self, path: str, backend: Backend) -> bool:
        """
        Remove a routing rule.

        Args:
            path: Path pattern of route to remove.
            backend: Backend of route to remove.

        Returns:
            True if route was removed, False if not found.
        """
        with self._lock:
            for i, route in enumerate(self._routes):
                if route.path == path and route.backend.id == backend.id:
                    del self._routes[i]
                    return True

        return False

    def clear_routes(self) -> None:
        """Remove all routing rules."""
        with self._lock:
            self._routes.clear()

    def get_routes(self) -> list[dict]:
        """
        Get all routing rules.

        Returns:
            List of route dicts with info.
        """
        with self._lock:
            return [
                {
                    "path": r.path,
                    "backend_id": r.backend.id,
                    "match_type": r.match_type.value,
                    "priority": r.priority,
                    "request_count": r.request_count,
                    "conditions": r.conditions,
                }
                for r in self._routes
            ]

    def get_route_stats(self) -> dict[str, int]:
        """
        Get request counts per route.

        Returns:
            Dict mapping route paths to request counts.
        """
        with self._lock:
            return {f"{r.path} ({r.match_type.value})": r.request_count for r in self._routes}


class VirtualHostRouter:
    """Router for virtual host (SNI) based routing."""

    def __init__(self) -> None:
        """Initialize virtual host router."""
        self._hosts: dict[str, Backend] = {}
        self._default_backend: Backend | None = None
        self._lock = threading.Lock()

    def add_host(self, hostname: str, backend: Backend) -> None:
        """
        Add a virtual host.

        Args:
            hostname: Hostname to route.
            backend: Backend to route to.
        """
        with self._lock:
            self._hosts[hostname.lower()] = backend

    def set_default(self, backend: Backend) -> None:
        """
        Set default backend for unknown hosts.

        Args:
            backend: Default backend.
        """
        with self._lock:
            self._default_backend = backend

    def route(self, hostname: str) -> Backend | None:
        """
        Route to backend by hostname.

        Args:
            hostname: Hostname to route.

        Returns:
            Backend to route to, or None if not found.
        """
        with self._lock:
            return self._hosts.get(hostname.lower(), self._default_backend)

    def remove_host(self, hostname: str) -> bool:
        """
        Remove a virtual host.

        Args:
            hostname: Hostname to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if hostname.lower() in self._hosts:
                del self._hosts[hostname.lower()]
                return True
            return False

    def get_hosts(self) -> dict[str, str]:
        """
        Get all virtual hosts.

        Returns:
            Dict mapping hostnames to backend IDs.
        """
        with self._lock:
            return {host: backend.id for host, backend in self._hosts.items()}
