"""
Tests for health checking module.
"""

from datetime import timedelta

from thomas.marketplace.monitoring._types import Check, CheckStatus
from thomas.marketplace.monitoring.health import HealthChecker, HealthStatus


class TestHealthChecker:
    """Test HealthChecker."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.checker = HealthChecker()

    def test_register_check(self) -> None:
        """Test registering a health check."""
        check = Check(
            name="http_check",
            check_type="http",
            config={"url": "http://localhost:8000/health"},
        )
        self.checker.register_check(check)

        # Verify registered
        assert self.checker._checks["http_check"] == check

    def test_unregister_check(self) -> None:
        """Test unregistering a check."""
        check = Check(name="test_check", check_type="http")
        self.checker.register_check(check)

        assert self.checker.unregister_check("test_check")
        assert "test_check" not in self.checker._checks

    def test_unregister_nonexistent_check(self) -> None:
        """Test unregistering non-existent check."""
        assert not self.checker.unregister_check("nonexistent")

    def test_register_custom_handler(self) -> None:
        """Test registering custom check handler."""

        def custom_handler(check: Check):
            from thomas.marketplace.monitoring._types import CheckResult, CheckStatus

            return CheckResult(
                check=check,
                status=CheckStatus.UP,
                message="Custom check passed",
            )

        self.checker.register_custom_handler("custom_type", custom_handler)
        assert "custom_type" in self.checker._custom_check_handlers

    def test_get_check_result(self) -> None:
        """Test getting check result."""
        result = self.checker.get_check_result("nonexistent")
        assert result is None

    def test_get_check_history(self) -> None:
        """Test getting check history."""
        history = self.checker.get_check_history("nonexistent", limit=10)
        assert len(history) == 0

    def test_get_status(self) -> None:
        """Test getting overall health status."""
        status = self.checker.get_status()
        assert isinstance(status, HealthStatus)
        assert status.overall == CheckStatus.UP

    def test_flap_detection(self) -> None:
        """Test flap detection."""
        check = Check(name="test_check", check_type="http")
        self.checker.register_check(check)

        # This would require running checks and getting history
        result = self.checker.get_flap_detection("test_check")
        assert result is None or isinstance(result, float)

    def test_check_enable_disable(self) -> None:
        """Test enabling/disabling checks."""
        check = Check(name="test_check", check_type="http", enabled=True)
        self.checker.register_check(check)

        assert check.enabled is True

        check.enabled = False
        assert check.enabled is False


class TestCheckTypes:
    """Test different check types."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.checker = HealthChecker()

    def test_http_check_config(self) -> None:
        """Test HTTP check configuration."""
        check = Check(
            name="api_health",
            check_type="http",
            config={
                "url": "http://localhost:8000/health",
                "expected_status": 200,
            },
        )

        assert check.config["url"] == "http://localhost:8000/health"
        assert check.config["expected_status"] == 200

    def test_tcp_check_config(self) -> None:
        """Test TCP check configuration."""
        check = Check(
            name="db_check",
            check_type="tcp",
            config={
                "host": "localhost",
                "port": 5432,
            },
        )

        assert check.config["host"] == "localhost"
        assert check.config["port"] == 5432

    def test_process_check_config(self) -> None:
        """Test process check configuration."""
        check = Check(
            name="app_process",
            check_type="process",
            config={
                "process_name": "myapp",
            },
        )

        assert check.config["process_name"] == "myapp"

    def test_disk_check_config(self) -> None:
        """Test disk check configuration."""
        check = Check(
            name="disk_space",
            check_type="disk",
            config={
                "path": "/",
                "min_free_percent": 10,
                "min_free_gb": 1,
            },
        )

        assert check.config["path"] == "/"
        assert check.config["min_free_percent"] == 10

    def test_custom_check_config(self) -> None:
        """Test custom check configuration."""
        check = Check(
            name="custom_check",
            check_type="custom",
            config={
                "custom_param": "value",
            },
        )

        assert check.config["custom_param"] == "value"


class TestCheckInterval:
    """Test check scheduling intervals."""

    def test_default_interval(self) -> None:
        """Test default check interval."""
        check = Check(name="test_check", check_type="http")
        assert check.interval == timedelta(seconds=30)

    def test_custom_interval(self) -> None:
        """Test custom check interval."""
        interval = timedelta(minutes=5)
        check = Check(
            name="test_check",
            check_type="http",
            interval=interval,
        )

        assert check.interval == interval

    def test_timeout_config(self) -> None:
        """Test check timeout configuration."""
        timeout = timedelta(seconds=10)
        check = Check(
            name="test_check",
            check_type="http",
            timeout=timeout,
        )

        assert check.timeout == timeout


class TestCheckLabels:
    """Test check labels."""

    def test_check_with_labels(self) -> None:
        """Test check with labels."""
        check = Check(
            name="test_check",
            check_type="http",
            labels={"environment": "prod", "team": "backend"},
        )

        assert check.labels["environment"] == "prod"
        assert check.labels["team"] == "backend"

    def test_empty_labels(self) -> None:
        """Test check with empty labels."""
        check = Check(name="test_check", check_type="http")
        assert len(check.labels) == 0


class TestHealthStatus:
    """Test HealthStatus."""

    def test_create_status(self) -> None:
        """Test creating health status."""
        checks = {
            "http_check": CheckStatus.UP,
            "tcp_check": CheckStatus.DOWN,
        }

        status = HealthStatus(
            overall=CheckStatus.DOWN,
            checks=checks,
        )

        assert status.overall == CheckStatus.DOWN
        assert status.checks["http_check"] == CheckStatus.UP

    def test_status_timestamp(self) -> None:
        """Test status includes timestamp."""
        status = HealthStatus(
            overall=CheckStatus.UP,
            checks={},
        )

        assert status.last_update is not None


class TestCheckExecution:
    """Test check execution."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.checker = HealthChecker()

    def test_execute_check_tcp_timeout(self) -> None:
        """Test TCP check with timeout handling."""
        check = Check(
            name="tcp_check",
            check_type="tcp",
            timeout=timedelta(seconds=1),
            config={"host": "127.0.0.1", "port": 12345},
        )

        result = self.checker._execute_check(check)
        assert result is not None

    def test_execute_check_unknown_type(self) -> None:
        """Test execution of unknown check type."""
        check = Check(
            name="unknown_check",
            check_type="unknown_type",
        )

        result = self.checker._execute_check(check)
        assert result.status == CheckStatus.UNKNOWN

    def test_check_result_response_time(self) -> None:
        """Test check result includes response time."""
        from thomas.marketplace.monitoring._types import CheckResult

        check = Check(name="test", check_type="http")
        result = CheckResult(
            check=check,
            status=CheckStatus.UP,
            response_time=123.45,
        )

        assert result.response_time == 123.45

    def test_check_result_details(self) -> None:
        """Test check result details."""
        from thomas.marketplace.monitoring._types import CheckResult

        check = Check(name="test", check_type="disk")
        details = {
            "free_percent": 50.5,
            "free_gb": 100.0,
        }

        result = CheckResult(
            check=check,
            status=CheckStatus.UP,
            details=details,
        )

        assert result.details["free_percent"] == 50.5
