"""
Thomas Load Balancer Engine

A production-ready load balancing module implementing multiple algorithms,
health checking, circuit breaking, rate limiting, and connection pooling.
"""

from thomas.load_balancer._exceptions import (
    BackendError,
    CircuitOpenError,
    LoadBalancerError,
    NoHealthyBackendError,
)
from thomas.load_balancer._types import (
    Backend,
    BackendPool,
    CircuitState,
    HealthCheckConfig,
    HealthStatus,
    LoadBalancerConfig,
    RequestContext,
    RoutingDecision,
)
from thomas.load_balancer.algorithms import (
    ConsistentHash,
    IPHash,
    LeastConnections,
    LeastResponseTime,
    RandomChoice,
    ResourceBased,
    RoundRobin,
    WeightedLeastConnections,
    WeightedRandom,
    WeightedRoundRobin,
)
from thomas.load_balancer.balancer import LoadBalancer
from thomas.load_balancer.circuit_breaker import CircuitBreaker
from thomas.load_balancer.connection_pool import ConnectionPool
from thomas.load_balancer.health_check import HealthChecker
from thomas.load_balancer.l7_router import L7Router
from thomas.load_balancer.metrics import MetricsCollector
from thomas.load_balancer.rate_limiter import RateLimiter
from thomas.load_balancer.sticky_sessions import SessionManager

__all__ = [
    # Types
    "Backend",
    "BackendPool",
    "CircuitState",
    "HealthCheckConfig",
    "HealthStatus",
    "LoadBalancerConfig",
    "RequestContext",
    "RoutingDecision",
    # Exceptions
    "BackendError",
    "CircuitOpenError",
    "LoadBalancerError",
    "NoHealthyBackendError",
    # Algorithms
    "ConsistentHash",
    "IPHash",
    "LeastConnections",
    "LeastResponseTime",
    "RandomChoice",
    "ResourceBased",
    "RoundRobin",
    "WeightedLeastConnections",
    "WeightedRandom",
    "WeightedRoundRobin",
    # Components
    "HealthChecker",
    "CircuitBreaker",
    "SessionManager",
    "RateLimiter",
    "ConnectionPool",
    "MetricsCollector",
    "LoadBalancer",
    "L7Router",
]

__version__ = "1.0.0"
