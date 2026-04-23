"""
Retry policy management and circuit breaker implementation.

Implements retry strategies including:
- Exponential backoff
- Linear backoff
- Fibonacci backoff
- Jitter for distributed systems
- Circuit breaker pattern
- Retry-after header support
"""

import threading
from collections import defaultdict
from datetime import datetime
from enum import Enum

from thomas.marketplace.task_queue._types import Task


class CircuitState(Enum):
    """States for circuit breaker pattern."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker for preventing cascading failures.

    Stops sending requests to a failing task type after too many failures,
    allowing the system to recover.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exceptions: list[type[Exception]] | None = None,
    ) -> None:
        """
        Initialize a CircuitBreaker.

        Args:
            failure_threshold: Number of failures before opening circuit.
            recovery_timeout: Seconds to wait before attempting recovery.
            expected_exceptions: Exception types to count as failures.
        """
        self.failure_threshold: int = failure_threshold
        self.recovery_timeout: float = recovery_timeout
        self.expected_exceptions: tuple[type[Exception], ...] = tuple(expected_exceptions or [Exception])

        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.last_failure_time: datetime | None = None
        self._lock: threading.Lock = threading.Lock()

    def call(self, func, *args, **kwargs):
        """
        Execute a function through the circuit breaker.

        Args:
            func: Function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result if successful.

        Raises:
            CircuitBreakerOpenError: If circuit is open.
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                else:
                    raise CircuitBreakerOpenError(f"Circuit breaker is open. " f"Retry after {self.recovery_timeout}s")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if not self.last_failure_time:
            return False
        elapsed = (datetime.utcnow() - self.last_failure_time).total_seconds()
        return elapsed >= self.recovery_timeout

    def get_state(self) -> str:
        """Get current circuit state."""
        with self._lock:
            return self.state.value


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


class RetryManager:
    """
    Manages retry logic for failed tasks.

    Handles exponential/linear/fibonacci backoff, jitter, and
    circuit breaker patterns for task types.
    """

    def __init__(self) -> None:
        """Initialize RetryManager."""
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._task_failure_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"failures": 0, "successes": 0})
        self._lock: threading.RLock = threading.RLock()

    def register_circuit_breaker(
        self,
        task_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> CircuitBreaker:
        """
        Register a circuit breaker for a task type.

        Args:
            task_name: Name of the task type.
            failure_threshold: Failures before opening.
            recovery_timeout: Recovery timeout in seconds.

        Returns:
            The CircuitBreaker instance.
        """
        with self._lock:
            breaker = CircuitBreaker(
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
            )
            self._circuit_breakers[task_name] = breaker
            return breaker

    def should_retry(
        self,
        task: Task,
        error: Exception,
    ) -> bool:
        """
        Determine if a task should be retried.

        Args:
            task: The failed task.
            error: The exception that occurred.

        Returns:
            True if task should be retried.
        """
        policy = task.retry_policy

        # Check if error type is retryable
        if policy.retry_on and not isinstance(error, tuple(policy.retry_on)):
            return False

        # Check max retries
        if task.retries >= policy.max_retries:
            return False

        # Check circuit breaker
        breaker = self._circuit_breakers.get(task.name)
        if breaker and breaker.state == CircuitState.OPEN:
            return False

        return True

    def calculate_delay(self, task: Task) -> float:
        """
        Calculate delay before retry.

        Args:
            task: Task being retried.

        Returns:
            Delay in seconds.
        """
        policy = task.retry_policy
        retry_num = task.retries

        # Calculate base delay
        if policy.backoff_type == "exponential":
            delay = policy.initial_delay * (2**retry_num)
        elif policy.backoff_type == "linear":
            delay = policy.initial_delay * (retry_num + 1)
        elif policy.backoff_type == "fibonacci":
            delay = policy.initial_delay * self._fibonacci(retry_num)
        else:
            delay = policy.initial_delay

        # Cap at max delay
        delay = min(delay, policy.max_delay)

        # Add jitter
        if policy.jitter:
            import random

            jitter_amount = delay * (random.random() * 0.4 - 0.2)
            delay += jitter_amount
            delay = max(delay, 0)

        return delay

    def record_success(self, task_name: str) -> None:
        """
        Record a successful task execution.

        Args:
            task_name: Name of the task.
        """
        with self._lock:
            self._task_failure_stats[task_name]["successes"] += 1

    def record_failure(self, task_name: str) -> None:
        """
        Record a failed task execution.

        Args:
            task_name: Name of the task.
        """
        with self._lock:
            self._task_failure_stats[task_name]["failures"] += 1

    def get_failure_rate(self, task_name: str) -> float:
        """
        Get failure rate for a task type.

        Args:
            task_name: Name of the task.

        Returns:
            Failure rate as a percentage (0-100).
        """
        with self._lock:
            stats = self._task_failure_stats.get(task_name, {})
            total = stats.get("failures", 0) + stats.get("successes", 0)
            if total == 0:
                return 0.0
            return (stats.get("failures", 0) / total) * 100

    def get_circuit_breaker_state(self, task_name: str) -> str | None:
        """
        Get circuit breaker state for a task.

        Args:
            task_name: Name of the task.

        Returns:
            Circuit state or None if no breaker registered.
        """
        breaker = self._circuit_breakers.get(task_name)
        return breaker.get_state() if breaker else None

    @staticmethod
    def _fibonacci(n: int) -> int:
        """Calculate nth Fibonacci number."""
        if n <= 1:
            return 1
        a, b = 1, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b

    def __repr__(self) -> str:
        return (
            f"RetryManager(circuit_breakers={len(self._circuit_breakers)}, "
            f"tracked_tasks={len(self._task_failure_stats)})"
        )
