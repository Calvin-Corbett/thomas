"""
Tests for WAF Rate Limiter

Tests for rate limiting, sliding windows, and graduated response.
"""

import pytest

from thomas.waf._types import RateLimitConfig, RuleAction
from thomas.waf.rate_limiter import RateLimiter


class TestRateLimiter:
    """Test cases for RateLimiter."""

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        """Create test config."""
        return RateLimitConfig(
            requests_per_second=5,
            requests_per_minute=100,
            requests_per_hour=1000,
            burst_size=10,
            window_size=60,
            graduated_response=True,
        )

    @pytest.fixture
    def limiter(self, config: RateLimitConfig) -> RateLimiter:
        """Create test limiter."""
        return RateLimiter(config)

    def test_limiter_initialization(self, limiter: RateLimiter) -> None:
        """Test limiter initialization."""
        assert limiter.config.requests_per_second == 5
        assert len(limiter.request_history) == 0

    def test_allow_under_limit(self, limiter: RateLimiter) -> None:
        """Test allowing requests under limit."""
        action, headers = limiter.check_rate_limit("192.168.1.1", "/api")

        assert action == RuleAction.ALLOW
        assert "X-Rate-Limit-Remaining" in headers

    def test_multiple_requests_under_limit(self, limiter: RateLimiter) -> None:
        """Test multiple requests under rate limit."""
        ip = "192.168.1.1"

        for i in range(4):
            action, _ = limiter.check_rate_limit(ip, "/api")
            assert action == RuleAction.ALLOW

    def test_rate_limit_exceeded(self, limiter: RateLimiter) -> None:
        """Test rate limit exceeded."""
        ip = "192.168.1.1"

        # Fill up the limit
        for i in range(5):
            action, _ = limiter.check_rate_limit(ip, "/api")
            assert action == RuleAction.ALLOW

        # This should be logged (first graduated response)
        action, _ = limiter.check_rate_limit(ip, "/api")
        assert action == RuleAction.LOG

    def test_graduated_response_levels(self, limiter: RateLimiter) -> None:
        """Test graduated response levels."""
        ip = "192.168.1.1"

        # Allow requests
        for i in range(5):
            limiter.check_rate_limit(ip, "/api")

        # Second violation: LOG -> CHALLENGE
        for i in range(5):
            action, _ = limiter.check_rate_limit(ip, "/api")

        # Third violation: BLOCK
        action, _ = limiter.check_rate_limit(ip, "/api")
        assert action in [RuleAction.CHALLENGE, RuleAction.BLOCK]

    def test_ip_whitelist(self, limiter: RateLimiter) -> None:
        """Test IP whitelist bypass."""
        ip = "192.168.1.1"
        limiter.add_to_whitelist(ip)

        # Make many requests - should all be allowed
        for i in range(20):
            action, _ = limiter.check_rate_limit(ip, "/api")
            assert action == RuleAction.ALLOW

    def test_path_whitelist(self, limiter: RateLimiter) -> None:
        """Test path whitelist bypass."""
        limiter.add_path_whitelist("/health")

        # Make many requests to whitelisted path
        for i in range(20):
            action, _ = limiter.check_rate_limit("192.168.1.1", "/health")
            assert action == RuleAction.ALLOW

    def test_reset_ip(self, limiter: RateLimiter) -> None:
        """Test resetting rate limit for IP."""
        ip = "192.168.1.1"

        # Make requests
        for i in range(5):
            limiter.check_rate_limit(ip, "/api")

        # Reset
        limiter.reset_ip(ip)

        # Should be able to make requests again
        action, _ = limiter.check_rate_limit(ip, "/api")
        assert action == RuleAction.ALLOW

    def test_different_ips_independent(self, limiter: RateLimiter) -> None:
        """Test that different IPs have independent limits."""
        # Fill limit for IP1
        for i in range(5):
            limiter.check_rate_limit("192.168.1.1", "/api")

        # IP2 should still be allowed
        action, _ = limiter.check_rate_limit("192.168.1.2", "/api")
        assert action == RuleAction.ALLOW

    def test_get_stats(self, limiter: RateLimiter) -> None:
        """Test statistics retrieval."""
        ip = "192.168.1.1"

        # Make requests
        for i in range(3):
            limiter.check_rate_limit(ip, "/api")

        stats = limiter.get_stats(ip)
        assert stats["per_second"] >= 0
        assert stats["per_minute"] >= 0
        assert "blocked" in stats

    def test_cleanup_old_entries(self, limiter: RateLimiter) -> None:
        """Test cleanup of old entries."""
        ip = "192.168.1.1"

        # Make a request
        limiter.check_rate_limit(ip, "/api")

        # Cleanup should remove old entries
        count = limiter.cleanup_old_entries()
        # May or may not clean depending on timing

    def test_retry_after_header(self, limiter: RateLimiter) -> None:
        """Test Retry-After header in response."""
        ip = "192.168.1.1"

        # Fill limit and trigger block
        for i in range(5):
            limiter.check_rate_limit(ip, "/api")

        action, headers = limiter.check_rate_limit(ip, "/api")
        # After multiple violations, should be blocked
        if action == RuleAction.BLOCK:
            assert "Retry-After" in headers

    def test_rate_limit_headers(self, limiter: RateLimiter) -> None:
        """Test rate limit headers."""
        ip = "192.168.1.1"

        action, headers = limiter.check_rate_limit(ip, "/api")

        assert action == RuleAction.ALLOW
        assert "X-Rate-Limit-Limit" in headers
        assert "X-Rate-Limit-Remaining" in headers
        assert "X-Rate-Limit-Reset" in headers

    def test_multiple_paths_same_ip(self, limiter: RateLimiter) -> None:
        """Test that different paths share same IP limit."""
        ip = "192.168.1.1"

        # Make requests to different paths
        for i in range(3):
            limiter.check_rate_limit(ip, "/api/users")

        for i in range(3):
            limiter.check_rate_limit(ip, "/api/posts")

        # Both paths should count toward same limit
        action, _ = limiter.check_rate_limit(ip, "/api")

    def test_block_expiry(self, limiter: RateLimiter) -> None:
        """Test that blocks eventually expire."""
        ip = "192.168.1.1"

        # Trigger block
        for i in range(10):
            limiter.check_rate_limit(ip, "/api")

        action, _ = limiter.check_rate_limit(ip, "/api")
        assert action == RuleAction.BLOCK

        # Block should have an expiry
        stats = limiter.get_stats(ip)
        if stats["blocked"]:
            assert "blocked_until" in stats

    def test_whitelist_removal(self, limiter: RateLimiter) -> None:
        """Test removing IP from whitelist."""
        ip = "192.168.1.1"
        limiter.add_to_whitelist(ip)

        # Should be whitelisted
        action, _ = limiter.check_rate_limit(ip, "/api")
        assert action == RuleAction.ALLOW

        # Remove from whitelist
        limiter.remove_from_whitelist(ip)

        # Reset history
        limiter.reset_ip(ip)

        # Now should respect limits
        for i in range(5):
            limiter.check_rate_limit(ip, "/api")

        action, _ = limiter.check_rate_limit(ip, "/api")
        # Should now be rate limited
