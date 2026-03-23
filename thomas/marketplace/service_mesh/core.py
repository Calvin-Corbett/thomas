"""Service mesh for service-to-service communication, traffic management, and observability.

Provides service discovery, load balancing, circuit breaking, and distributed tracing.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ServiceStatus(Enum):
    """Service status."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ServiceEndpoint:
    """Service endpoint."""

    host: str
    port: int
    weight: int = 100
    status: ServiceStatus = ServiceStatus.HEALTHY


@dataclass
class Service:
    """Service definition."""

    name: str
    namespace: str = "default"
    endpoints: list[ServiceEndpoint] = field(default_factory=list)
    version: str = "1.0.0"
    metadata: dict[str, str] = field(default_factory=dict)

    def add_endpoint(self, endpoint: ServiceEndpoint) -> None:
        """Add endpoint."""
        self.endpoints.append(endpoint)

    def get_healthy_endpoints(self) -> list[ServiceEndpoint]:
        """Get healthy endpoints."""
        return [e for e in self.endpoints if e.status == ServiceStatus.HEALTHY]


class CircuitBreakerState(Enum):
    """Circuit breaker state."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker."""

    name: str
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    failure_threshold: int = 5
    success_threshold: int = 2
    last_failure_time: datetime | None = None
    timeout_seconds: int = 60

    def record_failure(self) -> None:
        """Record failure."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def record_success(self) -> None:
        """Record success."""
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = CircuitBreakerState.CLOSED
                self.failure_count = 0
                self.success_count = 0

    def can_execute(self) -> bool:
        """Check if request can execute."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            if self.last_failure_time:
                age = (datetime.utcnow() - self.last_failure_time).total_seconds()
                if age > self.timeout_seconds:
                    self.state = CircuitBreakerState.HALF_OPEN
                    return True
            return False

        return True


class LoadBalancer:
    """Load balancer."""

    def __init__(self, name: str):
        self.name = name
        self.strategy = "round_robin"
        self.current_index = 0

    def select_endpoint(self, endpoints: list[ServiceEndpoint]) -> ServiceEndpoint | None:
        """Select endpoint using strategy."""
        if not endpoints:
            return None

        # Round-robin
        endpoint = endpoints[self.current_index % len(endpoints)]
        self.current_index += 1
        return endpoint


class ServiceRegistry:
    """Service registry."""

    def __init__(self):
        self.services: dict[str, Service] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

    def register_service(self, service: Service) -> None:
        """Register service."""
        key = f"{service.namespace}/{service.name}"
        self.services[key] = service

    def deregister_service(self, name: str, namespace: str = "default") -> bool:
        """Deregister service."""
        key = f"{namespace}/{name}"
        if key in self.services:
            del self.services[key]
            return True
        return False

    def discover_service(self, name: str, namespace: str = "default") -> Service | None:
        """Discover service."""
        key = f"{namespace}/{name}"
        return self.services.get(key)

    def get_circuit_breaker(self, service_name: str) -> CircuitBreaker:
        """Get circuit breaker for service."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker(name=service_name)
        return self.circuit_breakers[service_name]

    def list_services(self) -> list[Service]:
        """List all services."""
        return list(self.services.values())


class TrafficPolicy:
    """Traffic management policy."""

    def __init__(self, name: str):
        self.name = name
        self.timeout_ms: int = 5000
        self.retries: int = 3
        self.load_balancer_policy: str = "round_robin"
        self.rate_limit: int | None = None

    def apply(self) -> dict[str, Any]:
        """Apply policy."""
        return {
            "timeout_ms": self.timeout_ms,
            "retries": self.retries,
            "lb_policy": self.load_balancer_policy,
            "rate_limit": self.rate_limit,
        }


class ServiceMesh:
    """Service mesh."""

    def __init__(self):
        self.registry = ServiceRegistry()
        self.load_balancers: dict[str, LoadBalancer] = {}
        self.traffic_policies: dict[str, TrafficPolicy] = {}

    def register_service(self, service: Service) -> None:
        """Register service with mesh."""
        self.registry.register_service(service)
        lb_key = f"{service.namespace}/{service.name}"
        self.load_balancers[lb_key] = LoadBalancer(name=service.name)

    def get_service_endpoint(self, service_name: str, namespace: str = "default") -> str | None:
        """Get endpoint for service."""
        service = self.registry.discover_service(service_name, namespace)
        if not service:
            return None

        healthy = service.get_healthy_endpoints()
        if not healthy:
            return None

        lb_key = f"{namespace}/{service_name}"
        lb = self.load_balancers.get(lb_key)
        if lb:
            endpoint = lb.select_endpoint(healthy)
            if endpoint:
                return f"{endpoint.host}:{endpoint.port}"

        return None

    def apply_traffic_policy(self, service_name: str, policy: TrafficPolicy) -> None:
        """Apply traffic policy to service."""
        self.traffic_policies[service_name] = policy

    def get_traffic_policy(self, service_name: str) -> TrafficPolicy | None:
        """Get traffic policy."""
        return self.traffic_policies.get(service_name)

    def get_mesh_stats(self) -> dict[str, Any]:
        """Get mesh statistics."""
        return {
            "total_services": len(self.registry.services),
            "total_endpoints": sum(len(s.endpoints) for s in self.registry.services.values()),
            "policies": len(self.traffic_policies),
        }
