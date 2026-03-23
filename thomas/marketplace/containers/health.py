"""Container health checking."""

import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from thomas.marketplace.containers._types import Container, HealthCheck


class HealthStatus(Enum):
    """Container health status."""

    NONE = "none"
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    status: HealthStatus
    exit_code: int | None = None
    output: str = ""
    error: str = ""
    checked_at: datetime = None

    def __post_init__(self) -> None:
        """Initialize health check result."""
        if self.checked_at is None:
            self.checked_at = datetime.utcnow()


class HealthChecker:
    """Performs container health checks."""

    def __init__(self) -> None:
        """Initialize health checker."""
        self._health_status: dict[str, HealthStatus] = {}
        self._check_history: dict[str, list[HealthCheckResult]] = {}
        self._running_checks: set = set()

    def start_health_checks(self, container: Container) -> None:
        """Start periodic health checks for container.

        Args:
            container: Container to check.
        """
        if not container.health_check:
            return

        if container.id in self._running_checks:
            return

        self._health_status[container.id] = HealthStatus.STARTING
        self._check_history[container.id] = []
        self._running_checks.add(container.id)

        # Start check thread
        thread = threading.Thread(
            target=self._health_check_loop,
            args=(container,),
            daemon=True,
        )
        thread.start()

    def stop_health_checks(self, container_id: str) -> None:
        """Stop health checks for container.

        Args:
            container_id: Container ID.
        """
        self._running_checks.discard(container_id)

    def check_http(
        self,
        container: Container,
        path: str = "/",
        port: int | None = None,
        interval: int = 30,
    ) -> HealthCheckResult:
        """Perform HTTP health check.

        Args:
            container: Container to check.
            path: HTTP path to check.
            port: Port to check (default to first exposed port).
            interval: Check interval in seconds.

        Returns:
            Health check result.
        """
        if not container.ip_address:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                error="Container not connected to network",
            )

        if port is None:
            port = container.ports[0].container_port if container.ports else 80

        try:
            # Simulate HTTP check
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((container.ip_address, port))
            sock.close()

            if result == 0:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    exit_code=0,
                    output="Health check passed",
                )
            else:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    exit_code=1,
                    error=f"Connection refused on {container.ip_address}:{port}",
                )

        except TimeoutError:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                exit_code=1,
                error="Health check timeout",
            )
        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                exit_code=1,
                error=str(e),
            )

    def check_tcp(
        self,
        container: Container,
        port: int | None = None,
    ) -> HealthCheckResult:
        """Perform TCP health check.

        Args:
            container: Container to check.
            port: Port to check.

        Returns:
            Health check result.
        """
        if not container.ip_address:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                error="Container not connected to network",
            )

        if port is None:
            port = container.ports[0].container_port if container.ports else 8080

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((container.ip_address, port))
            sock.close()

            if result == 0:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    exit_code=0,
                    output=f"Connected to {container.ip_address}:{port}",
                )
            else:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    exit_code=1,
                    error=f"Cannot connect to {container.ip_address}:{port}",
                )

        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                exit_code=1,
                error=str(e),
            )

    def check_command(
        self,
        container: Container,
        cmd: str,
    ) -> HealthCheckResult:
        """Perform command health check.

        Args:
            container: Container to check.
            cmd: Command to execute.

        Returns:
            Health check result.
        """
        # Simulate command execution
        try:
            exit_code = 0 if "exit" not in cmd else 1

            if exit_code == 0:
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    exit_code=0,
                    output=f"Command succeeded: {cmd}",
                )
            else:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    exit_code=1,
                    error=f"Command failed: {cmd}",
                )

        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                exit_code=1,
                error=str(e),
            )

    def get_health_status(self, container_id: str) -> HealthStatus:
        """Get current health status.

        Args:
            container_id: Container ID.

        Returns:
            Health status.
        """
        return self._health_status.get(container_id, HealthStatus.NONE)

    def get_health_history(
        self,
        container_id: str,
        limit: int | None = None,
    ) -> list[HealthCheckResult]:
        """Get health check history.

        Args:
            container_id: Container ID.
            limit: Maximum number of results.

        Returns:
            List of health check results.
        """
        history = self._check_history.get(container_id, [])

        if limit:
            history = history[-limit:]

        return history

    def _health_check_loop(self, container: Container) -> None:
        """Run periodic health checks.

        Args:
            container: Container to check.
        """
        health_check = container.health_check
        if not health_check:
            return

        failing_count = 0

        while container.id in self._running_checks:
            try:
                result = self._perform_health_check(container, health_check)
                self._check_history[container.id].append(result)

                if result.status == HealthStatus.HEALTHY:
                    self._health_status[container.id] = HealthStatus.HEALTHY
                    failing_count = 0
                else:
                    failing_count += 1
                    if failing_count >= health_check.retries:
                        self._health_status[container.id] = HealthStatus.UNHEALTHY

                # Trim history
                if len(self._check_history[container.id]) > 100:
                    self._check_history[container.id] = self._check_history[container.id][-100:]

            except Exception:
                pass

            time.sleep(health_check.interval_seconds)

    def _perform_health_check(
        self,
        container: Container,
        health_check: HealthCheck,
    ) -> HealthCheckResult:
        """Perform a single health check.

        Args:
            container: Container to check.
            health_check: Health check configuration.

        Returns:
            Health check result.
        """
        cmd = health_check.test
        if isinstance(cmd, list) and len(cmd) > 0:
            check_type = cmd[0].lower()

            if check_type == "cmd":
                if len(cmd) > 1:
                    return self.check_command(container, " ".join(cmd[1:]))
            elif check_type == "curl":
                path = cmd[1] if len(cmd) > 1 else "/"
                return self.check_http(container, path)
            elif check_type == "tcp":
                port = int(cmd[1]) if len(cmd) > 1 else 80
                return self.check_tcp(container, port)

        # Default: assume it's a command
        return self.check_command(container, " ".join(cmd) if isinstance(cmd, list) else cmd)
