"""
Circuit breaker implementation for backend fault tolerance.

Implements the circuit breaker pattern to prevent cascading failures
when backends become unhealthy.
"""

import threading
import time
from collections import deque

from thomas.load_balancer._types import CircuitState


class CircuitMetrics:
    """Metrics for a single circuit breaker."""

    def __init__(self) -> None:
        """Initialize circuit metrics."""
        self.total_requests: int = 0
        self.total_failures: int = 0
        self.total_successes: int = 0
        self.last_failure_time: float = 0
        self.last_success_time: float = 0
        self.state_changes: int = 0


class CircuitBreaker:
    """
    Circuit breaker per backend.

    Three states:
    - CLOSED: Normal operation, requests pass through.
    - OPEN: Failures detected, requests fail immediately.
    - HALF_OPEN: Testing if backend recovered.
    """

    def __init__(
        self,
        backend_id: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
        window_size: int = 10,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            backend_id: ID of the backend this circuit protects.
            failure_threshold: Number of failures to trip the circuit.
            recovery_timeout: Seconds before attempting recovery from OPEN state.
            success_threshold: Successful requests in HALF_OPEN to close circuit.
            window_size: Size of sliding window for failure tracking.
        """
        self.backend_id = backend_id
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.window_size = window_size

        self._state = CircuitState.CLOSED
        self._failure_window: deque[float] = deque(maxlen=window_size)
        self._open_time: float = 0
        self._half_open_successes: int = 0
        self._metrics = CircuitMetrics()
        self._lock = threading.Lock()

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self._metrics.total_requests += 1
            self._metrics.total_successes += 1
            self._metrics.last_success_time = time.time()

            if self._state == CircuitState.CLOSED:
                # Clear failures on success
                self._failure_window.clear()

            elif self._state == CircuitState.HALF_OPEN:
                # Track successes during recovery
                self._half_open_successes += 1
                if self._half_open_successes >= self.success_threshold:
                    self._transition_to_closed()

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            self._metrics.total_requests += 1
            self._metrics.total_failures += 1
            self._metrics.last_failure_time = time.time()

            if self._state == CircuitState.CLOSED:
                # Add failure to sliding window
                self._failure_window.append(time.time())

                # Check if we should trip the circuit
                if len(self._failure_window) >= self.failure_threshold:
                    self._transition_to_open()

            elif self._state == CircuitState.HALF_OPEN:
                # Any failure during recovery opens circuit
                self._transition_to_open()

    def can_execute(self) -> bool:
        """
        Check if a request can be executed.

        Returns:
            True if request should be allowed, False if circuit is OPEN.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                elapsed = time.time() - self._open_time
                if elapsed >= self.recovery_timeout:
                    self._transition_to_half_open()
                    return True
                return False

            # HALF_OPEN state
            return True

    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    def get_reset_time(self) -> float:
        """
        Get when the circuit will attempt recovery.

        Returns:
            Unix timestamp when circuit will move from OPEN to HALF_OPEN.
        """
        if self._state == CircuitState.OPEN:
            return self._open_time + self.recovery_timeout
        return time.time()

    def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state."""
        old_state = self._state
        self._state = CircuitState.OPEN
        self._open_time = time.time()
        self._metrics.state_changes += 1
        self._half_open_successes = 0

    def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state."""
        old_state = self._state
        self._state = CircuitState.HALF_OPEN
        self._metrics.state_changes += 1
        self._half_open_successes = 0

    def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state."""
        old_state = self._state
        self._state = CircuitState.CLOSED
        self._metrics.state_changes += 1
        self._failure_window.clear()
        self._half_open_successes = 0

    def get_metrics(self) -> dict:
        """
        Get circuit metrics.

        Returns:
            Dict with metrics for this circuit.
        """
        with self._lock:
            return {
                "backend_id": self.backend_id,
                "state": self._state.value,
                "total_requests": self._metrics.total_requests,
                "total_failures": self._metrics.total_failures,
                "total_successes": self._metrics.total_successes,
                "failure_rate": (
                    (self._metrics.total_failures / self._metrics.total_requests)
                    if self._metrics.total_requests > 0
                    else 0
                ),
                "last_failure_time": self._metrics.last_failure_time,
                "last_success_time": self._metrics.last_success_time,
                "state_changes": self._metrics.state_changes,
                "recent_failures": len(self._failure_window),
            }

    def reset(self) -> None:
        """Reset circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_window.clear()
            self._half_open_successes = 0
            self._metrics = CircuitMetrics()


class CircuitBreakerManager:
    """Manages circuit breakers for all backends."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ) -> None:
        """
        Initialize circuit breaker manager.

        Args:
            failure_threshold: Default failure threshold for new circuits.
            recovery_timeout: Default recovery timeout for new circuits.
            success_threshold: Default success threshold for new circuits.
        """
        self._breakers: dict[str, CircuitBreaker] = {}
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self._lock = threading.Lock()

    def get_breaker(self, backend_id: str) -> CircuitBreaker:
        """
        Get or create circuit breaker for a backend.

        Args:
            backend_id: ID of the backend.

        Returns:
            CircuitBreaker instance for this backend.
        """
        with self._lock:
            if backend_id not in self._breakers:
                self._breakers[backend_id] = CircuitBreaker(
                    backend_id,
                    failure_threshold=self.failure_threshold,
                    recovery_timeout=self.recovery_timeout,
                    success_threshold=self.success_threshold,
                )
            return self._breakers[backend_id]

    def record_success(self, backend_id: str) -> None:
        """
        Record a successful request to a backend.

        Args:
            backend_id: ID of the backend.
        """
        breaker = self.get_breaker(backend_id)
        breaker.record_success()

    def record_failure(self, backend_id: str) -> None:
        """
        Record a failed request to a backend.

        Args:
            backend_id: ID of the backend.
        """
        breaker = self.get_breaker(backend_id)
        breaker.record_failure()

    def can_execute(self, backend_id: str) -> bool:
        """
        Check if a request can be sent to a backend.

        Args:
            backend_id: ID of the backend.

        Returns:
            True if circuit allows execution, False if OPEN.
        """
        breaker = self.get_breaker(backend_id)
        return breaker.can_execute()

    def get_state(self, backend_id: str) -> CircuitState:
        """
        Get current state of a backend's circuit.

        Args:
            backend_id: ID of the backend.

        Returns:
            CircuitState of the backend's circuit.
        """
        breaker = self.get_breaker(backend_id)
        return breaker.get_state()

    def get_all_metrics(self) -> dict[str, dict]:
        """
        Get metrics for all circuits.

        Returns:
            Dict mapping backend ID to metrics.
        """
        with self._lock:
            return {bid: breaker.get_metrics() for bid, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()

    def remove_backend(self, backend_id: str) -> None:
        """
        Remove a backend's circuit breaker.

        Args:
            backend_id: ID of the backend.
        """
        with self._lock:
            self._breakers.pop(backend_id, None)
