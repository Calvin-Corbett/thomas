"""Retry logic and circuit breaker for webhook delivery."""

import random
from datetime import datetime, timedelta

from thomas.webhooks._types import Delivery, DeliveryStatus, RetryPolicy


class RetryCalculator:
    """Calculates retry delays using various strategies.

    Supports:
    - Fixed delays
    - Exponential backoff
    - Fibonacci progression
    - Jitter to prevent thundering herd
    """

    @staticmethod
    def calculate_delay(
        policy: RetryPolicy,
        attempt_number: int,
    ) -> int:
        """Calculate delay in seconds for a retry attempt.

        Args:
            policy: The retry policy configuration.
            attempt_number: The attempt number (1-based).

        Returns:
            Delay in seconds.

        Raises:
            ValueError: If attempt number is invalid.
        """
        if attempt_number < 1:
            raise ValueError("Attempt number must be >= 1")

        if policy.strategy == "fixed":
            delay = policy.base_delay_seconds
        elif policy.strategy == "exponential":
            delay = RetryCalculator._exponential_delay(
                attempt_number,
                policy.base_delay_seconds,
                policy.multiplier,
            )
        elif policy.strategy == "fibonacci":
            delay = RetryCalculator._fibonacci_delay(
                attempt_number,
                policy.base_delay_seconds,
            )
        else:
            raise ValueError(f"Unknown retry strategy: {policy.strategy}")

        delay = min(delay, policy.max_delay_seconds)

        if policy.jitter:
            jitter_factor = random.uniform(0.8, 1.2)
            delay = int(delay * jitter_factor)

        return max(1, delay)

    @staticmethod
    def _exponential_delay(
        attempt_number: int,
        base_delay: int,
        multiplier: float,
    ) -> int:
        """Calculate exponential backoff delay.

        Formula: base * (multiplier ^ (attempt - 1))

        Args:
            attempt_number: The attempt number (1-based).
            base_delay: Base delay in seconds.
            multiplier: Exponential multiplier.

        Returns:
            Delay in seconds.
        """
        return int(base_delay * (multiplier ** (attempt_number - 1)))

    @staticmethod
    def _fibonacci_delay(
        attempt_number: int,
        base_delay: int,
    ) -> int:
        """Calculate Fibonacci-based delay.

        Formula: base * fibonacci(attempt)

        Args:
            attempt_number: The attempt number (1-based).
            base_delay: Base delay in seconds.

        Returns:
            Delay in seconds.
        """
        fib_val = RetryCalculator._fibonacci(attempt_number)
        return base_delay * fib_val

    @staticmethod
    def _fibonacci(n: int) -> int:
        """Get nth Fibonacci number.

        Args:
            n: Position in sequence (1-based).

        Returns:
            The nth Fibonacci number.
        """
        if n <= 1:
            return 1
        if n == 2:
            return 1
        a, b = 1, 1
        for _ in range(n - 2):
            a, b = b, a + b
        return b


class RetryScheduler:
    """Schedules retries for failed deliveries."""

    def __init__(self, policy: RetryPolicy) -> None:
        """Initialize the retry scheduler.

        Args:
            policy: The retry policy configuration.
        """
        self.policy = policy

    def should_retry(self, delivery: Delivery) -> bool:
        """Determine if a delivery should be retried.

        Args:
            delivery: The delivery record.

        Returns:
            True if delivery should be retried, False otherwise.
        """
        if delivery.status in (DeliveryStatus.DELIVERED, DeliveryStatus.EXHAUSTED):
            return False

        if len(delivery.attempts) >= self.policy.max_attempts:
            return False

        if not delivery.attempts:
            return True

        last_attempt = delivery.attempts[-1]
        if last_attempt.status_code:
            if 400 <= last_attempt.status_code < 500:
                return False

        return True

    def schedule_next_retry(self, delivery: Delivery) -> datetime | None:
        """Calculate when the next retry should occur.

        Args:
            delivery: The delivery record.

        Returns:
            Datetime of next retry, or None if no more retries.
        """
        if not self.should_retry(delivery):
            return None

        attempt_number = len(delivery.attempts) + 1
        delay_seconds = RetryCalculator.calculate_delay(
            self.policy,
            attempt_number,
        )

        return datetime.utcnow() + timedelta(seconds=delay_seconds)


class CircuitBreaker:
    """Per-endpoint circuit breaker for failure handling.

    States:
    - CLOSED: Normal operation
    - OPEN: Rejecting requests (after N consecutive failures)
    - HALF_OPEN: Testing if service recovered
    """

    class State:
        """Circuit breaker states."""

        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: int = 60,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit.
            success_threshold: Successes in half-open to close circuit.
            timeout_seconds: Timeout before attempting recovery.
        """
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds

        self.state = self.State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: datetime | None = None
        self.opened_at: datetime | None = None

    def record_success(self) -> None:
        """Record a successful request."""
        self.failure_count = 0

        if self.state == self.State.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.close()

    def record_failure(self) -> None:
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()

        if self.state == self.State.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self.open()
        elif self.state == self.State.HALF_OPEN:
            self.open()

    def is_available(self) -> bool:
        """Check if requests can be sent.

        Returns:
            True if circuit is closed or half-open, False if open.
        """
        if self.state == self.State.CLOSED:
            return True

        if self.state == self.State.OPEN:
            if self.opened_at is None:
                return False

            elapsed = (datetime.utcnow() - self.opened_at).total_seconds()
            if elapsed >= self.timeout_seconds:
                self.half_open()
                return True

            return False

        return self.state == self.State.HALF_OPEN

    def open(self) -> None:
        """Open the circuit (reject requests)."""
        self.state = self.State.OPEN
        self.opened_at = datetime.utcnow()
        self.success_count = 0

    def half_open(self) -> None:
        """Move to half-open state (test recovery)."""
        self.state = self.State.HALF_OPEN
        self.success_count = 0
        self.failure_count = 0

    def close(self) -> None:
        """Close the circuit (resume normal operation)."""
        self.state = self.State.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at = None

    def get_status(self) -> dict:
        """Get circuit breaker status.

        Returns:
            Dictionary with current state and metrics.
        """
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
        }


class DeadLetterQueue:
    """Dead letter queue for failed deliveries.

    Stores deliveries that exceeded max retries.
    """

    def __init__(self) -> None:
        """Initialize the dead letter queue."""
        self._queue: list[tuple[Delivery, str]] = []

    def enqueue(self, delivery: Delivery, reason: str) -> None:
        """Add a delivery to the dead letter queue.

        Args:
            delivery: The delivery that failed.
            reason: Reason for failure.
        """
        self._queue.append((delivery, reason))
        delivery.status = DeliveryStatus.EXHAUSTED
        delivery.permanent_failure_reason = reason

    def get_all(self) -> list[tuple[Delivery, str]]:
        """Get all dead lettered deliveries.

        Returns:
            List of (delivery, reason) tuples.
        """
        return list(self._queue)

    def get_by_endpoint(self, endpoint_id: str) -> list[tuple[Delivery, str]]:
        """Get dead lettered deliveries for a specific endpoint.

        Args:
            endpoint_id: The endpoint ID to filter by.

        Returns:
            List of (delivery, reason) tuples.
        """
        return [
            (d, r)
            for d, r in self._queue
            if d.subscription_id  # Filter would need subscription info
        ]

    def size(self) -> int:
        """Get the number of dead lettered deliveries.

        Returns:
            Number of entries in the queue.
        """
        return len(self._queue)

    def clear(self) -> None:
        """Clear the dead letter queue."""
        self._queue.clear()

    def retry(self, delivery: Delivery) -> bool:
        """Move a delivery back to the main queue for retry.

        Args:
            delivery: The delivery to retry.

        Returns:
            True if successfully removed from DLQ, False otherwise.
        """
        for i, (d, _) in enumerate(self._queue):
            if d.id == delivery.id:
                self._queue.pop(i)
                delivery.status = DeliveryStatus.RETRYING
                return True

        return False


class RetryBudget:
    """Retry budget limiting retries per time window.

    Prevents excessive retries during outages.
    """

    def __init__(
        self,
        max_retries: int = 1000,
        window_seconds: int = 60,
    ) -> None:
        """Initialize the retry budget.

        Args:
            max_retries: Maximum retries per window.
            window_seconds: Time window in seconds.
        """
        self.max_retries = max_retries
        self.window_seconds = window_seconds
        self._retry_times: list[datetime] = []

    def can_retry(self) -> bool:
        """Check if we can perform another retry.

        Returns:
            True if retry budget available, False otherwise.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.window_seconds)

        self._retry_times = [t for t in self._retry_times if t > cutoff]

        return len(self._retry_times) < self.max_retries

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self._retry_times.append(datetime.utcnow())

    def get_available(self) -> int:
        """Get number of retries still available.

        Returns:
            Number of available retries.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.window_seconds)
        self._retry_times = [t for t in self._retry_times if t > cutoff]

        return max(0, self.max_retries - len(self._retry_times))

    def get_status(self) -> dict:
        """Get retry budget status.

        Returns:
            Dictionary with budget information.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.window_seconds)
        recent = [t for t in self._retry_times if t > cutoff]

        return {
            "used": len(recent),
            "available": max(0, self.max_retries - len(recent)),
            "max": self.max_retries,
            "window_seconds": self.window_seconds,
        }
