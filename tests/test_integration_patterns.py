"""
Tests for integration hardening patterns.

Tests rate limiting, retry logic, circuit breaker, and health checking.
"""

import asyncio

import pytest

from thomas.integrations._circuit_breaker import CircuitBreaker, CircuitBreakerError
from thomas.integrations._health import IntegrationHealthChecker
from thomas.integrations._rate_limiter import TokenBucketRateLimiter
from thomas.integrations._retry import retry


class TestTokenBucketRateLimiter:
    """Test rate limiter with token bucket algorithm."""

    @pytest.mark.asyncio
    async def test_allows_burst_capacity(self):
        """Test that burst capacity is allowed without waiting."""
        limiter = TokenBucketRateLimiter(rate=10, burst=5, name="test")

        # Should acquire all burst tokens without waiting
        for i in range(5):
            await limiter.acquire()

        # Check tokens depleted
        assert limiter.remaining() < 0.1

    @pytest.mark.asyncio
    async def test_throttles_after_burst(self):
        """Test that requests are throttled after burst exhausted."""
        limiter = TokenBucketRateLimiter(rate=10, burst=2, name="test")

        # Exhaust burst
        await limiter.acquire()
        await limiter.acquire()

        # Next acquire should wait
        import time

        start = time.time()
        await limiter.acquire()
        elapsed = time.time() - start

        # Should wait roughly 0.1 seconds (1 token at 10 per sec)
        assert elapsed > 0.05

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test context manager pattern."""
        limiter = TokenBucketRateLimiter(rate=100, burst=10, name="test")

        async with limiter:
            assert limiter.remaining() < 10

    @pytest.mark.asyncio
    async def test_reset(self):
        """Test resetting limiter."""
        limiter = TokenBucketRateLimiter(rate=10, burst=5, name="test")

        await limiter.acquire()
        await limiter.acquire()

        await limiter.reset()

        # Should have full burst again
        assert limiter.remaining() > 4.9


class TestRetryDecorator:
    """Test retry decorator with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retries_on_error(self):
        """Test that decorator retries on configured errors."""
        call_count = 0

        @retry(
            max_attempts=3,
            backoff_factor=1.5,
            initial_delay=0.01,
            retryable_errors=(ValueError,),
        )
        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = await failing_func()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_attempts_exhausted(self):
        """Test that exception is raised after max attempts."""

        @retry(
            max_attempts=2,
            backoff_factor=1.5,
            initial_delay=0.01,
            retryable_errors=(ValueError,),
        )
        async def failing_func():
            raise ValueError("Persistent error")

        with pytest.raises(ValueError, match="Persistent error"):
            await failing_func()

    @pytest.mark.asyncio
    async def test_respects_retry_after_header(self):
        """Test respecting Retry-After from errors."""

        class RateLimitError(Exception):
            def __init__(self):
                self.retry_after = 0.01

        call_count = 0

        @retry(
            max_attempts=3,
            initial_delay=1.0,
            retryable_errors=(RateLimitError,),
        )
        async def rate_limited():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RateLimitError()
            return "ok"

        import time

        start = time.time()
        result = await rate_limited()
        elapsed = time.time() - start

        assert result == "ok"
        # Should use retry_after (0.01) not initial_delay (1.0)
        assert elapsed < 0.5

    def test_non_retryable_error_raises_immediately(self):
        """Test that non-retryable errors are raised immediately."""

        @retry(
            max_attempts=3,
            retryable_errors=(ValueError,),
        )
        def failing_func():
            raise TypeError("Not retryable")

        with pytest.raises(TypeError, match="Not retryable"):
            failing_func()


class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    @pytest.mark.asyncio
    async def test_closed_state_allows_requests(self):
        """Test that CLOSED state allows all requests."""
        breaker = CircuitBreaker(name="test", failure_threshold=5)

        # Should not raise
        await breaker.check()
        assert breaker.state().value == "closed"

    @pytest.mark.asyncio
    async def test_opens_after_failures(self):
        """Test that circuit opens after threshold failures."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=1,
        )

        # Record failures
        for i in range(3):
            await breaker.record_failure()

        assert breaker.state().value == "open"

    @pytest.mark.asyncio
    async def test_rejects_in_open_state(self):
        """Test that OPEN state rejects requests."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        await breaker.record_failure()

        with pytest.raises(CircuitBreakerError):
            await breaker.check()

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        """Test transition to HALF_OPEN after recovery timeout."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.05,
        )

        await breaker.record_failure()
        assert breaker.state().value == "open"

        # Wait for recovery timeout
        await asyncio.sleep(0.06)

        # Next check should allow one request and transition to half-open
        await breaker.check()
        assert breaker.state().value == "half_open"

    @pytest.mark.asyncio
    async def test_closes_after_success_in_half_open(self):
        """Test that one success in HALF_OPEN closes circuit."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
        )

        await breaker.record_failure()
        await asyncio.sleep(0.02)
        await breaker.check()

        # Record success
        await breaker.record_success()

        assert breaker.state().value == "closed"

    @pytest.mark.asyncio
    async def test_context_manager_pattern(self):
        """Test using circuit breaker as async context manager."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        async with breaker:
            pass  # Success

        # Should be closed
        assert breaker.state().value == "closed"


class TestIntegrationHealthChecker:
    """Test integration health monitoring."""

    @pytest.mark.asyncio
    async def test_register_integration(self):
        """Test registering an integration."""
        checker = IntegrationHealthChecker()

        await checker.register("test_service")

        status = await checker.get_status("test_service")
        assert status is not None
        assert status.name == "test_service"

    @pytest.mark.asyncio
    async def test_record_success(self):
        """Test recording successful operation."""
        checker = IntegrationHealthChecker()

        await checker.register("test_service")
        await checker.record_success("test_service", latency_ms=42.5)

        status = await checker.get_status("test_service")
        assert status.status == "healthy"
        assert status.latency_ms == 42.5
        assert status.error_count == 0

    @pytest.mark.asyncio
    async def test_record_error_degraded(self):
        """Test recording errors marks as degraded."""
        checker = IntegrationHealthChecker()

        await checker.register("test_service")
        await checker.record_error("test_service", ValueError("Test error"))

        status = await checker.get_status("test_service")
        assert status.status == "degraded"
        assert status.error_count == 1
        assert "ValueError" in status.last_error

    @pytest.mark.asyncio
    async def test_record_error_down(self):
        """Test that many errors marks as down."""
        checker = IntegrationHealthChecker()

        await checker.register("test_service")

        # Record multiple errors
        for i in range(5):
            await checker.record_error("test_service", ValueError(f"Error {i}"))

        status = await checker.get_status("test_service")
        assert status.status == "down"
        assert status.error_count == 5

    @pytest.mark.asyncio
    async def test_summary(self):
        """Test health summary across all integrations."""
        checker = IntegrationHealthChecker()

        await checker.register("service1")
        await checker.register("service2")
        await checker.register("service3")

        await checker.record_success("service1")
        await checker.record_error("service2", ValueError("Error"))
        await checker.record_error("service3", ValueError("Error"))

        summary = await checker.get_summary()
        assert summary["total"] == 3
        assert summary["healthy"] == 1
        assert summary["degraded"] == 2

    @pytest.mark.asyncio
    async def test_reset(self):
        """Test resetting health status."""
        checker = IntegrationHealthChecker()

        await checker.register("test_service")
        await checker.record_error("test_service", ValueError("Error"))

        await checker.reset("test_service")

        status = await checker.get_status("test_service")
        assert status.status == "unknown"
        assert status.error_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
