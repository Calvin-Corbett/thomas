"""
Tests for circuit breaker implementation.

Verifies state transitions, failure tracking, and recovery patterns.
"""

import time

from thomas.load_balancer._types import CircuitState
from thomas.load_balancer.circuit_breaker import CircuitBreaker, CircuitBreakerManager


class TestCircuitBreaker:
    """Tests for single circuit breaker."""

    def test_initial_state(self):
        """Test circuit starts in CLOSED state."""
        breaker = CircuitBreaker("backend1")
        assert breaker.get_state() == CircuitState.CLOSED

    def test_can_execute_when_closed(self):
        """Test requests allowed in CLOSED state."""
        breaker = CircuitBreaker("backend1")
        assert breaker.can_execute() is True

    def test_transition_to_open(self):
        """Test transition from CLOSED to OPEN."""
        breaker = CircuitBreaker("backend1", failure_threshold=3)

        # Record failures
        for _ in range(3):
            breaker.record_failure()

        assert breaker.get_state() == CircuitState.OPEN
        assert not breaker.can_execute()

    def test_open_to_half_open_timeout(self):
        """Test transition from OPEN to HALF_OPEN after timeout."""
        breaker = CircuitBreaker("backend1", failure_threshold=2, recovery_timeout=1)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

        # Should not execute immediately
        assert not breaker.can_execute()

        # Wait for recovery timeout
        time.sleep(1.1)

        # Now should be HALF_OPEN
        assert breaker.can_execute()
        assert breaker.get_state() == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        """Test recovery from HALF_OPEN on successful request."""
        breaker = CircuitBreaker(
            "backend1",
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=2,
        )

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

        # Wait and enter HALF_OPEN
        time.sleep(1.1)
        breaker.can_execute()

        # Record successes
        breaker.record_success()
        assert breaker.get_state() == CircuitState.HALF_OPEN

        breaker.record_success()
        assert breaker.get_state() == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """Test failure in HALF_OPEN returns to OPEN."""
        breaker = CircuitBreaker(
            "backend1",
            failure_threshold=2,
            recovery_timeout=1,
        )

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()

        # Wait and enter HALF_OPEN
        time.sleep(1.1)
        breaker.can_execute()

        # Single failure should reopen
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

    def test_success_clears_failures(self):
        """Test successful requests clear failure window."""
        breaker = CircuitBreaker("backend1", failure_threshold=3)

        # Record some failures
        breaker.record_failure()
        breaker.record_failure()

        # Then success in CLOSED state should clear
        breaker.record_success()
        assert breaker.get_state() == CircuitState.CLOSED

        # More failures should require 3 again
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.CLOSED

        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

    def test_sliding_window_tracking(self):
        """Test sliding window failure tracking."""
        breaker = CircuitBreaker("backend1", failure_threshold=3, window_size=3)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.CLOSED

        # Add success, should stay closed
        breaker.record_success()
        assert breaker.get_state() == CircuitState.CLOSED

        # More failures
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

    def test_get_reset_time(self):
        """Test getting reset time."""
        breaker = CircuitBreaker("backend1", failure_threshold=1, recovery_timeout=5)

        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

        reset_time = breaker.get_reset_time()
        assert reset_time > time.time()
        assert reset_time <= time.time() + 6

    def test_get_metrics(self):
        """Test metrics collection."""
        breaker = CircuitBreaker("backend1")

        breaker.record_success()
        breaker.record_success()
        breaker.record_failure()

        metrics = breaker.get_metrics()
        assert metrics["backend_id"] == "backend1"
        assert metrics["total_requests"] == 3
        assert metrics["total_successes"] == 2
        assert metrics["total_failures"] == 1
        assert metrics["state"] == "closed"

    def test_reset(self):
        """Test resetting circuit breaker."""
        breaker = CircuitBreaker("backend1", failure_threshold=2)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

        breaker.reset()
        assert breaker.get_state() == CircuitState.CLOSED

    def test_metrics_increments(self):
        """Test state_changes counter."""
        breaker = CircuitBreaker("backend1", failure_threshold=1, recovery_timeout=1)

        initial_changes = breaker.get_metrics()["state_changes"]

        breaker.record_failure()  # OPEN
        changes_after_open = breaker.get_metrics()["state_changes"]
        assert changes_after_open > initial_changes

        time.sleep(1.1)
        breaker.can_execute()  # HALF_OPEN
        changes_after_half = breaker.get_metrics()["state_changes"]
        assert changes_after_half > changes_after_open


class TestCircuitBreakerManager:
    """Tests for circuit breaker manager."""

    def test_get_or_create_breaker(self):
        """Test creating breaker on demand."""
        manager = CircuitBreakerManager()

        breaker1 = manager.get_breaker("b1")
        breaker2 = manager.get_breaker("b1")

        assert breaker1 is breaker2

    def test_record_success(self):
        """Test recording success through manager."""
        manager = CircuitBreakerManager()

        manager.record_success("b1")
        breaker = manager.get_breaker("b1")
        metrics = breaker.get_metrics()
        assert metrics["total_successes"] == 1

    def test_record_failure(self):
        """Test recording failure through manager."""
        manager = CircuitBreakerManager()

        for _ in range(5):
            manager.record_failure("b1")

        breaker = manager.get_breaker("b1")
        assert breaker.get_state() == CircuitState.OPEN

    def test_can_execute(self):
        """Test checking execution permission."""
        manager = CircuitBreakerManager(failure_threshold=2)

        assert manager.can_execute("b1")

        manager.record_failure("b1")
        manager.record_failure("b1")

        assert not manager.can_execute("b1")

    def test_get_state(self):
        """Test getting state of backend."""
        manager = CircuitBreakerManager(failure_threshold=1)

        assert manager.get_state("b1") == CircuitState.CLOSED

        manager.record_failure("b1")
        assert manager.get_state("b1") == CircuitState.OPEN

    def test_get_all_metrics(self):
        """Test getting metrics for all backends."""
        manager = CircuitBreakerManager()

        manager.record_success("b1")
        manager.record_failure("b2")

        all_metrics = manager.get_all_metrics()
        assert "b1" in all_metrics
        assert "b2" in all_metrics

    def test_reset_all(self):
        """Test resetting all circuit breakers."""
        manager = CircuitBreakerManager(failure_threshold=1)

        manager.record_failure("b1")
        manager.record_failure("b2")

        assert manager.get_state("b1") == CircuitState.OPEN
        assert manager.get_state("b2") == CircuitState.OPEN

        manager.reset_all()

        assert manager.get_state("b1") == CircuitState.CLOSED
        assert manager.get_state("b2") == CircuitState.CLOSED

    def test_remove_backend(self):
        """Test removing a backend's circuit."""
        manager = CircuitBreakerManager()

        manager.record_success("b1")
        manager.remove_backend("b1")

        # Creating new breaker should have fresh metrics
        breaker = manager.get_breaker("b1")
        metrics = breaker.get_metrics()
        assert metrics["total_requests"] == 0


class TestCircuitBreakerStates:
    """Tests for state machine transitions."""

    def test_state_machine_closed_to_open(self):
        """Test CLOSED -> OPEN transition."""
        breaker = CircuitBreaker("b1", failure_threshold=2)

        states = []
        breaker.record_failure()
        states.append(breaker.get_state())
        breaker.record_failure()
        states.append(breaker.get_state())

        assert states[0] == CircuitState.CLOSED
        assert states[1] == CircuitState.OPEN

    def test_state_machine_full_cycle(self):
        """Test full state cycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        breaker = CircuitBreaker(
            "b1",
            failure_threshold=2,
            recovery_timeout=1,
            success_threshold=2,
        )

        # Start CLOSED
        assert breaker.get_state() == CircuitState.CLOSED

        # Go to OPEN
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_state() == CircuitState.OPEN

        # Can't execute
        assert not breaker.can_execute()

        # Wait for HALF_OPEN
        time.sleep(1.1)
        breaker.can_execute()
        assert breaker.get_state() == CircuitState.HALF_OPEN

        # Recover to CLOSED
        breaker.record_success()
        breaker.record_success()
        assert breaker.get_state() == CircuitState.CLOSED

    def test_failure_rate_calculation(self):
        """Test failure rate in metrics."""
        breaker = CircuitBreaker("b1")

        for _ in range(7):
            breaker.record_success()
        for _ in range(3):
            breaker.record_failure()

        metrics = breaker.get_metrics()
        # 3 failures out of 10 = 30%
        assert 25 < metrics["failure_rate"] < 35
