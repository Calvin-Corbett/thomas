"""
Main load balancer orchestrating all components.

Coordinates request routing, health checking, circuit breaking, rate limiting,
and metrics collection.
"""

import threading
import time

from thomas.load_balancer._exceptions import (
    CircuitOpenError,
    LoadBalancerError,
    NoHealthyBackendError,
)
from thomas.load_balancer._types import (
    Backend,
    BackendPool,
    LoadBalancerConfig,
    RequestContext,
    RoutingDecision,
)
from thomas.load_balancer.algorithms import LoadBalancingAlgorithm, RoundRobin
from thomas.load_balancer.circuit_breaker import CircuitBreakerManager
from thomas.load_balancer.connection_pool import ConnectionPoolManager
from thomas.load_balancer.health_check import HealthChecker
from thomas.load_balancer.metrics import MetricsCollector
from thomas.load_balancer.rate_limiter import RateLimiter
from thomas.load_balancer.sticky_sessions import SessionManager


class LoadBalancer:
    """
    Main load balancer coordinating all components.

    Handles request routing with algorithm selection, health checking,
    circuit breaking, rate limiting, and connection pooling.
    """

    def __init__(self, config: LoadBalancerConfig) -> None:
        """
        Initialize the load balancer.

        Args:
            config: LoadBalancerConfig with desired settings.
        """
        self.config = config
        self.pool = BackendPool()

        # Initialize components based on config
        self._algorithm = self._create_algorithm(config.algorithm)
        self._health_checker = HealthChecker(config.health_check)
        self._circuit_breaker = CircuitBreakerManager()
        self._session_manager = SessionManager() if config.enable_sticky_sessions else None
        self._rate_limiter = RateLimiter() if config.enable_rate_limiter else None
        self._connection_pool = ConnectionPoolManager() if config.enable_connection_pool else None
        self._metrics = MetricsCollector()

        self._draining_backends: set = set()
        self._lock = threading.Lock()
        self._running = False

    def start(self) -> None:
        """Start the load balancer."""
        if self._running:
            return

        self._running = True
        self._health_checker.start(list(self.pool))

        if self._session_manager:
            self._session_manager.start()

    def stop(self) -> None:
        """Stop the load balancer."""
        self._running = False
        self._health_checker.stop()

        if self._connection_pool:
            self._connection_pool.shutdown()

        if self._session_manager:
            self._session_manager.stop()

    def add_backend(self, backend: Backend) -> None:
        """
        Add a backend to the pool.

        Args:
            backend: Backend to add.

        Raises:
            ValueError: If backend already exists.
        """
        self.pool.add(backend)
        self._health_checker.add_backend(backend)
        self._metrics.get_backend_metrics(backend.id)  # Ensure metrics exist

    def remove_backend(self, backend_id: str) -> None:
        """
        Remove a backend from the pool.

        Args:
            backend_id: ID of backend to remove.
        """
        backend = self.pool.remove(backend_id)
        if backend:
            self._health_checker.remove_backend(backend_id)
            self._circuit_breaker.get_breaker(backend_id).reset()
            if self._connection_pool:
                self._connection_pool.remove_backend(backend_id)
            if self._session_manager:
                # Migrate sessions to other backends
                other_backends = [b for b in self.pool if b.id != backend_id]
                if other_backends:
                    self._session_manager.migrate_sessions(backend_id, other_backends[0].id)

    def drain_backend(self, backend_id: str) -> None:
        """
        Begin graceful drain of a backend.

        No new requests routed to this backend, but existing connections complete.

        Args:
            backend_id: ID of backend to drain.
        """
        with self._lock:
            self._draining_backends.add(backend_id)

        if self._connection_pool:
            self._connection_pool.drain_backend(backend_id)

    def route_request(
        self,
        context: RequestContext,
        client_limit: int | None = None,
        backend_limit: int | None = None,
    ) -> RoutingDecision:
        """
        Route a request to a backend.

        Applies algorithm selection, health checking, circuit breaking,
        rate limiting, and sticky sessions.

        Args:
            context: Request context.
            client_limit: Per-client rate limit (requests per minute).
            backend_limit: Per-backend rate limit (requests per minute).

        Returns:
            RoutingDecision with selected backend and metadata.

        Raises:
            NoHealthyBackendError: If no suitable backend found.
            CircuitOpenError: If selected backend's circuit is open.
            LoadBalancerError: If rate limit exceeded or other issues.
        """
        # Check rate limiting
        if self._rate_limiter:
            allowed, headers = self._rate_limiter.is_allowed(
                context,
                client_limit=client_limit,
                backend_limit=backend_limit,
            )
            if not allowed:
                raise LoadBalancerError(f"Rate limit exceeded for {context.client_ip}")

        # Get healthy backends
        healthy_backends = self._health_checker.get_healthy_backends(list(self.pool))

        # Filter out draining backends
        with self._lock:
            available_backends = [b for b in healthy_backends if b.id not in self._draining_backends]

        if not available_backends:
            raise NoHealthyBackendError("No healthy non-draining backends available")

        # Try sticky session first
        selected = None
        if self._session_manager:
            session_id = self._session_manager.extract_session_id(context)
            if session_id:
                selected = self._session_manager.get_backend_for_session(
                    session_id,
                    available_backends,
                )

        # Use algorithm if sticky session didn't work
        if not selected:
            # Get metrics for algorithm
            active_connections = {}
            latencies = {}

            if self._connection_pool:
                stats = self._connection_pool.get_all_stats()
                for bid, stat in stats.items():
                    active_connections[bid] = stat["active_connections"]

            # Get per-backend latencies from metrics
            all_metrics = self._metrics.get_all_backend_metrics()
            for bid, metric in all_metrics.items():
                latencies[bid] = metric.get("latency_mean", 0)

            decision = self._algorithm.select(
                available_backends,
                context,
                healthy_backends=available_backends,
                active_connections=active_connections,
                latencies=latencies,
            )
            selected = decision.backend

        # Check circuit breaker
        if not self._circuit_breaker.can_execute(selected.id):
            reset_time = self._circuit_breaker.get_breaker(selected.id).get_reset_time()
            raise CircuitOpenError(selected.id, reset_time)

        return RoutingDecision(backend=selected, algorithm_name=self._algorithm.__class__.__name__)

    def record_request(
        self,
        decision: RoutingDecision,
        latency: float,
        success: bool,
    ) -> None:
        """
        Record request metrics and circuit breaker updates.

        Args:
            decision: RoutingDecision from route_request.
            latency: Request latency in milliseconds.
            success: Whether request succeeded.
        """
        backend_id = decision.backend.id

        # Update metrics
        self._metrics.record_request(backend_id, latency, success)

        # Update circuit breaker
        if success:
            self._circuit_breaker.record_success(backend_id)
        else:
            self._circuit_breaker.record_failure(backend_id)
            # Passive health detection
            self._health_checker.mark_unhealthy(backend_id)

        # Update circuit state in metrics
        state = self._circuit_breaker.get_state(backend_id)
        self._metrics.set_circuit_state(backend_id, state)

    def retry_request(
        self,
        context: RequestContext,
        excluded_backends: list[str],
        client_limit: int | None = None,
        backend_limit: int | None = None,
    ) -> RoutingDecision:
        """
        Retry routing a request to a different backend.

        Args:
            context: Request context.
            excluded_backends: List of backend IDs to skip.
            client_limit: Per-client rate limit.
            backend_limit: Per-backend rate limit.

        Returns:
            New RoutingDecision with different backend.

        Raises:
            NoHealthyBackendError: If no alternative backend available.
        """
        # Filter out excluded backends for retry
        available = [
            b for b in list(self.pool) if b.id not in excluded_backends and b.id not in self._draining_backends
        ]

        healthy = self._health_checker.get_healthy_backends(available)

        if not healthy:
            raise NoHealthyBackendError(f"No healthy backends available for retry (excluded: {excluded_backends})")

        # Check circuit breaker for retry candidates
        can_execute = [b for b in healthy if self._circuit_breaker.can_execute(b.id)]

        if not can_execute:
            raise CircuitOpenError(
                can_execute[0].id if can_execute else "unknown",
                time.time(),
            )

        decision = self._algorithm.select(can_execute, context)
        return decision

    def get_health_status(self) -> dict:
        """
        Get health status of all backends.

        Returns:
            Dict mapping backend ID to health info.
        """
        return self._health_checker.get_health_summary()

    def get_metrics(self) -> dict:
        """
        Get all metrics.

        Returns:
            Dict with comprehensive metrics.
        """
        return self._metrics.export_metrics()

    def get_circuit_breaker_status(self) -> dict:
        """
        Get circuit breaker status for all backends.

        Returns:
            Dict mapping backend ID to circuit breaker metrics.
        """
        return self._circuit_breaker.get_all_metrics()

    def _create_algorithm(self, algorithm_name: str) -> LoadBalancingAlgorithm:
        """
        Create algorithm instance by name.

        Args:
            algorithm_name: Name of the algorithm.

        Returns:
            LoadBalancingAlgorithm instance.

        Raises:
            ValueError: If algorithm not found.
        """
        # Import here to avoid circular imports
        from thomas.load_balancer.algorithms import (
            ConsistentHash,
            IPHash,
            LeastConnections,
            LeastResponseTime,
            RandomChoice,
            ResourceBased,
            WeightedLeastConnections,
            WeightedRandom,
            WeightedRoundRobin,
        )

        algorithms = {
            "round_robin": RoundRobin,
            "weighted_round_robin": WeightedRoundRobin,
            "least_connections": LeastConnections,
            "weighted_least_connections": WeightedLeastConnections,
            "random": RandomChoice,
            "weighted_random": WeightedRandom,
            "ip_hash": IPHash,
            "consistent_hash": ConsistentHash,
            "least_response_time": LeastResponseTime,
            "resource_based": ResourceBased,
        }

        if algorithm_name not in algorithms:
            raise ValueError(f"Unknown algorithm: {algorithm_name}. " f"Available: {', '.join(algorithms.keys())}")

        return algorithms[algorithm_name]()

    def set_algorithm(self, algorithm_name: str) -> None:
        """
        Change the load balancing algorithm at runtime.

        Args:
            algorithm_name: Name of the algorithm.

        Raises:
            ValueError: If algorithm not found.
        """
        self._algorithm = self._create_algorithm(algorithm_name)
        self.config.algorithm = algorithm_name

    def get_stats(self) -> dict:
        """
        Get comprehensive statistics.

        Returns:
            Dict with all statistics.
        """
        return {
            "config": {
                "algorithm": self.config.algorithm,
                "enable_circuit_breaker": self.config.enable_circuit_breaker,
                "enable_rate_limiter": self.config.enable_rate_limiter,
                "enable_connection_pool": self.config.enable_connection_pool,
                "enable_sticky_sessions": self.config.enable_sticky_sessions,
            },
            "backends": {
                "total": len(self.pool),
                "draining": len(self._draining_backends),
            },
            "metrics": self.get_metrics(),
            "health": self.get_health_status(),
            "circuit_breakers": self.get_circuit_breaker_status(),
        }
