"""
Rate limiting implementation using token bucket algorithm.

Supports:
- Async context manager pattern for easy integration
- Configurable burst capacity and refill rate
- Queue depth monitoring
- Logging of backpressure events
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls.

    Allows a configurable rate with burst capacity. Useful for enforcing
    API rate limits and preventing overwhelming downstream services.

    Attributes:
        rate: Tokens per second (refill rate)
        burst: Maximum tokens in bucket (burst capacity)
        name: Identifier for logging
    """

    def __init__(
        self,
        rate: float,
        burst: int,
        name: str = "limiter",
    ):
        """Initialize rate limiter.

        Args:
            rate: Tokens per second (e.g., 250/60 for 250 per minute)
            burst: Maximum tokens in bucket
            name: Name for logging
        """
        if rate <= 0:
            raise ValueError("Rate must be positive")
        if burst <= 0:
            raise ValueError("Burst must be positive")

        self.rate = rate
        self.burst = burst
        self.name = name

        self._tokens = float(burst)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
        self._queue_depth = 0

    async def __aenter__(self) -> TokenBucketRateLimiter:
        """Context manager entry - acquire permission."""
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        pass

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire (default 1)
        """
        if tokens <= 0:
            raise ValueError("Tokens to acquire must be positive")

        async with self._lock:
            while self._tokens < tokens:
                # Refill bucket
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                self._last_update = now

                if self._tokens < tokens:
                    # Need to wait
                    self._queue_depth += 1
                    wait_time = (tokens - self._tokens) / self.rate

                    if self._queue_depth > 1:
                        logger.warning(
                            f"{self.name}: queue building up (depth={self._queue_depth}), " f"waiting {wait_time:.2f}s"
                        )

                    await asyncio.sleep(wait_time)
                    self._queue_depth -= 1
                else:
                    break

            # Consume tokens
            self._tokens -= tokens
            self._last_update = time.monotonic()

    def remaining(self) -> float:
        """Get current number of tokens available.

        Returns:
            Number of tokens in bucket
        """
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(self.burst, self._tokens + elapsed * self.rate)

    def queue_depth(self) -> int:
        """Get current queue depth.

        Returns:
            Number of requests waiting in queue
        """
        return self._queue_depth

    async def reset(self) -> None:
        """Reset limiter to full capacity."""
        async with self._lock:
            self._tokens = float(self.burst)
            self._last_update = time.monotonic()
            self._queue_depth = 0
