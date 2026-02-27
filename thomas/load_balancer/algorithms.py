"""
Load balancing algorithms.

Implements multiple load balancing strategies, each with different characteristics
suitable for various use cases.
"""

import hashlib
import random
import threading
from abc import ABC, abstractmethod

from thomas.load_balancer._exceptions import NoHealthyBackendError
from thomas.load_balancer._types import Backend, RequestContext, RoutingDecision


class LoadBalancingAlgorithm(ABC):
    """Base class for all load balancing algorithms."""

    @abstractmethod
    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """
        Select a backend for the given request.

        Args:
            backends: All available backends.
            context: Request context information.
            healthy_backends: List of healthy backends (subset of backends).
            active_connections: Dict mapping backend ID to active connection count.
            latencies: Dict mapping backend ID to measured latency in ms.

        Returns:
            RoutingDecision with selected backend and metadata.

        Raises:
            NoHealthyBackendError: If no suitable backend can be selected.
        """
        pass


class RoundRobin(LoadBalancingAlgorithm):
    """
    Round-robin load balancing.

    Distributes requests evenly across all backends in a circular manner.
    Uses atomic counter to ensure thread-safe operation.
    """

    def __init__(self) -> None:
        """Initialize the round-robin counter."""
        self._counter = 0
        self._lock = threading.Lock()

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using round-robin."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for round-robin selection")

        with self._lock:
            self._counter = (self._counter + 1) % len(candidates)
            selected = candidates[self._counter]

        return RoutingDecision(backend=selected, algorithm_name="RoundRobin")


class WeightedRoundRobin(LoadBalancingAlgorithm):
    """
    Weighted round-robin load balancing (Nginx-style).

    Distributes requests proportionally to backend weights using smooth
    weighted distribution to achieve better balance.
    """

    def __init__(self) -> None:
        """Initialize weighted counters."""
        self._current_weights: dict[str, int] = {}
        self._total_weight = 0
        self._lock = threading.Lock()

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using weighted round-robin."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for weighted round-robin selection")

        with self._lock:
            # Initialize weights if needed
            if not self._current_weights:
                for b in candidates:
                    self._current_weights[b.id] = 0
                self._total_weight = sum(b.weight for b in candidates)

            # Increase current weight for each backend
            for backend in candidates:
                self._current_weights[backend.id] += backend.weight

            # Select backend with highest current weight
            selected = max(candidates, key=lambda b: self._current_weights[b.id])

            # Decrease selected backend's weight
            self._current_weights[selected.id] -= self._total_weight

        return RoutingDecision(backend=selected, algorithm_name="WeightedRoundRobin")


class LeastConnections(LoadBalancingAlgorithm):
    """
    Least connections load balancing.

    Routes requests to the backend with the fewest active connections.
    Useful for long-lived connections.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend with least active connections."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for least connections selection")

        if not active_connections:
            active_connections = {}

        # Find backend with minimum active connections
        selected = min(candidates, key=lambda b: active_connections.get(b.id, 0))

        return RoutingDecision(backend=selected, algorithm_name="LeastConnections")


class WeightedLeastConnections(LoadBalancingAlgorithm):
    """
    Weighted least connections load balancing.

    Routes to the backend with the best ratio of available capacity
    (considering weights) to active connections.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using weighted least connections."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for weighted least connections selection")

        if not active_connections:
            active_connections = {}

        # Calculate capacity ratio for each backend
        def capacity_ratio(backend: Backend) -> float:
            """Lower ratio means better capacity."""
            active = active_connections.get(backend.id, 0)
            # Avoid division by zero with weight of 0
            weight = backend.weight if backend.weight > 0 else 1
            return active / weight

        selected = min(candidates, key=capacity_ratio)

        return RoutingDecision(backend=selected, algorithm_name="WeightedLeastConnections")


class RandomChoice(LoadBalancingAlgorithm):
    """
    Random selection load balancing.

    Selects a backend uniformly at random from available healthy backends.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend randomly."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for random selection")

        selected = random.choice(candidates)

        return RoutingDecision(backend=selected, algorithm_name="RandomChoice")


class WeightedRandom(LoadBalancingAlgorithm):
    """
    Weighted random selection.

    Selects a backend randomly with probability proportional to its weight.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using weighted random."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for weighted random selection")

        # Filter out backends with weight 0
        weighted_candidates = [b for b in candidates if b.weight > 0]

        if not weighted_candidates:
            raise NoHealthyBackendError("No healthy backends with positive weight for weighted random selection")

        # Use weighted random choice
        total_weight = sum(b.weight for b in weighted_candidates)
        choice_val = random.uniform(0, total_weight)

        cumulative = 0
        for backend in weighted_candidates:
            cumulative += backend.weight
            if choice_val <= cumulative:
                return RoutingDecision(backend=backend, algorithm_name="WeightedRandom")

        # Fallback (shouldn't reach here)
        return RoutingDecision(backend=weighted_candidates[-1], algorithm_name="WeightedRandom")


class IPHash(LoadBalancingAlgorithm):
    """
    IP hash load balancing.

    Routes requests from the same client IP to the same backend,
    providing session affinity without cookies.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using IP hash."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for IP hash selection")

        # Hash the client IP
        hash_val = int(hashlib.md5(context.client_ip.encode()).hexdigest(), 16)
        selected = candidates[hash_val % len(candidates)]

        return RoutingDecision(backend=selected, algorithm_name="IPHash")


class ConsistentHash(LoadBalancingAlgorithm):
    """
    Consistent hashing with virtual nodes.

    Implements ketama-style consistent hashing to minimize redistribution
    when backends are added/removed.
    """

    def __init__(self, virtual_nodes: int = 160) -> None:
        """
        Initialize consistent hash ring.

        Args:
            virtual_nodes: Number of virtual nodes per backend (default 160, Ketama style).
        """
        self.virtual_nodes = virtual_nodes
        self._ring: dict[int, Backend] = {}
        self._ring_sorted: list[int] = []
        self._lock = threading.Lock()
        self._backend_ids: set = set()

    def _build_ring(self, backends: list[Backend]) -> None:
        """Rebuild the hash ring for given backends."""
        self._ring = {}
        current_ids = {b.id for b in backends}

        # Only rebuild if backends changed
        if current_ids == self._backend_ids:
            return

        for backend in backends:
            for i in range(self.virtual_nodes):
                # Ketama-style hashing: use backend:virtual_node as key
                key = f"{backend.id}:{i}".encode()
                hash_val = int(hashlib.md5(key).hexdigest(), 16)
                self._ring[hash_val] = backend

        self._ring_sorted = sorted(self._ring.keys())
        self._backend_ids = current_ids

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend using consistent hashing."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for consistent hash selection")

        with self._lock:
            self._build_ring(candidates)

            # Hash the request context
            hash_key = f"{context.client_ip}:{context.path}".encode()
            hash_val = int(hashlib.md5(hash_key).hexdigest(), 16)

            # Find first node in ring >= hash value
            if not self._ring_sorted:
                selected = candidates[0]
            else:
                pos = 0
                for i, ring_val in enumerate(self._ring_sorted):
                    if ring_val >= hash_val:
                        pos = i
                        break
                else:
                    # Wrap around to first node
                    pos = 0

                selected = self._ring[self._ring_sorted[pos]]

        return RoutingDecision(backend=selected, algorithm_name="ConsistentHash")


class LeastResponseTime(LoadBalancingAlgorithm):
    """
    Least response time load balancing.

    Routes to the backend with the lowest estimated latency,
    weighted by backend weights.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend with least response time."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for least response time selection")

        if not latencies:
            latencies = {}

        def score(backend: Backend) -> float:
            """Lower score is better."""
            latency = latencies.get(backend.id, 0)
            weight = backend.weight if backend.weight > 0 else 1
            # Combine latency and weight: prefer low latency, consider weight
            return latency / weight if weight > 0 else float("inf")

        selected = min(candidates, key=score)
        estimated_latency = latencies.get(selected.id, 0)

        return RoutingDecision(
            backend=selected,
            latency_estimate=estimated_latency,
            algorithm_name="LeastResponseTime",
        )


class ResourceBased(LoadBalancingAlgorithm):
    """
    Resource-based load balancing.

    Routes to the backend with most available resources (CPU, memory).
    Metadata should contain 'cpu_available' and 'memory_available' percentages.
    """

    def select(
        self,
        backends: list[Backend],
        context: RequestContext,
        healthy_backends: list[Backend] | None = None,
        active_connections: dict[str, int] | None = None,
        latencies: dict[str, float] | None = None,
    ) -> RoutingDecision:
        """Select backend based on available resources."""
        candidates = healthy_backends if healthy_backends else backends

        if not candidates:
            raise NoHealthyBackendError("No healthy backends for resource-based selection")

        def resource_score(backend: Backend) -> float:
            """Higher score means more available resources."""
            cpu = backend.metadata.get("cpu_available", 0)
            memory = backend.metadata.get("memory_available", 0)
            # Combine metrics (could use more sophisticated weighting)
            return (cpu + memory) / 2.0

        selected = max(candidates, key=resource_score)

        return RoutingDecision(backend=selected, algorithm_name="ResourceBased")
