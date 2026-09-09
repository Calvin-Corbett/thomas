"""Service gateway with routing, service discovery, load balancing, and circuit breaker."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ServiceStatus(str, Enum):
    """Service health status."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ServiceInstance:
    """Service instance."""

    instance_id: str
    service_name: str
    host: str
    port: int
    weight: int = 100
    status: ServiceStatus = ServiceStatus.UNKNOWN
    last_check: datetime | None = None
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "instance_id": self.instance_id,
            "service_name": self.service_name,
            "host": self.host,
            "port": self.port,
            "weight": self.weight,
            "status": self.status.value,
            "error_count": self.error_count,
        }


@dataclass
class Route:
    """API route."""

    route_id: str
    path_pattern: str
    method: str
    service_name: str
    rate_limit: int = 1000
    timeout_ms: int = 5000
    enabled: bool = True


class ServiceRegistry:
    """Service discovery and registration."""

    def __init__(self):
        self.services: dict[str, dict[str, ServiceInstance]] = {}

    def register_service(self, instance: ServiceInstance) -> None:
        """Register service instance."""
        service_name = instance.service_name
        if service_name not in self.services:
            self.services[service_name] = {}
        self.services[service_name][instance.instance_id] = instance

    def deregister_service(self, service_name: str, instance_id: str) -> bool:
        """Deregister service instance."""
        if service_name in self.services:
            if instance_id in self.services[service_name]:
                del self.services[service_name][instance_id]
                return True
        return False

    def get_service_instances(self, service_name: str) -> list[ServiceInstance]:
        """Get all instances of a service."""
        return list(self.services.get(service_name, {}).values())

    def get_healthy_instances(self, service_name: str) -> list[ServiceInstance]:
        """Get healthy instances of a service."""
        instances = self.get_service_instances(service_name)
        return [i for i in instances if i.status == ServiceStatus.HEALTHY]

    def update_instance_status(self, service_name: str, instance_id: str, status: ServiceStatus) -> None:
        """Update instance status."""
        if service_name in self.services:
            if instance_id in self.services[service_name]:
                self.services[service_name][instance_id].status = status
                self.services[service_name][instance_id].last_check = datetime.now()

    def list_services(self) -> list[str]:
        """List all registered services."""
        return list(self.services.keys())

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        stats = {"services": len(self.services), "total_instances": 0, "healthy_instances": 0, "unhealthy_instances": 0}

        for instances in self.services.values():
            for instance in instances.values():
                stats["total_instances"] += 1
                if instance.status == ServiceStatus.HEALTHY:
                    stats["healthy_instances"] += 1
                else:
                    stats["unhealthy_instances"] += 1

        return stats


class LoadBalancer:
    """Load balancing strategies."""

    @staticmethod
    def round_robin(instances: list[ServiceInstance], state: dict[str, int]) -> ServiceInstance | None:
        """Round robin selection."""
        if not instances:
            return None
        idx = state.get("round_robin_idx", 0) % len(instances)
        state["round_robin_idx"] = idx + 1
        return instances[idx]

    @staticmethod
    def random_selection(instances: list[ServiceInstance]) -> ServiceInstance | None:
        """Random selection."""
        return random.choice(instances) if instances else None

    @staticmethod
    def weighted_round_robin(instances: list[ServiceInstance], state: dict[str, int]) -> ServiceInstance | None:
        """Weighted round robin selection."""
        if not instances:
            return None

        total_weight = sum(i.weight for i in instances)
        if total_weight <= 0:
            return instances[0]

        current_weight = state.get("weighted_idx", 0)
        current_weight += random.randint(1, total_weight)

        for instance in instances:
            current_weight -= instance.weight
            if current_weight <= 0:
                return instance

        return instances[-1]

    @staticmethod
    def least_connections(instances: list[ServiceInstance]) -> ServiceInstance | None:
        """Select instance with least errors."""
        if not instances:
            return None
        return min(instances, key=lambda i: i.error_count)


class CircuitBreaker:
    """Circuit breaker pattern."""

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.state = "closed"  # closed, open, half_open

    def record_success(self) -> None:
        """Record successful request."""
        if self.state == "half_open":
            self.state = "closed"
            self.failure_count = 0

    def record_failure(self) -> None:
        """Record failed request."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def is_open(self) -> bool:
        """Check if circuit is open."""
        if self.state != "open":
            return False

        if self.last_failure_time:
            elapsed = (datetime.now() - self.last_failure_time).total_seconds()
            if elapsed >= self.timeout_seconds:
                self.state = "half_open"
                return False

        return True

    def get_state(self) -> dict[str, Any]:
        """Get circuit state."""
        return {"state": self.state, "failure_count": self.failure_count, "threshold": self.failure_threshold}


class APIGateway:
    """API Gateway."""

    def __init__(self):
        self.registry = ServiceRegistry()
        self.routes: dict[str, Route] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self.load_balancer_state: dict[str, dict[str, int]] = {}
        self._route_counter = 0

    def register_route(
        self, path_pattern: str, method: str, service_name: str, rate_limit: int = 1000, timeout_ms: int = 5000
    ) -> str:
        """Register a route."""
        self._route_counter += 1
        route_id = f"route_{self._route_counter}"

        route = Route(
            route_id=route_id,
            path_pattern=path_pattern,
            method=method,
            service_name=service_name,
            rate_limit=rate_limit,
            timeout_ms=timeout_ms,
        )
        self.routes[route_id] = route
        return route_id

    def get_routes(self) -> list[dict[str, Any]]:
        """Get all routes."""
        return [
            {
                "route_id": r.route_id,
                "path": r.path_pattern,
                "method": r.method,
                "service": r.service_name,
                "enabled": r.enabled,
            }
            for r in self.routes.values()
        ]

    def route_request(self, method: str, path: str) -> ServiceInstance | None:
        """Find service instance for request."""
        matching_route = None
        for route in self.routes.values():
            if route.method == method and route.enabled and path.startswith(route.path_pattern):
                matching_route = route
                break

        if not matching_route:
            return None

        service_name = matching_route.service_name

        # Check circuit breaker
        if service_name in self.circuit_breakers:
            if self.circuit_breakers[service_name].is_open():
                return None

        # Get healthy instances
        instances = self.registry.get_healthy_instances(service_name)
        if not instances:
            return None

        # Load balance
        if service_name not in self.load_balancer_state:
            self.load_balancer_state[service_name] = {}

        return LoadBalancer.round_robin(instances, self.load_balancer_state[service_name])

    def record_request(self, service_name: str, success: bool) -> None:
        """Record request outcome."""
        if service_name not in self.circuit_breakers:
            self.circuit_breakers[service_name] = CircuitBreaker()

        cb = self.circuit_breakers[service_name]
        if success:
            cb.record_success()
        else:
            cb.record_failure()

    def get_gateway_stats(self) -> dict[str, Any]:
        """Get gateway statistics."""
        return {
            "routes": len(self.routes),
            "services": len(self.registry.services),
            "registry_stats": self.registry.get_stats(),
            "circuit_breakers": {name: cb.get_state() for name, cb in self.circuit_breakers.items()},
        }
