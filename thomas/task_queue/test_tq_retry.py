"""
Tests for retry policies and circuit breaker implementation.

Tests exponential/linear/fibonacci backoff, jitter, and circuit breaker patterns.
"""

import time

import pytest

from thomas.task_queue._types import RetryPolicy, Task
from thomas.task_queue.retry import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    RetryManager,
)


def dummy_func():
    """Simple test function."""
    pass


class TestRetryPolicy:
    """Tests for RetryPolicy."""

    def test_default_retry_policy(self) -> None:
        """Test default retry policy."""
        policy = RetryPolicy()

        assert policy.max_retries == 3
        assert policy.backoff_type == "exponential"
        assert policy.initial_delay == 1.0

    def test_custom_retry_policy(self) -> None:
        """Test custom retry policy."""
        policy = RetryPolicy(
            max_retries=5,
            backoff_type="linear",
            initial_delay=0.5,
        )

        assert policy.max_retries == 5
        assert policy.backoff_type == "linear"
        assert policy.initial_delay == 0.5

    def test_retry_policy_validation(self) -> None:
        """Test retry policy validation."""
        with pytest.raises(ValueError):
            RetryPolicy(max_retries=-1)

        with pytest.raises(ValueError):
            RetryPolicy(initial_delay=-1)

        with pytest.raises(ValueError):
            RetryPolicy(max_delay=1, initial_delay=10)

        with pytest.raises(ValueError):
            RetryPolicy(backoff_type="invalid")

    def test_retry_on_specific_exceptions(self) -> None:
        """Test retry only on specific exceptions."""
        policy = RetryPolicy(retry_on=[ValueError, KeyError])

        assert ValueError in policy.retry_on
        assert KeyError in policy.retry_on


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""

    def test_circuit_breaker_initialization(self) -> None:
        """Test circuit breaker creation."""
        breaker = CircuitBreaker(failure_threshold=5)

        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_circuit_breaker_success(self) -> None:
        """Test successful call through breaker."""
        breaker = CircuitBreaker()

        def success_func():
            return 42

        result = breaker.call(success_func)
        assert result == 42
        assert breaker.failure_count == 0

    def test_circuit_breaker_failure(self) -> None:
        """Test failures increment counter."""
        breaker = CircuitBreaker(failure_threshold=3)

        def fail_func():
            raise ValueError("error")

        for i in range(3):
            with pytest.raises(ValueError):
                breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

    def test_circuit_breaker_opens_after_threshold(self) -> None:
        """Test circuit opens after failure threshold."""
        breaker = CircuitBreaker(failure_threshold=2)

        def fail_func():
            raise ValueError("error")

        # First two failures
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(fail_func)

        # Third call should be blocked
        assert breaker.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerOpenError):
            breaker.call(fail_func)

    def test_circuit_breaker_recovery(self) -> None:
        """Test circuit breaker recovery after timeout."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.5)

        def fail_func():
            raise ValueError("error")

        # Trigger failure
        with pytest.raises(ValueError):
            breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        time.sleep(0.6)

        # Should attempt recovery
        with pytest.raises(ValueError):
            breaker.call(fail_func)

        assert breaker.state == CircuitState.HALF_OPEN

    def test_circuit_breaker_resets_on_success(self) -> None:
        """Test circuit resets on successful call."""
        breaker = CircuitBreaker(failure_threshold=2)

        def fail_func():
            raise ValueError("error")

        # Cause failures
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Create success function
        def success_func():
            return 42

        # After reset attempt, call success
        breaker.failure_count = 0
        breaker.state = CircuitState.HALF_OPEN

        result = breaker.call(success_func)
        assert result == 42
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0


class TestRetryManager:
    """Tests for RetryManager."""

    def test_retry_manager_initialization(self) -> None:
        """Test retry manager creation."""
        manager = RetryManager()

        assert len(manager._circuit_breakers) == 0

    def test_register_circuit_breaker(self) -> None:
        """Test registering circuit breaker."""
        manager = RetryManager()

        breaker = manager.register_circuit_breaker("task_type")

        assert "task_type" in manager._circuit_breakers
        assert isinstance(breaker, CircuitBreaker)

    def test_should_retry(self) -> None:
        """Test retry decision logic."""
        manager = RetryManager()
        policy = RetryPolicy(max_retries=3)
        task = Task("test", dummy_func, retry_policy=policy)

        # Should retry while under limit
        assert manager.should_retry(task, ValueError("error"))

        # Should not retry after max retries
        task.retries = 3
        assert not manager.should_retry(task, ValueError("error"))

    def test_should_not_retry_specific_exception(self) -> None:
        """Test don't retry on non-retryable exceptions."""
        manager = RetryManager()
        policy = RetryPolicy(max_retries=3, retry_on=[ValueError])
        task = Task("test", dummy_func, retry_policy=policy)

        # Should retry ValueError
        assert manager.should_retry(task, ValueError("error"))

        # Should not retry KeyError
        assert not manager.should_retry(task, KeyError("error"))

    def test_circuit_breaker_prevents_retry(self) -> None:
        """Test circuit breaker prevents retries."""
        manager = RetryManager()
        manager.register_circuit_breaker("test_task", failure_threshold=1)

        policy = RetryPolicy(max_retries=3)
        task = Task("test_task", dummy_func, retry_policy=policy)

        # Open circuit
        breaker = manager._circuit_breakers["test_task"]
        breaker.failure_count = 1
        breaker.state = CircuitState.OPEN

        # Should not retry when circuit open
        assert not manager.should_retry(task, ValueError("error"))

    def test_calculate_exponential_delay(self) -> None:
        """Test exponential backoff delay calculation."""
        manager = RetryManager()
        policy = RetryPolicy(backoff_type="exponential", initial_delay=1.0)
        task = Task("test", dummy_func, retry_policy=policy)

        task.retries = 0
        delay0 = manager.calculate_delay(task)
        assert abs(delay0 - 1.0) < 0.5  # Allow for jitter

        task.retries = 1
        delay1 = manager.calculate_delay(task)
        assert delay1 > delay0

        task.retries = 2
        delay2 = manager.calculate_delay(task)
        assert delay2 > delay1

    def test_calculate_linear_delay(self) -> None:
        """Test linear backoff delay calculation."""
        manager = RetryManager()
        policy = RetryPolicy(backoff_type="linear", initial_delay=1.0, jitter=False)
        task = Task("test", dummy_func, retry_policy=policy)

        task.retries = 0
        delay0 = manager.calculate_delay(task)
        assert abs(delay0 - 1.0) < 0.01

        task.retries = 1
        delay1 = manager.calculate_delay(task)
        assert abs(delay1 - 2.0) < 0.01

        task.retries = 2
        delay2 = manager.calculate_delay(task)
        assert abs(delay2 - 3.0) < 0.01

    def test_calculate_fibonacci_delay(self) -> None:
        """Test fibonacci backoff delay calculation."""
        manager = RetryManager()
        policy = RetryPolicy(
            backoff_type="fibonacci",
            initial_delay=1.0,
            jitter=False,
        )
        task = Task("test", dummy_func, retry_policy=policy)

        delays = []
        for i in range(4):
            task.retries = i
            delays.append(manager.calculate_delay(task))

        # Fibonacci: 1, 1, 2, 3
        assert delays[0] < delays[1]
        assert delays[1] <= delays[2]
        assert delays[2] < delays[3]

    def test_max_delay_capped(self) -> None:
        """Test max delay cap."""
        manager = RetryManager()
        policy = RetryPolicy(
            backoff_type="exponential",
            initial_delay=1.0,
            max_delay=10.0,
            jitter=False,
        )
        task = Task("test", dummy_func, retry_policy=policy)

        task.retries = 10
        delay = manager.calculate_delay(task)
        assert delay <= 10.0

    def test_record_success_failure(self) -> None:
        """Test recording task success/failure."""
        manager = RetryManager()

        manager.record_success("task_type_a")
        manager.record_success("task_type_a")
        manager.record_failure("task_type_a")

        rate = manager.get_failure_rate("task_type_a")
        assert 0 < rate < 100  # Should be around 33%

    def test_failure_rate_calculation(self) -> None:
        """Test failure rate calculation."""
        manager = RetryManager()

        for _ in range(90):
            manager.record_success("task")
        for _ in range(10):
            manager.record_failure("task")

        rate = manager.get_failure_rate("task")
        assert abs(rate - 10.0) < 0.1
