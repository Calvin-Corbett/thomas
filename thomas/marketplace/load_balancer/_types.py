"""
Type definitions for the load balancer module.

Includes data classes for backend configuration, health status, routing decisions,
and configuration structures.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthStatus(Enum):
    """Health status of a backend."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CircuitState(Enum):
    """State of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class Backend:
    """
    Represents a backend server in the load balancer pool.

    Attributes:
        id: Unique identifier for the backend.
        host: Hostname or IP address of the backend.
        port: Port number the backend listens on.
        weight: Weight for weighted algorithms (default 1).
        max_connections: Maximum concurrent connections (default unlimited).
        metadata: Additional arbitrary metadata about the backend.
    """

    id: str
    host: str
    port: int
    weight: int = 1
    max_connections: int = 0  # 0 means unlimited
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate backend configuration."""
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Invalid port: {self.port}")
        if self.weight < 0:
            raise ValueError(f"Weight cannot be negative: {self.weight}")
        if self.max_connections < 0:
            raise ValueError(f"max_connections cannot be negative: {self.max_connections}")

    def __hash__(self) -> int:
        """Make backend hashable for use in sets/dicts."""
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        """Compare backends by ID."""
        if not isinstance(other, Backend):
            return NotImplemented
        return self.id == other.id


@dataclass
class BackendPool:
    """
    Represents a pool of backend servers.

    Attributes:
        backends: List of backend servers.
    """

    backends: list[Backend] = field(default_factory=list)

    def add(self, backend: Backend) -> None:
        """Add a backend to the pool."""
        if any(b.id == backend.id for b in self.backends):
            raise ValueError(f"Backend {backend.id} already exists")
        self.backends.append(backend)

    def remove(self, backend_id: str) -> Backend | None:
        """Remove a backend from the pool by ID."""
        for i, backend in enumerate(self.backends):
            if backend.id == backend_id:
                return self.backends.pop(i)
        return None

    def get(self, backend_id: str) -> Backend | None:
        """Get a backend by ID."""
        for backend in self.backends:
            if backend.id == backend_id:
                return backend
        return None

    def __len__(self) -> int:
        """Return the number of backends."""
        return len(self.backends)

    def __iter__(self):
        """Allow iteration over backends."""
        return iter(self.backends)


@dataclass
class RequestContext:
    """
    Context information about a client request.

    Attributes:
        client_ip: IP address of the client.
        path: HTTP request path.
        headers: HTTP request headers.
        session_id: Optional session identifier.
        timestamp: Request timestamp (unix epoch).
    """

    client_ip: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class RoutingDecision:
    """
    Result of a routing decision.

    Attributes:
        backend: Selected backend for the request.
        latency_estimate: Estimated latency in milliseconds.
        algorithm_name: Name of the algorithm used for selection.
    """

    backend: Backend
    latency_estimate: float = 0.0
    algorithm_name: str = ""


@dataclass
class HealthCheckConfig:
    """
    Configuration for health checking.

    Attributes:
        enabled: Whether health checking is enabled.
        interval: Interval in seconds between health checks.
        timeout: Timeout in seconds for each check.
        healthy_threshold: Number of successful checks to mark healthy.
        unhealthy_threshold: Number of failed checks to mark unhealthy.
        check_type: Type of check ('tcp' or 'http').
        http_path: Path for HTTP checks (only used if check_type='http').
        http_expected_status: Expected HTTP status code for HTTP checks.
        custom_check_fn: Optional custom check function.
    """

    enabled: bool = True
    interval: int = 10
    timeout: int = 5
    healthy_threshold: int = 2
    unhealthy_threshold: int = 3
    check_type: str = "tcp"
    http_path: str = "/"
    http_expected_status: int = 200
    custom_check_fn: Callable[[Backend], bool] | None = None

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.interval < 1:
            raise ValueError(f"interval must be >= 1, got {self.interval}")
        if self.timeout < 1:
            raise ValueError(f"timeout must be >= 1, got {self.timeout}")
        if self.timeout > self.interval:
            raise ValueError("timeout cannot exceed interval")
        if self.healthy_threshold < 1:
            raise ValueError("healthy_threshold must be >= 1")
        if self.unhealthy_threshold < 1:
            raise ValueError("unhealthy_threshold must be >= 1")
        if self.check_type not in ("tcp", "http"):
            raise ValueError(f"check_type must be 'tcp' or 'http', got {self.check_type}")


@dataclass
class LoadBalancerConfig:
    """
    Configuration for the load balancer.

    Attributes:
        algorithm: Name of the load balancing algorithm.
        health_check: Health check configuration.
        enable_circuit_breaker: Whether to enable circuit breaker.
        enable_rate_limiter: Whether to enable rate limiting.
        enable_connection_pool: Whether to enable connection pooling.
        enable_sticky_sessions: Whether to enable sticky sessions.
        drain_timeout: Timeout in seconds for graceful shutdown.
    """

    algorithm: str = "round_robin"
    health_check: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    enable_circuit_breaker: bool = True
    enable_rate_limiter: bool = True
    enable_connection_pool: bool = True
    enable_sticky_sessions: bool = False
    drain_timeout: int = 30
