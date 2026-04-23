"""Service mesh for service-to-service communication and traffic management.

Provides service discovery, load balancing, circuit breaking,
and traffic policies.
"""

from .core import (
    CircuitBreaker,
    CircuitBreakerState,
    LoadBalancer,
    Service,
    ServiceEndpoint,
    ServiceMesh,
    ServiceRegistry,
    ServiceStatus,
    TrafficPolicy,
)

__all__ = [
    "ServiceStatus",
    "ServiceEndpoint",
    "Service",
    "CircuitBreakerState",
    "CircuitBreaker",
    "LoadBalancer",
    "ServiceRegistry",
    "TrafficPolicy",
    "ServiceMesh",
]

__version__ = "1.0.0"
