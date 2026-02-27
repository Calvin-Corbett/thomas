"""
Circuit breaker pattern implementation.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests are rejected
- HALF_OPEN: Service recovery test, one request allowed

Features:
- Automatic state transitions
- Tracks failure counts and state changes
- Configurable thresholds
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Raised when circuit is open."""

    pass


class CircuitBreaker:
    """Circuit breaker for fault tolerance.

    Prevents cascading failures by rejecting requests when a service
    is experiencing issues, allowing it time to recover.

    Attributes:
        name: Identifier for logging
        failure_threshold: Number of failures to open circuit
        recovery_timeout: Seconds in open state before half-open
        success_threshold: Successful requests needed to close from half-open
    """

    def __init__(
        self,
        name: str = "circuit",
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 1,
    ):
        """Initialize circuit breaker.

        Args:
            name: Name for logging
            failure_threshold: Failures before opening (default 5)
            recovery_timeout: Seconds in open state (default 60)
            success_threshold: Successes to close from half-open (default 1)
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._last_state_change = time.monotonic()
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> CircuitBreaker:
        """Context manager entry."""
        await self.check()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        if exc_type is not None:
            await self.record_failure()
        else:
            await self.record_success()

    async def check(self) -> None:
        """Check if request is allowed.

        Raises:
            CircuitBreakerError: If circuit is open
        """
        async with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                elapsed = time.monotonic() - self._last_state_change
                if elapsed >= self.recovery_timeout:
                    logger.info(f"{self.name}: recovery timeout elapsed, " f"transitioning to HALF_OPEN")
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0
                    self._last_state_change = time.monotonic()
                else:
                    raise CircuitBreakerError(
                        f"{self.name}: circuit is OPEN (recovery in " f"{self.recovery_timeout - elapsed:.1f}s)"
                    )

            if self._state == CircuitState.HALF_OPEN:
                # Allow single request in half-open state
                pass

    async def record_success(self) -> None:
        """Record successful request."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    logger.info(f"{self.name}: recovered, closing circuit")
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._last_state_change = time.monotonic()

            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                if self._failure_count > 0:
                    self._failure_count = 0
                    logger.debug(f"{self.name}: failure count reset")

    async def record_failure(self) -> None:
        """Record failed request."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                logger.warning(f"{self.name}: failure in HALF_OPEN state, " f"reopening circuit")
                self._state = CircuitState.OPEN
                self._last_state_change = time.monotonic()
                self._success_count = 0

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    logger.error(
                        f"{self.name}: failure threshold ({self.failure_threshold}) " f"reached, opening circuit"
                    )
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.monotonic()
                else:
                    logger.warning(
                        f"{self.name}: failure recorded " f"({self._failure_count}/{self.failure_threshold})"
                    )

    def state(self) -> CircuitState:
        """Get current circuit state.

        Returns:
            Current state (CLOSED, OPEN, or HALF_OPEN)
        """
        return self._state

    def failure_count(self) -> int:
        """Get current failure count.

        Returns:
            Number of consecutive failures
        """
        return self._failure_count

    def last_failure_time(self) -> float | None:
        """Get timestamp of last failure.

        Returns:
            Unix timestamp or None if no failures
        """
        return self._last_failure_time

    async def reset(self) -> None:
        """Reset circuit to closed state."""
        async with self._lock:
            logger.info(f"{self.name}: resetting circuit")
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._last_state_change = time.monotonic()
