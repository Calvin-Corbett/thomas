"""
Integration health checking system.

Tracks:
- Health status (healthy, degraded, down)
- Latency metrics
- Error rates and last error
- Last check timestamp
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health status snapshot for an integration.

    Attributes:
        name: Integration name
        status: One of "healthy", "degraded", "down"
        latency_ms: Last request latency in milliseconds
        last_check: Unix timestamp of last check
        error_count: Total errors since last reset
        last_error: Description of last error if any
    """

    name: str
    status: str = "unknown"
    latency_ms: float = 0.0
    last_check: float = field(default_factory=time.time)
    error_count: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check,
            "error_count": self.error_count,
            "last_error": self.last_error,
        }


class IntegrationHealthChecker:
    """Central health checker for all integrations.

    Maintains health status for multiple integrations and provides
    aggregated health views.
    """

    def __init__(self) -> None:
        """Initialize health checker."""
        self._integrations: dict[str, HealthStatus] = {}
        self._lock = asyncio.Lock()

    async def register(self, name: str) -> None:
        """Register an integration for health monitoring.

        Args:
            name: Integration name
        """
        async with self._lock:
            if name not in self._integrations:
                self._integrations[name] = HealthStatus(name=name)
                logger.debug(f"Registered integration: {name}")

    async def record_success(
        self,
        name: str,
        latency_ms: float = 0.0,
    ) -> None:
        """Record successful operation.

        Args:
            name: Integration name
            latency_ms: Request latency in milliseconds
        """
        async with self._lock:
            if name not in self._integrations:
                self._integrations[name] = HealthStatus(name=name)

            status = self._integrations[name]
            status.latency_ms = latency_ms
            status.last_check = time.time()
            status.status = "healthy"
            status.last_error = None

    async def record_error(
        self,
        name: str,
        error: Exception,
        latency_ms: float = 0.0,
    ) -> None:
        """Record failed operation.

        Args:
            name: Integration name
            error: Exception that occurred
            latency_ms: Request latency in milliseconds
        """
        async with self._lock:
            if name not in self._integrations:
                self._integrations[name] = HealthStatus(name=name)

            status = self._integrations[name]
            status.latency_ms = latency_ms
            status.last_check = time.time()
            status.error_count += 1
            status.last_error = f"{type(error).__name__}: {str(error)[:100]}"

            # Mark degraded after 1-2 errors, down after more
            if status.error_count >= 5:
                status.status = "down"
            elif status.error_count >= 2:
                status.status = "degraded"
            else:
                status.status = "degraded"

    async def get_status(self, name: str) -> HealthStatus | None:
        """Get health status for an integration.

        Args:
            name: Integration name

        Returns:
            HealthStatus or None if not registered
        """
        async with self._lock:
            return self._integrations.get(name)

    async def get_all_status(self) -> dict[str, HealthStatus]:
        """Get health status for all integrations.

        Returns:
            Dictionary mapping integration names to health status
        """
        async with self._lock:
            return dict(self._integrations)

    async def get_summary(self) -> dict[str, Any]:
        """Get summary of all integration health.

        Returns:
            Summary dict with aggregate stats
        """
        async with self._lock:
            if not self._integrations:
                return {"total": 0, "healthy": 0, "degraded": 0, "down": 0}

            healthy = sum(1 for s in self._integrations.values() if s.status == "healthy")
            degraded = sum(1 for s in self._integrations.values() if s.status == "degraded")
            down = sum(1 for s in self._integrations.values() if s.status == "down")

            avg_latency = (
                sum(s.latency_ms for s in self._integrations.values()) / len(self._integrations)
                if self._integrations
                else 0.0
            )

            return {
                "total": len(self._integrations),
                "healthy": healthy,
                "degraded": degraded,
                "down": down,
                "avg_latency_ms": avg_latency,
            }

    async def reset(self, name: str | None = None) -> None:
        """Reset health status for integration(s).

        Args:
            name: Integration name, or None to reset all
        """
        async with self._lock:
            if name:
                if name in self._integrations:
                    self._integrations[name] = HealthStatus(name=name)
                    logger.info(f"Reset health status for {name}")
            else:
                self._integrations.clear()
                logger.info("Reset all health statuses")


# Global instance for convenient access
_global_health_checker: IntegrationHealthChecker | None = None


def get_health_checker() -> IntegrationHealthChecker:
    """Get or create global health checker instance.

    Returns:
        Global IntegrationHealthChecker instance
    """
    global _global_health_checker
    if _global_health_checker is None:
        _global_health_checker = IntegrationHealthChecker()
    return _global_health_checker
