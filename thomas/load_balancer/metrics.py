"""
Metrics collection and reporting.

Collects per-backend and global metrics including request counts, errors,
latencies (p50/p95/p99), and connection statistics.
"""

import threading
import time
from collections import deque

from thomas.load_balancer._types import CircuitState


class LatencyHistogram:
    """Tracks latency percentiles."""

    def __init__(self, max_samples: int = 1000) -> None:
        """
        Initialize latency histogram.

        Args:
            max_samples: Maximum samples to keep.
        """
        self.max_samples = max_samples
        self.samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def add(self, latency: float) -> None:
        """Add a latency sample."""
        with self._lock:
            self.samples.append(latency)

    def percentile(self, p: float) -> float:
        """
        Get latency percentile.

        Args:
            p: Percentile (0-100).

        Returns:
            Latency at percentile in milliseconds.
        """
        with self._lock:
            if not self.samples:
                return 0.0

            sorted_samples = sorted(self.samples)
            idx = int(len(sorted_samples) * (p / 100.0))
            return float(sorted_samples[min(idx, len(sorted_samples) - 1)])

    def mean(self) -> float:
        """Get mean latency."""
        with self._lock:
            if not self.samples:
                return 0.0
            return sum(self.samples) / len(self.samples)


class BackendMetrics:
    """Metrics for a single backend."""

    def __init__(self, backend_id: str) -> None:
        """
        Initialize backend metrics.

        Args:
            backend_id: ID of the backend.
        """
        self.backend_id = backend_id
        self.total_requests = 0
        self.total_errors = 0
        self.total_successes = 0
        self.active_connections = 0
        self.circuit_state = CircuitState.CLOSED

        self.latency_histogram = LatencyHistogram()
        self._lock = threading.Lock()

    def record_request(self, latency: float, success: bool) -> None:
        """
        Record a request.

        Args:
            latency: Request latency in milliseconds.
            success: Whether request succeeded.
        """
        with self._lock:
            self.total_requests += 1
            if success:
                self.total_successes += 1
            else:
                self.total_errors += 1

            self.latency_histogram.add(latency)

    def set_active_connections(self, count: int) -> None:
        """Set active connection count."""
        with self._lock:
            self.active_connections = count

    def set_circuit_state(self, state: CircuitState) -> None:
        """Set circuit breaker state."""
        with self._lock:
            self.circuit_state = state

    def get_metrics(self) -> dict:
        """
        Get metrics snapshot.

        Returns:
            Dict with metrics.
        """
        with self._lock:
            error_rate = (self.total_errors / self.total_requests) * 100 if self.total_requests > 0 else 0

            return {
                "backend_id": self.backend_id,
                "total_requests": self.total_requests,
                "total_errors": self.total_errors,
                "total_successes": self.total_successes,
                "error_rate": error_rate,
                "active_connections": self.active_connections,
                "circuit_state": self.circuit_state.value,
                "latency_p50": self.latency_histogram.percentile(50),
                "latency_p95": self.latency_histogram.percentile(95),
                "latency_p99": self.latency_histogram.percentile(99),
                "latency_mean": self.latency_histogram.mean(),
            }


class MetricsCollector:
    """Collects metrics from the load balancer."""

    def __init__(self, retention_seconds: int = 3600) -> None:
        """
        Initialize metrics collector.

        Args:
            retention_seconds: How long to retain metrics in memory.
        """
        self.retention_seconds = retention_seconds
        self._backend_metrics: dict[str, BackendMetrics] = {}
        self._global_metrics = {
            "total_requests": 0,
            "total_errors": 0,
            "requests_per_second": 0.0,
        }
        self._request_times: deque[float] = deque()
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def record_request(
        self,
        backend_id: str,
        latency: float,
        success: bool,
    ) -> None:
        """
        Record a request to a backend.

        Args:
            backend_id: ID of the backend.
            latency: Request latency in milliseconds.
            success: Whether request succeeded.
        """
        self._ensure_backend_metrics(backend_id)

        with self._lock:
            self._backend_metrics[backend_id].record_request(latency, success)
            self._global_metrics["total_requests"] += 1
            if not success:
                self._global_metrics["total_errors"] += 1

            now = time.time()
            self._request_times.append(now)

            # Periodic cleanup
            if now - self._last_cleanup > 60:
                self._cleanup_old_requests()
                self._last_cleanup = now

    def _cleanup_old_requests(self) -> None:
        """Remove old request timestamps."""
        cutoff = time.time() - self.retention_seconds
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    def set_active_connections(self, backend_id: str, count: int) -> None:
        """
        Set active connection count for a backend.

        Args:
            backend_id: ID of the backend.
            count: Number of active connections.
        """
        self._ensure_backend_metrics(backend_id)

        with self._lock:
            self._backend_metrics[backend_id].set_active_connections(count)

    def set_circuit_state(self, backend_id: str, state: CircuitState) -> None:
        """
        Set circuit breaker state for a backend.

        Args:
            backend_id: ID of the backend.
            state: CircuitState.
        """
        self._ensure_backend_metrics(backend_id)

        with self._lock:
            self._backend_metrics[backend_id].set_circuit_state(state)

    def _ensure_backend_metrics(self, backend_id: str) -> None:
        """Ensure metrics exist for a backend."""
        with self._lock:
            if backend_id not in self._backend_metrics:
                self._backend_metrics[backend_id] = BackendMetrics(backend_id)

    def get_backend_metrics(self, backend_id: str) -> dict | None:
        """
        Get metrics for a backend.

        Args:
            backend_id: ID of the backend.

        Returns:
            Dict with backend metrics, or None if not found.
        """
        with self._lock:
            if backend_id in self._backend_metrics:
                return self._backend_metrics[backend_id].get_metrics()
            return None

    def get_all_backend_metrics(self) -> dict[str, dict]:
        """
        Get metrics for all backends.

        Returns:
            Dict mapping backend ID to metrics.
        """
        with self._lock:
            return {bid: metrics.get_metrics() for bid, metrics in self._backend_metrics.items()}

    def get_global_metrics(self) -> dict:
        """
        Get global metrics.

        Returns:
            Dict with global metrics.
        """
        with self._lock:
            # Calculate requests per second
            now = time.time()
            cutoff = now - 60  # Last minute
            recent_requests = sum(1 for t in self._request_times if t > cutoff)
            rps = recent_requests / 60.0

            return {
                "total_requests": self._global_metrics["total_requests"],
                "total_errors": self._global_metrics["total_errors"],
                "error_rate": (
                    (self._global_metrics["total_errors"] / self._global_metrics["total_requests"]) * 100
                    if self._global_metrics["total_requests"] > 0
                    else 0
                ),
                "requests_per_second": rps,
                "active_backends": len(self._backend_metrics),
            }

    def get_backend_distribution(self) -> dict[str, float]:
        """
        Get request distribution across backends (percentages).

        Returns:
            Dict mapping backend ID to request percentage.
        """
        with self._lock:
            total = self._global_metrics["total_requests"]
            if total == 0:
                return {}

            return {bid: (metrics.total_requests / total) * 100 for bid, metrics in self._backend_metrics.items()}

    def reset_backend(self, backend_id: str) -> None:
        """
        Reset metrics for a backend.

        Args:
            backend_id: ID of the backend.
        """
        with self._lock:
            if backend_id in self._backend_metrics:
                self._backend_metrics[backend_id] = BackendMetrics(backend_id)

    def reset_all(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._backend_metrics.clear()
            self._global_metrics = {
                "total_requests": 0,
                "total_errors": 0,
            }
            self._request_times.clear()

    def export_metrics(self) -> dict:
        """
        Export all metrics for external consumption.

        Returns:
            Dict with complete metrics snapshot.
        """
        return {
            "timestamp": time.time(),
            "global": self.get_global_metrics(),
            "backends": self.get_all_backend_metrics(),
            "distribution": self.get_backend_distribution(),
        }
