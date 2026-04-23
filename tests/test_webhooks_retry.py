"""Tests for retry logic and circuit breaker."""

from datetime import datetime, timedelta

from thomas.marketplace.webhooks._types import Delivery, DeliveryAttempt, DeliveryStatus, RetryPolicy
from thomas.marketplace.webhooks.retry import (
    CircuitBreaker,
    DeadLetterQueue,
    RetryBudget,
    RetryCalculator,
    RetryScheduler,
)


class TestRetryCalculator:
    """Test retry delay calculation."""

    def test_fixed_strategy(self):
        """Test fixed retry strategy."""
        policy = RetryPolicy(strategy="fixed", base_delay_seconds=5, jitter=False)

        delay1 = RetryCalculator.calculate_delay(policy, 1)
        delay2 = RetryCalculator.calculate_delay(policy, 2)
        delay3 = RetryCalculator.calculate_delay(policy, 3)

        assert delay1 == 5
        assert delay2 == 5
        assert delay3 == 5

    def test_exponential_strategy(self):
        """Test exponential backoff strategy."""
        policy = RetryPolicy(
            strategy="exponential",
            base_delay_seconds=2,
            multiplier=2.0,
            max_delay_seconds=3600,
            jitter=False,
        )

        delay1 = RetryCalculator.calculate_delay(policy, 1)
        delay2 = RetryCalculator.calculate_delay(policy, 2)
        delay3 = RetryCalculator.calculate_delay(policy, 3)

        assert delay1 == 2
        assert delay2 == 4
        assert delay3 == 8

    def test_exponential_respects_max_delay(self):
        """Test that exponential backoff respects max delay."""
        policy = RetryPolicy(
            strategy="exponential",
            base_delay_seconds=2,
            multiplier=2.0,
            max_delay_seconds=10,
            jitter=False,
        )

        delay = RetryCalculator.calculate_delay(policy, 10)
        assert delay <= 10

    def test_fibonacci_strategy(self):
        """Test Fibonacci retry strategy."""
        policy = RetryPolicy(
            strategy="fibonacci",
            base_delay_seconds=1,
            max_delay_seconds=3600,
            jitter=False,
        )

        delay1 = RetryCalculator.calculate_delay(policy, 1)
        delay2 = RetryCalculator.calculate_delay(policy, 2)
        delay3 = RetryCalculator.calculate_delay(policy, 3)

        assert delay1 == 1
        assert delay2 == 1
        assert delay3 == 2

    def test_jitter_factor(self):
        """Test that jitter adds randomness to delays."""
        policy = RetryPolicy(
            strategy="fixed",
            base_delay_seconds=100,
            jitter=True,
        )

        delays = [RetryCalculator.calculate_delay(policy, 1) for _ in range(10)]

        assert len(set(delays)) > 1


class TestRetryScheduler:
    """Test retry scheduling."""

    def test_should_retry_on_failure(self):
        """Test that scheduler allows retry on failure."""
        policy = RetryPolicy(max_attempts=3)
        scheduler = RetryScheduler(policy)

        delivery = Delivery(id="del_1", status=DeliveryStatus.FAILED)
        delivery.attempts.append(DeliveryAttempt(attempt_number=1, status=DeliveryStatus.FAILED))

        assert scheduler.should_retry(delivery)

    def test_should_not_retry_on_success(self):
        """Test that scheduler doesn't retry successful delivery."""
        policy = RetryPolicy(max_attempts=3)
        scheduler = RetryScheduler(policy)

        delivery = Delivery(id="del_1", status=DeliveryStatus.DELIVERED)
        delivery.attempts.append(DeliveryAttempt(attempt_number=1, status=DeliveryStatus.DELIVERED))

        assert not scheduler.should_retry(delivery)

    def test_should_not_retry_after_max_attempts(self):
        """Test that scheduler stops after max attempts."""
        policy = RetryPolicy(max_attempts=2)
        scheduler = RetryScheduler(policy)

        delivery = Delivery(id="del_1", status=DeliveryStatus.FAILED)
        delivery.attempts.append(DeliveryAttempt(attempt_number=1, status=DeliveryStatus.FAILED))
        delivery.attempts.append(DeliveryAttempt(attempt_number=2, status=DeliveryStatus.FAILED))

        assert not scheduler.should_retry(delivery)

    def test_should_not_retry_on_4xx_error(self):
        """Test that 4xx errors are not retried."""
        policy = RetryPolicy(max_attempts=5)
        scheduler = RetryScheduler(policy)

        delivery = Delivery(id="del_1", status=DeliveryStatus.FAILED)
        delivery.attempts.append(
            DeliveryAttempt(
                attempt_number=1,
                status=DeliveryStatus.FAILED,
                status_code=400,
            )
        )

        assert not scheduler.should_retry(delivery)

    def test_schedule_next_retry(self):
        """Test scheduling next retry time."""
        policy = RetryPolicy(
            strategy="fixed",
            base_delay_seconds=5,
            jitter=False,
        )
        scheduler = RetryScheduler(policy)

        delivery = Delivery(id="del_1", status=DeliveryStatus.FAILED)
        delivery.attempts.append(DeliveryAttempt(attempt_number=1, status=DeliveryStatus.FAILED))

        next_retry = scheduler.schedule_next_retry(delivery)

        assert next_retry is not None
        now = datetime.utcnow()
        assert 4 < (next_retry - now).total_seconds() < 6


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_initial_state_closed(self):
        """Test that circuit breaker starts closed."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitBreaker.State.CLOSED
        assert breaker.is_available()

    def test_open_circuit_after_failures(self):
        """Test that circuit opens after threshold failures."""
        breaker = CircuitBreaker(failure_threshold=3)

        for _ in range(3):
            breaker.record_failure()

        assert breaker.state == CircuitBreaker.State.OPEN
        assert not breaker.is_available()

    def test_half_open_after_timeout(self):
        """Test that circuit moves to half-open after timeout."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            timeout_seconds=0,
        )

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreaker.State.OPEN

        breaker.opened_at = datetime.utcnow() - timedelta(seconds=1)
        assert breaker.is_available()
        assert breaker.state == CircuitBreaker.State.HALF_OPEN

    def test_close_after_success_in_half_open(self):
        """Test that circuit closes after successes in half-open."""
        breaker = CircuitBreaker(
            failure_threshold=2,
            success_threshold=2,
        )

        breaker.open()
        breaker.half_open()

        breaker.record_success()
        assert breaker.state == CircuitBreaker.State.HALF_OPEN

        breaker.record_success()
        assert breaker.state == CircuitBreaker.State.CLOSED

    def test_reopen_on_failure_in_half_open(self):
        """Test that circuit reopens if failure in half-open."""
        breaker = CircuitBreaker(failure_threshold=2)

        breaker.open()
        breaker.half_open()

        breaker.record_failure()
        assert breaker.state == CircuitBreaker.State.OPEN

    def test_get_status(self):
        """Test getting circuit breaker status."""
        breaker = CircuitBreaker()
        breaker.record_failure()

        status = breaker.get_status()

        assert status["state"] == CircuitBreaker.State.CLOSED
        assert status["failure_count"] == 1
        assert status["success_count"] == 0


class TestDeadLetterQueue:
    """Test dead letter queue."""

    def test_enqueue_delivery(self):
        """Test adding delivery to dead letter queue."""
        dlq = DeadLetterQueue()
        delivery = Delivery(id="del_1")

        dlq.enqueue(delivery, "Max retries exceeded")

        assert dlq.size() == 1
        assert delivery.status == DeliveryStatus.EXHAUSTED

    def test_get_all_deliveries(self):
        """Test retrieving all dead lettered deliveries."""
        dlq = DeadLetterQueue()
        del1 = Delivery(id="del_1")
        del2 = Delivery(id="del_2")

        dlq.enqueue(del1, "Reason 1")
        dlq.enqueue(del2, "Reason 2")

        all_dlq = dlq.get_all()
        assert len(all_dlq) == 2

    def test_retry_from_dlq(self):
        """Test moving delivery from DLQ back to retry."""
        dlq = DeadLetterQueue()
        delivery = Delivery(id="del_1")

        dlq.enqueue(delivery, "Reason")
        success = dlq.retry(delivery)

        assert success
        assert dlq.size() == 0
        assert delivery.status == DeliveryStatus.RETRYING

    def test_clear_dlq(self):
        """Test clearing dead letter queue."""
        dlq = DeadLetterQueue()
        dlq.enqueue(Delivery(id="del_1"), "Reason 1")
        dlq.enqueue(Delivery(id="del_2"), "Reason 2")

        dlq.clear()

        assert dlq.size() == 0


class TestRetryBudget:
    """Test retry budget limiting."""

    def test_can_retry_within_budget(self):
        """Test that retries are allowed within budget."""
        budget = RetryBudget(max_retries=10, window_seconds=60)

        for _ in range(5):
            assert budget.can_retry()
            budget.record_retry()

    def test_cannot_retry_over_budget(self):
        """Test that retries are denied over budget."""
        budget = RetryBudget(max_retries=2, window_seconds=60)

        budget.record_retry()
        budget.record_retry()

        assert not budget.can_retry()

    def test_budget_refill_after_window(self):
        """Test that budget refills after window expires."""
        budget = RetryBudget(max_retries=1, window_seconds=0)

        budget.record_retry()
        assert not budget.can_retry()

        import time

        time.sleep(0.1)

        assert budget.can_retry()

    def test_get_available(self):
        """Test checking available retries."""
        budget = RetryBudget(max_retries=5, window_seconds=60)

        assert budget.get_available() == 5

        budget.record_retry()
        assert budget.get_available() == 4

    def test_get_status(self):
        """Test getting budget status."""
        budget = RetryBudget(max_retries=10, window_seconds=60)

        budget.record_retry()
        budget.record_retry()

        status = budget.get_status()

        assert status["used"] == 2
        assert status["available"] == 8
        assert status["max"] == 10
