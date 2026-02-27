"""
Health checking system for backends.

Implements active health checking (TCP/HTTP) and passive health detection.
Tracks health history and recovery patterns.
"""

import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque

from thomas.load_balancer._types import Backend, HealthCheckConfig, HealthStatus


class HealthHistory:
    """Tracks the history of health check results for a backend."""

    def __init__(self, max_entries: int = 100) -> None:
        """
        Initialize health history tracker.

        Args:
            max_entries: Maximum number of check results to store.
        """
        self.history: deque[tuple[float, HealthStatus]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(self, status: HealthStatus) -> None:
        """
        Add a health check result.

        Args:
            status: The health status from the check.
        """
        with self._lock:
            self.history.append((time.time(), status))

    def get_recent(self, seconds: int = 60) -> list[HealthStatus]:
        """
        Get recent health statuses.

        Args:
            seconds: Time window in seconds.

        Returns:
            List of HealthStatus values from the specified time window.
        """
        with self._lock:
            cutoff = time.time() - seconds
            return [status for timestamp, status in self.history if timestamp >= cutoff]

    def success_rate(self, seconds: int = 60) -> float:
        """
        Calculate recent success rate.

        Args:
            seconds: Time window in seconds.

        Returns:
            Success rate as percentage (0-100).
        """
        recent = self.get_recent(seconds)
        if not recent:
            return 0.0
        healthy = sum(1 for s in recent if s == HealthStatus.HEALTHY)
        return (healthy / len(recent)) * 100.0


class HealthChecker:
    """
    Active health checking system for backends.

    Performs periodic health checks using TCP/HTTP or custom check functions.
    """

    def __init__(self, config: HealthCheckConfig) -> None:
        """
        Initialize health checker.

        Args:
            config: Health check configuration.
        """
        self.config = config
        self._health_status: dict[str, HealthStatus] = {}
        self._consecutive_failures: dict[str, int] = {}
        self._consecutive_successes: dict[str, int] = {}
        self._last_check_time: dict[str, float] = {}
        self._history: dict[str, HealthHistory] = {}
        self._lock = threading.Lock()
        self._running = False
        self._checker_thread: threading.Thread | None = None

    def start(self, backends: list[Backend]) -> None:
        """
        Start health checking.

        Args:
            backends: List of backends to check.
        """
        if self._running:
            return

        with self._lock:
            # Initialize tracking for backends
            for backend in backends:
                self._health_status[backend.id] = HealthStatus.UNKNOWN
                self._consecutive_failures[backend.id] = 0
                self._consecutive_successes[backend.id] = 0
                self._history[backend.id] = HealthHistory()

            self._running = True

        if self.config.enabled:
            self._checker_thread = threading.Thread(
                target=self._check_loop,
                args=(backends,),
                daemon=True,
            )
            self._checker_thread.start()

    def stop(self) -> None:
        """Stop health checking."""
        self._running = False
        if self._checker_thread:
            self._checker_thread.join(timeout=5)

    def _check_loop(self, backends: list[Backend]) -> None:
        """Main loop for health checking."""
        while self._running:
            for backend in backends:
                if not self._running:
                    break

                try:
                    self._perform_check(backend)
                except Exception:  # REVIEWED: broad catch
                    # Catch all exceptions to keep checker running
                    pass

            time.sleep(self.config.interval)

    def _perform_check(self, backend: Backend) -> None:
        """Perform a health check on a backend."""
        is_healthy = False

        try:
            if self.config.custom_check_fn:
                is_healthy = self.config.custom_check_fn(backend)
            elif self.config.check_type == "tcp":
                is_healthy = self._tcp_check(backend)
            elif self.config.check_type == "http":
                is_healthy = self._http_check(backend)
        except (ConnectionError, TimeoutError):
            is_healthy = False

        self._update_status(backend.id, is_healthy)

    def _tcp_check(self, backend: Backend) -> bool:
        """
        Perform TCP connectivity check.

        Args:
            backend: Backend to check.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.config.timeout)
            sock.connect((backend.host, backend.port))
            sock.close()
            return True
        except (TimeoutError, OSError):
            return False

    def _http_check(self, backend: Backend) -> bool:
        """
        Perform HTTP health check.

        Args:
            backend: Backend to check.

        Returns:
            True if HTTP response matches expected status, False otherwise.
        """
        try:
            url = f"http://{backend.host}:{backend.port}{self.config.http_path}"
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", "LoadBalancerHealthCheck/1.0")

            with urllib.request.urlopen(req, timeout=self.config.timeout) as response:
                return response.status == self.config.http_expected_status
        except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError):
            return False
        except (OSError, FileNotFoundError):
            return False

    def _update_status(self, backend_id: str, is_healthy: bool) -> None:
        """
        Update health status based on check result.

        Args:
            backend_id: ID of the backend.
            is_healthy: Whether the check passed.
        """
        with self._lock:
            if is_healthy:
                self._consecutive_failures[backend_id] = 0
                self._consecutive_successes[backend_id] += 1

                if (
                    self._health_status[backend_id] == HealthStatus.UNHEALTHY
                    and self._consecutive_successes[backend_id] >= self.config.healthy_threshold
                ):
                    self._health_status[backend_id] = HealthStatus.HEALTHY

            else:
                self._consecutive_successes[backend_id] = 0
                self._consecutive_failures[backend_id] += 1

                if (
                    self._health_status[backend_id] == HealthStatus.HEALTHY
                    and self._consecutive_failures[backend_id] >= self.config.unhealthy_threshold
                ):
                    self._health_status[backend_id] = HealthStatus.UNHEALTHY

            status = self._health_status[backend_id]
            if backend_id in self._history:
                self._history[backend_id].add(status)

            self._last_check_time[backend_id] = time.time()

    def get_status(self, backend_id: str) -> HealthStatus:
        """
        Get current health status of a backend.

        Args:
            backend_id: ID of the backend.

        Returns:
            Current HealthStatus.
        """
        with self._lock:
            return self._health_status.get(backend_id, HealthStatus.UNKNOWN)

    def mark_unhealthy(self, backend_id: str) -> None:
        """
        Mark a backend as unhealthy (passive health detection).

        Called when errors occur during request processing to mark
        backends unhealthy without waiting for active checks.

        Args:
            backend_id: ID of the backend to mark unhealthy.
        """
        with self._lock:
            self._consecutive_successes[backend_id] = 0
            self._consecutive_failures[backend_id] += 1

            if self._consecutive_failures[backend_id] >= self.config.unhealthy_threshold:
                self._health_status[backend_id] = HealthStatus.UNHEALTHY

            if backend_id in self._history:
                self._history[backend_id].add(self._health_status.get(backend_id, HealthStatus.UNHEALTHY))

    def is_healthy(self, backend_id: str) -> bool:
        """
        Check if a backend is healthy.

        Args:
            backend_id: ID of the backend.

        Returns:
            True if backend is healthy, False otherwise.
        """
        return self.get_status(backend_id) == HealthStatus.HEALTHY

    def get_healthy_backends(self, backends: list[Backend]) -> list[Backend]:
        """
        Get list of healthy backends.

        Args:
            backends: List of all backends.

        Returns:
            Filtered list of only healthy backends.
        """
        return [b for b in backends if self.is_healthy(b.id)]

    def get_health_summary(self) -> dict[str, dict]:
        """
        Get health summary for all backends.

        Returns:
            Dict mapping backend ID to health info (status, successes, failures, history).
        """
        with self._lock:
            summary = {}
            for backend_id, status in self._health_status.items():
                history = self._history.get(backend_id)
                summary[backend_id] = {
                    "status": status.value,
                    "consecutive_successes": self._consecutive_successes[backend_id],
                    "consecutive_failures": self._consecutive_failures[backend_id],
                    "last_check": self._last_check_time.get(backend_id, 0),
                    "success_rate": history.success_rate() if history else 0,
                }
            return summary

    def add_backend(self, backend: Backend) -> None:
        """
        Add a new backend to health tracking.

        Args:
            backend: Backend to add.
        """
        with self._lock:
            if backend.id not in self._health_status:
                self._health_status[backend.id] = HealthStatus.UNKNOWN
                self._consecutive_failures[backend.id] = 0
                self._consecutive_successes[backend.id] = 0
                self._history[backend.id] = HealthHistory()

    def remove_backend(self, backend_id: str) -> None:
        """
        Remove a backend from health tracking.

        Args:
            backend_id: ID of backend to remove.
        """
        with self._lock:
            self._health_status.pop(backend_id, None)
            self._consecutive_failures.pop(backend_id, None)
            self._consecutive_successes.pop(backend_id, None)
            self._history.pop(backend_id, None)
            self._last_check_time.pop(backend_id, None)
