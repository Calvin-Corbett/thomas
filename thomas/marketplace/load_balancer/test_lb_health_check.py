"""
Tests for health checking system.

Verifies TCP/HTTP checks, thresholds, and passive detection.
"""

from unittest.mock import patch

import pytest

from thomas.marketplace.load_balancer._types import Backend, HealthCheckConfig, HealthStatus
from thomas.marketplace.load_balancer.health_check import HealthChecker, HealthHistory


@pytest.fixture
def backends():
    """Create test backends."""
    return [
        Backend("b1", "127.0.0.1", 8080),
        Backend("b2", "127.0.0.1", 8081),
    ]


@pytest.fixture
def health_config():
    """Create test health check config."""
    return HealthCheckConfig(
        enabled=True,
        interval=1,
        timeout=1,
        healthy_threshold=2,
        unhealthy_threshold=2,
        check_type="tcp",
    )


class TestHealthHistory:
    """Tests for health history tracking."""

    def test_add_status(self):
        """Test adding status entries."""
        history = HealthHistory()
        history.add(HealthStatus.HEALTHY)
        history.add(HealthStatus.HEALTHY)
        history.add(HealthStatus.UNHEALTHY)

        recent = history.get_recent(60)
        assert len(recent) == 3
        assert recent.count(HealthStatus.HEALTHY) == 2
        assert recent.count(HealthStatus.UNHEALTHY) == 1

    def test_success_rate(self):
        """Test success rate calculation."""
        history = HealthHistory()
        for _ in range(8):
            history.add(HealthStatus.HEALTHY)
        for _ in range(2):
            history.add(HealthStatus.UNHEALTHY)

        rate = history.success_rate(60)
        assert 75 < rate < 85  # 80% success rate

    def test_max_entries(self):
        """Test max entries limit."""
        history = HealthHistory(max_entries=5)
        for i in range(10):
            history.add(HealthStatus.HEALTHY)

        recent = history.get_recent(60)
        assert len(recent) <= 5


class TestHealthChecker:
    """Tests for health checker."""

    def test_initialization(self, backends, health_config):
        """Test health checker initialization."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        assert checker.get_status("b1") == HealthStatus.UNKNOWN
        assert checker.get_status("b2") == HealthStatus.UNKNOWN

        checker.stop()

    def test_mark_unhealthy(self, backends, health_config):
        """Test passive health marking."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # Mark unhealthy passively
        for _ in range(health_config.unhealthy_threshold):
            checker.mark_unhealthy("b1")

        assert checker.get_status("b1") == HealthStatus.UNHEALTHY
        checker.stop()

    def test_custom_check_function(self, backends):
        """Test custom check function."""
        check_called = []

        def custom_check(backend):
            check_called.append(backend.id)
            return backend.id == "b1"

        config = HealthCheckConfig(enabled=False, custom_check_fn=custom_check)
        checker = HealthChecker(config)

        checker._perform_check(backends[0])
        checker._perform_check(backends[1])

        assert "b1" in check_called
        assert "b2" in check_called

    def test_tcp_check_connection(self, backends, health_config):
        """Test TCP connectivity check."""
        checker = HealthChecker(health_config)

        # Test with unreachable host
        with patch.object(checker, "_tcp_check", return_value=False):
            checker._perform_check(backends[0])

        # Status should become unhealthy after threshold
        checker.mark_unhealthy("b1")
        checker.mark_unhealthy("b1")
        assert checker.get_status("b1") == HealthStatus.UNHEALTHY

    def test_http_check(self, backends):
        """Test HTTP health check."""
        config = HealthCheckConfig(
            enabled=False,
            check_type="http",
            http_path="/health",
            http_expected_status=200,
        )
        checker = HealthChecker(config)

        with patch.object(checker, "_http_check", return_value=True):
            checker._perform_check(backends[0])

    def test_consecutive_failures_threshold(self, backends, health_config):
        """Test failure threshold triggering."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # Simulate failures
        for _ in range(health_config.unhealthy_threshold):
            checker.mark_unhealthy("b1")

        assert checker.get_status("b1") == HealthStatus.UNHEALTHY
        checker.stop()

    def test_consecutive_successes_recovery(self, backends, health_config):
        """Test recovery from unhealthy state."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # First mark unhealthy
        for _ in range(health_config.unhealthy_threshold):
            checker.mark_unhealthy("b1")

        assert checker.get_status("b1") == HealthStatus.UNHEALTHY

        # Then simulate successes
        for _ in range(health_config.healthy_threshold):
            checker._update_status("b1", True)

        assert checker.get_status("b1") == HealthStatus.HEALTHY
        checker.stop()

    def test_is_healthy(self, backends, health_config):
        """Test is_healthy check."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # Unknown starts as not healthy
        assert not checker.is_healthy("b1")

        # Mark healthy
        for _ in range(health_config.healthy_threshold):
            checker._update_status("b1", True)

        assert checker.is_healthy("b1")
        checker.stop()

    def test_get_healthy_backends(self, backends, health_config):
        """Test filtering healthy backends."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # All start unhealthy
        healthy = checker.get_healthy_backends(backends)
        assert len(healthy) == 0

        # Mark b1 healthy
        for _ in range(health_config.healthy_threshold):
            checker._update_status("b1", True)

        healthy = checker.get_healthy_backends(backends)
        assert len(healthy) == 1
        assert healthy[0].id == "b1"

        checker.stop()

    def test_get_health_summary(self, backends, health_config):
        """Test health summary export."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        summary = checker.get_health_summary()
        assert "b1" in summary
        assert "b2" in summary
        assert "status" in summary["b1"]
        assert "success_rate" in summary["b1"]

        checker.stop()

    def test_add_backend(self, health_config):
        """Test adding backend to checker."""
        checker = HealthChecker(health_config)
        checker.start([])

        backend = Backend("b3", "127.0.0.1", 8082)
        checker.add_backend(backend)

        assert checker.get_status("b3") == HealthStatus.UNKNOWN
        checker.stop()

    def test_remove_backend(self, backends, health_config):
        """Test removing backend from checker."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        assert checker.get_status("b1") is not None
        checker.remove_backend("b1")

        # Status should return UNKNOWN after removal
        summary = checker.get_health_summary()
        assert "b1" not in summary

        checker.stop()


class TestHealthCheckConfig:
    """Tests for health check configuration validation."""

    def test_invalid_interval(self):
        """Test validation of interval."""
        with pytest.raises(ValueError):
            HealthCheckConfig(interval=0)

    def test_invalid_timeout(self):
        """Test validation of timeout."""
        with pytest.raises(ValueError):
            HealthCheckConfig(timeout=0)

    def test_timeout_exceeds_interval(self):
        """Test that timeout cannot exceed interval."""
        with pytest.raises(ValueError):
            HealthCheckConfig(interval=1, timeout=10)

    def test_invalid_check_type(self):
        """Test invalid check type."""
        with pytest.raises(ValueError):
            HealthCheckConfig(check_type="invalid")

    def test_valid_config(self):
        """Test valid configuration."""
        config = HealthCheckConfig(
            enabled=True,
            interval=10,
            timeout=5,
            healthy_threshold=2,
            unhealthy_threshold=3,
            check_type="http",
        )
        assert config.interval == 10
        assert config.timeout == 5


class TestHealthCheckRecovery:
    """Tests for recovery patterns."""

    def test_gradual_recovery(self, backends, health_config):
        """Test gradual recovery from unhealthy state."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # Mark unhealthy
        for _ in range(health_config.unhealthy_threshold):
            checker.mark_unhealthy("b1")

        assert checker.get_status("b1") == HealthStatus.UNHEALTHY

        # Partial recovery (not enough for healthy)
        checker._update_status("b1", True)
        assert checker.get_status("b1") == HealthStatus.UNHEALTHY

        # Complete recovery
        checker._update_status("b1", True)
        assert checker.get_status("b1") == HealthStatus.HEALTHY

        checker.stop()

    def test_failure_during_recovery(self, backends, health_config):
        """Test failure resets recovery progress."""
        checker = HealthChecker(health_config)
        checker.start(backends)

        # Mark unhealthy
        for _ in range(health_config.unhealthy_threshold):
            checker.mark_unhealthy("b1")

        # Start recovery
        checker._update_status("b1", True)

        # But then fail
        checker.mark_unhealthy("b1")

        # Should not immediately recover
        assert checker.get_status("b1") == HealthStatus.UNHEALTHY

        checker.stop()
