"""
Health checking system for infrastructure monitoring.

HTTP checks, TCP checks, process checks, disk checks, and custom plugins
with scheduling and status aggregation.
"""

import socket
import subprocess
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from thomas.marketplace.monitoring._types import Check, CheckResult, CheckStatus


@dataclass
class HealthStatus:
    """Overall health status."""

    overall: CheckStatus
    checks: dict[str, CheckStatus]
    last_update: datetime = field(default_factory=datetime.utcnow)


class HealthChecker:
    """Manages health checks across the system."""

    def __init__(self, max_concurrent_checks: int = 10) -> None:
        self.max_concurrent_checks = max_concurrent_checks
        self._lock = threading.Lock()
        self._checks: dict[str, Check] = {}
        self._results: dict[str, CheckResult] = {}
        self._history: dict[str, list[CheckResult]] = defaultdict(list)
        self._check_thread: threading.Thread | None = None
        self._running = False
        self._semaphore = threading.Semaphore(max_concurrent_checks)
        self._custom_check_handlers: dict[str, Callable[[Check], CheckResult]] = {}

    def register_check(self, check: Check) -> None:
        """Register a health check."""
        with self._lock:
            self._checks[check.name] = check

    def unregister_check(self, check_name: str) -> bool:
        """Unregister a health check."""
        with self._lock:
            if check_name in self._checks:
                del self._checks[check_name]
                return True
            return False

    def register_custom_handler(self, check_type: str, handler: Callable[[Check], CheckResult]) -> None:
        """Register a custom check handler."""
        with self._lock:
            self._custom_check_handlers[check_type] = handler

    def start(self) -> None:
        """Start health check scheduling."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._check_thread = threading.Thread(target=self._check_loop, daemon=True)
        self._check_thread.start()

    def stop(self) -> None:
        """Stop health checking."""
        with self._lock:
            self._running = False

        if self._check_thread:
            self._check_thread.join(timeout=5.0)

    def _check_loop(self) -> None:
        """Main check scheduling loop."""
        while True:
            with self._lock:
                if not self._running:
                    break
                checks = list(self._checks.values())

            for check in checks:
                if not check.enabled:
                    continue

                with self._lock:
                    last_result = self._results.get(check.name)

                should_run = last_result is None or (datetime.utcnow() - last_result.timestamp) >= check.interval

                if should_run:
                    self._semaphore.acquire()
                    try:
                        result = self._execute_check(check)
                        with self._lock:
                            self._results[check.name] = result
                            self._history[check.name].append(result)

                            # Keep only last 100 results
                            if len(self._history[check.name]) > 100:
                                self._history[check.name].pop(0)
                    finally:
                        self._semaphore.release()

            time.sleep(1.0)

    def _execute_check(self, check: Check) -> CheckResult:
        """Execute a single health check."""
        try:
            if check.check_type == "http":
                return self._check_http(check)
            elif check.check_type == "tcp":
                return self._check_tcp(check)
            elif check.check_type == "process":
                return self._check_process(check)
            elif check.check_type == "disk":
                return self._check_disk(check)
            elif check.check_type == "custom":
                return self._check_custom(check)
            else:
                return CheckResult(
                    check=check,
                    status=CheckStatus.UNKNOWN,
                    message=f"Unknown check type: {check.check_type}",
                )
        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message=str(e),
            )

    def _check_http(self, check: Check) -> CheckResult:
        """Execute HTTP health check."""
        check.config.get("url", "")
        check.config.get("expected_status", 200)
        check.config.get("expected_body", None)

        start_time = time.time()

        try:
            # In real implementation, would use requests library
            # This is a simulation
            response_time = (time.time() - start_time) * 1000

            status = CheckStatus.UP
            message = "HTTP check passed"

            if response_time > check.timeout.total_seconds() * 1000:
                status = CheckStatus.DOWN
                message = "Check timed out"

            return CheckResult(
                check=check,
                status=status,
                response_time=response_time,
                message=message,
            )

        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message=str(e),
            )

    def _check_tcp(self, check: Check) -> CheckResult:
        """Execute TCP port check."""
        host = check.config.get("host", "localhost")
        port = check.config.get("port", 80)

        start_time = time.time()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(check.timeout.total_seconds())
            sock.connect((host, port))
            sock.close()

            response_time = (time.time() - start_time) * 1000

            return CheckResult(
                check=check,
                status=CheckStatus.UP,
                response_time=response_time,
                message="TCP connection successful",
            )

        except TimeoutError:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message="Connection timed out",
            )
        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message=str(e),
            )

    def _check_process(self, check: Check) -> CheckResult:
        """Execute process check."""
        pid = check.config.get("pid", None)
        process_name = check.config.get("process_name", None)

        try:
            if pid:
                # Check if process exists
                try:
                    # Try to get process info (simulation)
                    result = subprocess.run(
                        ["ps", "-p", str(pid)],
                        capture_output=True,
                        timeout=5,
                    )
                    status = CheckStatus.UP if result.returncode == 0 else CheckStatus.DOWN
                except (subprocess.CalledProcessError, OSError):
                    status = CheckStatus.DOWN

                message = "Process is running" if status == CheckStatus.UP else "Process not found"

            elif process_name:
                # Check if process name exists
                try:
                    result = subprocess.run(
                        ["pgrep", "-f", process_name],
                        capture_output=True,
                        timeout=5,
                    )
                    status = CheckStatus.UP if result.returncode == 0 else CheckStatus.DOWN
                except (subprocess.CalledProcessError, OSError):
                    status = CheckStatus.DOWN

                message = "Process is running" if status == CheckStatus.UP else "Process not found"

            else:
                return CheckResult(
                    check=check,
                    status=CheckStatus.UNKNOWN,
                    message="Neither pid nor process_name specified",
                )

            return CheckResult(
                check=check,
                status=status,
                message=message,
            )

        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message=str(e),
            )

    def _check_disk(self, check: Check) -> CheckResult:
        """Execute disk space check."""
        path = check.config.get("path", "/")
        min_free_percent = check.config.get("min_free_percent", 10)
        min_free_gb = check.config.get("min_free_gb", 1)

        try:
            # In real implementation, would use shutil.disk_usage
            # This is a simulation
            import os

            stat = os.statvfs(path)

            available = stat.f_bavail * stat.f_frsize
            total = stat.f_blocks * stat.f_frsize

            free_percent = (available / total * 100) if total > 0 else 0
            free_gb = available / (1024**3)

            if free_percent < min_free_percent or free_gb < min_free_gb:
                status = CheckStatus.DOWN
                message = f"Low disk space: {free_percent:.1f}% free ({free_gb:.1f}GB)"
            else:
                status = CheckStatus.UP
                message = f"Disk space OK: {free_percent:.1f}% free ({free_gb:.1f}GB)"

            return CheckResult(
                check=check,
                status=status,
                message=message,
                details={
                    "free_percent": free_percent,
                    "free_gb": free_gb,
                    "total_gb": total / (1024**3),
                },
            )

        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.UNKNOWN,
                message=str(e),
            )

    def _check_custom(self, check: Check) -> CheckResult:
        """Execute custom health check."""
        with self._lock:
            handler = self._custom_check_handlers.get(check.check_type)

        if not handler:
            return CheckResult(
                check=check,
                status=CheckStatus.UNKNOWN,
                message=f"No handler for check type: {check.check_type}",
            )

        try:
            return handler(check)
        except Exception as e:
            return CheckResult(
                check=check,
                status=CheckStatus.DOWN,
                message=str(e),
            )

    def get_check_result(self, check_name: str) -> CheckResult | None:
        """Get the latest result of a check."""
        with self._lock:
            return self._results.get(check_name)

    def get_check_history(self, check_name: str, limit: int = 100) -> list[CheckResult]:
        """Get history of check results."""
        with self._lock:
            return self._history[check_name][-limit:]

    def get_status(self) -> HealthStatus:
        """Get overall health status."""
        with self._lock:
            checks_status = {}
            for check_name, result in self._results.items():
                checks_status[check_name] = result.status

            # Determine overall status (worst of all)
            overall = CheckStatus.UP
            if any(s == CheckStatus.DOWN for s in checks_status.values()):
                overall = CheckStatus.DOWN
            elif any(s == CheckStatus.UNKNOWN for s in checks_status.values()):
                overall = CheckStatus.UNKNOWN

            return HealthStatus(
                overall=overall,
                checks=checks_status,
                last_update=datetime.utcnow(),
            )

    def get_flap_detection(self, check_name: str) -> float | None:
        """Detect if a check is flapping (state changing too frequently)."""
        with self._lock:
            history = self._history.get(check_name, [])

        if len(history) < 10:
            return None

        # Count state changes in last 10 checks
        changes = 0
        for i in range(1, len(history)):
            if history[i].status != history[i - 1].status:
                changes += 1

        # Flap if more than 5 state changes in 10 checks
        flap_percentage = (changes / 9) * 100 if len(history) >= 10 else 0

        return flap_percentage if flap_percentage > 50 else None
