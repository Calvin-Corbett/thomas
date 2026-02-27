"""
Tests for rate limiting.

Verifies token bucket, sliding window, fixed window, and leaky bucket algorithms.
"""

import time

import pytest

from thomas.load_balancer._types import RequestContext
from thomas.load_balancer.rate_limiter import (
    FixedWindowCounter,
    LeakyBucket,
    RateLimiter,
    SlidingWindowCounter,
    TokenBucket,
)


@pytest.fixture
def context():
    """Create test request context."""
    return RequestContext(client_ip="192.168.1.1", path="/api/test")


class TestTokenBucket:
    """Tests for token bucket algorithm."""

    def test_initial_tokens(self):
        """Test bucket starts full."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.tokens == 10

    def test_consume_tokens(self):
        """Test consuming tokens."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)

        assert bucket.try_consume(5)
        assert bucket.tokens == 5

    def test_reject_overdrawn(self):
        """Test rejecting when tokens insufficient."""
        bucket = TokenBucket(capacity=10, refill_rate=1.0)

        bucket.try_consume(10)
        assert not bucket.try_consume(1)

    def test_refill(self):
        """Test bucket refilling over time."""
        bucket = TokenBucket(capacity=10, refill_rate=10.0)  # 10 tokens/sec

        bucket.tokens = 0
        time.sleep(0.2)

        # Should have ~2 tokens after 0.2 seconds
        available = bucket.get_available_tokens()
        assert 1 < available < 3

    def test_refill_capped_at_capacity(self):
        """Test refill doesn't exceed capacity."""
        bucket = TokenBucket(capacity=10, refill_rate=100.0)

        time.sleep(0.2)
        assert bucket.tokens <= 10


class TestSlidingWindowCounter:
    """Tests for sliding window counter."""

    def test_allows_within_limit(self):
        """Test allowing requests within limit."""
        counter = SlidingWindowCounter(limit=5, window_size=60)

        for i in range(5):
            assert counter.try_consume()

        # Sixth should fail
        assert not counter.try_consume()

    def test_window_expiration(self):
        """Test window expiration allowing new requests."""
        counter = SlidingWindowCounter(limit=2, window_size=1)

        # Use up limit
        counter.try_consume()
        counter.try_consume()
        assert not counter.try_consume()

        # Wait for window
        time.sleep(1.1)

        # Should allow again
        assert counter.try_consume()

    def test_rolling_window(self):
        """Test rolling window behavior."""
        counter = SlidingWindowCounter(limit=3, window_size=1)

        # Make 3 requests at time 0
        counter.try_consume()
        counter.try_consume()
        counter.try_consume()

        assert not counter.try_consume()

        # Wait 0.5 seconds, make 1 more request
        time.sleep(0.5)
        assert not counter.try_consume()

        # Wait another 0.6 seconds (total 1.1, first request now old)
        time.sleep(0.6)
        assert counter.try_consume()


class TestFixedWindowCounter:
    """Tests for fixed window counter."""

    def test_allows_within_limit(self):
        """Test allowing requests within limit."""
        counter = FixedWindowCounter(limit=5, window_size=60)

        for i in range(5):
            assert counter.try_consume()

        assert not counter.try_consume()

    def test_window_reset(self):
        """Test window reset after duration."""
        counter = FixedWindowCounter(limit=2, window_size=1)

        counter.try_consume()
        counter.try_consume()
        assert not counter.try_consume()

        # Wait for window reset
        time.sleep(1.1)

        # Should allow again
        assert counter.try_consume()

    def test_sharp_cutoff(self):
        """Test sharp window cutoff behavior."""
        counter = FixedWindowCounter(limit=3, window_size=1)

        counter.try_consume()
        counter.try_consume()
        counter.try_consume()

        # All used up
        assert not counter.try_consume()

        # Right at cutoff
        time.sleep(1.0)
        assert not counter.try_consume()

        # Just past cutoff
        counter.requests_in_window = 0  # Reset manually
        counter.window_start = time.time()
        assert counter.try_consume()


class TestLeakyBucket:
    """Tests for leaky bucket algorithm."""

    def test_capacity_limit(self):
        """Test bucket doesn't exceed capacity."""
        bucket = LeakyBucket(capacity=5, leak_rate=1.0)

        # Fill bucket
        for _ in range(5):
            assert bucket.try_consume()

        # Sixth should fail
        assert not bucket.try_consume()

    def test_leaking(self):
        """Test water leaks from bucket."""
        bucket = LeakyBucket(capacity=5, leak_rate=1.0)  # 1 req/sec

        # Fill bucket
        for _ in range(5):
            bucket.try_consume()

        assert not bucket.try_consume()

        # Wait for 2 seconds of leaking
        time.sleep(2.1)

        # Should have capacity now
        assert bucket.try_consume()

    def test_gradual_leak(self):
        """Test gradual leaking allows steady rate."""
        bucket = LeakyBucket(capacity=10, leak_rate=5.0)  # 5 req/sec

        # Add 10 requests
        for _ in range(10):
            bucket.try_consume()

        # Wait 1 second (5 should leak)
        time.sleep(1.0)

        # Should have room for ~5 more
        count = 0
        for _ in range(6):
            if bucket.try_consume():
                count += 1

        assert 4 <= count <= 6


class TestRateLimiter:
    """Tests for main rate limiter."""

    def test_initialization(self, context):
        """Test rate limiter initialization."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=100, window_size=60)
        assert limiter.algorithm == "token_bucket"
        assert limiter.global_limit == 100

    def test_global_rate_limit(self, context):
        """Test global rate limiting."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=5, window_size=60)

        for _ in range(5):
            allowed, _ = limiter.is_allowed(context)
            assert allowed

        # Sixth should be denied
        allowed, _ = limiter.is_allowed(context)
        assert not allowed

    def test_per_client_limit(self, context):
        """Test per-client rate limiting."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=1000, window_size=60)

        context1 = RequestContext(client_ip="192.168.1.1", path="/test")
        context2 = RequestContext(client_ip="192.168.1.2", path="/test")

        # Each client should have independent limit
        for _ in range(5):
            limiter.is_allowed(context1, client_limit=5)
            limiter.is_allowed(context2, client_limit=5)

        # First client exhausted
        allowed, _ = limiter.is_allowed(context1, client_limit=5)
        assert not allowed

        # Second client still OK
        allowed, _ = limiter.is_allowed(context2, client_limit=5)
        assert allowed

    def test_per_backend_limit(self, context):
        """Test per-backend rate limiting."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=1000, window_size=60)

        for _ in range(3):
            limiter.is_allowed(context, backend_id="b1", backend_limit=3)

        # b1 exhausted
        allowed, _ = limiter.is_allowed(context, backend_id="b1", backend_limit=3)
        assert not allowed

        # b2 OK
        allowed, _ = limiter.is_allowed(context, backend_id="b2", backend_limit=3)
        assert allowed

    def test_rate_limit_headers(self, context):
        """Test rate limit headers in response."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=10, window_size=60)

        allowed, headers = limiter.is_allowed(context)
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers

    def test_reset_client(self, context):
        """Test resetting client rate limit."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=1000, window_size=60)

        # Use up client limit
        for _ in range(5):
            limiter.is_allowed(context, client_limit=5)

        # Exhausted
        allowed, _ = limiter.is_allowed(context, client_limit=5)
        assert not allowed

        # Reset
        limiter.reset_client("192.168.1.1")

        # Should work again
        allowed, _ = limiter.is_allowed(context, client_limit=5)
        assert allowed

    def test_reset_backend(self, context):
        """Test resetting backend rate limit."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=1000, window_size=60)

        # Use up backend limit
        for _ in range(5):
            limiter.is_allowed(context, backend_id="b1", backend_limit=5)

        allowed, _ = limiter.is_allowed(context, backend_id="b1", backend_limit=5)
        assert not allowed

        # Reset
        limiter.reset_backend("b1")

        # Should work again
        allowed, _ = limiter.is_allowed(context, backend_id="b1", backend_limit=5)
        assert allowed

    def test_reset_all(self, context):
        """Test resetting all limiters."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=5, window_size=60)

        # Exhaust limits
        for _ in range(5):
            limiter.is_allowed(context)

        allowed, _ = limiter.is_allowed(context)
        assert not allowed

        # Reset all
        limiter.reset_all()

        allowed, _ = limiter.is_allowed(context)
        assert allowed

    def test_get_stats(self):
        """Test getting limiter statistics."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=100, window_size=60)

        stats = limiter.get_stats()
        assert stats["algorithm"] == "token_bucket"
        assert stats["global_limit"] == 100
        assert stats["window_size"] == 60

    def test_sliding_window_algorithm(self, context):
        """Test with sliding window algorithm."""
        limiter = RateLimiter(algorithm="sliding_window", global_limit=5, window_size=60)

        for _ in range(5):
            allowed, _ = limiter.is_allowed(context)
            assert allowed

        allowed, _ = limiter.is_allowed(context)
        assert not allowed

    def test_fixed_window_algorithm(self, context):
        """Test with fixed window algorithm."""
        limiter = RateLimiter(algorithm="fixed_window", global_limit=5, window_size=60)

        for _ in range(5):
            allowed, _ = limiter.is_allowed(context)
            assert allowed

        allowed, _ = limiter.is_allowed(context)
        assert not allowed

    def test_leaky_bucket_algorithm(self, context):
        """Test with leaky bucket algorithm."""
        limiter = RateLimiter(algorithm="leaky_bucket", global_limit=5, window_size=60)

        for _ in range(5):
            allowed, _ = limiter.is_allowed(context)
            assert allowed

        allowed, _ = limiter.is_allowed(context)
        assert not allowed


class TestRateLimiterCombinations:
    """Tests for combinations of limits."""

    def test_global_and_client_limits(self, context):
        """Test both global and client limits enforced."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=10, window_size=60)

        context1 = RequestContext(client_ip="192.168.1.1", path="/test")

        # Use up global limit
        for _ in range(10):
            limiter.is_allowed(context1, client_limit=20)

        # Should fail on global limit
        allowed, _ = limiter.is_allowed(context1, client_limit=20)
        assert not allowed

    def test_multiple_limit_levels(self, context):
        """Test global, client, and backend limits together."""
        limiter = RateLimiter(algorithm="token_bucket", global_limit=50, window_size=60)

        context1 = RequestContext(client_ip="192.168.1.1", path="/test")

        # Use up client limit
        for _ in range(10):
            limiter.is_allowed(context1, client_limit=10, backend_id="b1", backend_limit=20)

        # Should fail on client limit
        allowed, _ = limiter.is_allowed(context1, client_limit=10, backend_id="b1", backend_limit=20)
        assert not allowed

        # But other clients OK
        context2 = RequestContext(client_ip="192.168.1.2", path="/test")
        allowed, _ = limiter.is_allowed(context2, client_limit=10, backend_id="b1", backend_limit=20)
        assert allowed
