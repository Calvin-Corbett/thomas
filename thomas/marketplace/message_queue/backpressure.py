"""
Backpressure handling for producer throttling and rate limiting.

Implements token bucket rate limiter, sliding window counters,
buffer size limits, and consumer lag monitoring.
"""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class BackpressureConfig:
    """Configuration for backpressure control."""

    enable_rate_limiting: bool = True
    rate_limit_msgs_per_sec: int = 10000
    enable_buffer_limits: bool = True
    max_buffer_size: int = 100000
    enable_lag_monitoring: bool = True
    max_consumer_lag: int = 50000


class TokenBucket:
    """
    Token bucket rate limiter.

    Implements leaky bucket algorithm for rate limiting with
    configurable refill rate.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        """
        Initialize token bucket.

        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1, timeout_ms: int | None = None) -> bool:
        """
        Acquire tokens from bucket.

        Args:
            tokens: Number of tokens to acquire
            timeout_ms: Maximum time to wait for tokens

        Returns:
            True if tokens acquired, False if timeout
        """
        async with self.lock:
            deadline = None
            if timeout_ms is not None:
                deadline = time.monotonic() + (timeout_ms / 1000.0)

            while True:
                now = time.monotonic()

                # Once timeout is reached, fail without applying additional
                # refill so timeout behavior stays deterministic.
                if deadline is not None and now >= deadline and self.tokens < tokens:
                    return False

                # Refill bucket
                elapsed = now - self.last_refill
                self.tokens = min(
                    self.capacity,
                    self.tokens + (elapsed * self.refill_rate),
                )
                self.last_refill = now

                # Check if we have enough tokens
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                # Check timeout
                if deadline is not None and time.monotonic() >= deadline:
                    return False

                # Wait before retrying
                await asyncio.sleep(0.01)

    async def reset(self) -> None:
        """Reset bucket to full capacity."""
        async with self.lock:
            self.tokens = float(self.capacity)
            self.last_refill = time.monotonic()


class SlidingWindow:
    """
    Sliding window counter for rate limiting.

    Tracks message counts in a rolling time window.
    """

    def __init__(self, window_size_ms: int = 1000) -> None:
        """
        Initialize sliding window.

        Args:
            window_size_ms: Window duration in milliseconds
        """
        self.window_size_ms = window_size_ms
        self.timestamps: list = []
        self.lock = asyncio.Lock()

    async def record(self) -> None:
        """Record an event at current time."""
        async with self.lock:
            now = time.time() * 1000  # Convert to ms

            # Remove old entries outside window
            cutoff = now - self.window_size_ms
            self.timestamps = [ts for ts in self.timestamps if ts > cutoff]

            # Add current timestamp
            self.timestamps.append(now)

    async def get_count(self) -> int:
        """
        Get count of events in current window.

        Returns:
            Number of events in sliding window
        """
        async with self.lock:
            now = time.time() * 1000
            cutoff = now - self.window_size_ms
            return sum(1 for ts in self.timestamps if ts > cutoff)

    async def reset(self) -> None:
        """Reset window."""
        async with self.lock:
            self.timestamps = []


class BackpressureManager:
    """
    Manager for backpressure mechanisms.

    Coordinates rate limiting, buffer management, and lag monitoring
    to prevent producer/consumer bottlenecks.
    """

    def __init__(self, config: BackpressureConfig | None = None) -> None:
        """
        Initialize backpressure manager.

        Args:
            config: Backpressure configuration
        """
        self.config = config or BackpressureConfig()

        # Rate limiting
        self.token_bucket = TokenBucket(
            capacity=self.config.rate_limit_msgs_per_sec,
            refill_rate=self.config.rate_limit_msgs_per_sec,
        )

        # Sliding window for tracking
        self.message_window = SlidingWindow(window_size_ms=1000)

        # Buffer tracking
        self.buffer_usage: dict[str, int] = {}
        self.buffer_lock = asyncio.Lock()

        # Consumer lag tracking
        self.consumer_lags: dict[str, int] = {}
        self.lag_lock = asyncio.Lock()

    async def check_can_publish(self, timeout_ms: int = 1000) -> bool:
        """
        Check if producer can publish (apply backpressure if needed).

        Args:
            timeout_ms: Timeout for acquiring tokens

        Returns:
            True if can publish, False if backpressure applied
        """
        if not self.config.enable_rate_limiting:
            return True

        return await self.token_bucket.acquire(tokens=1, timeout_ms=timeout_ms)

    async def record_publish(self) -> None:
        """Record a published message for tracking."""
        await self.message_window.record()

    async def update_buffer_usage(self, producer_id: str, size: int) -> None:
        """
        Update buffer usage for a producer.

        Args:
            producer_id: Producer identifier
            size: Current buffer size
        """
        if not self.config.enable_buffer_limits:
            return

        async with self.buffer_lock:
            self.buffer_usage[producer_id] = size

    async def is_buffer_full(self, producer_id: str) -> bool:
        """
        Check if buffer is at limit.

        Args:
            producer_id: Producer identifier

        Returns:
            True if buffer at limit
        """
        if not self.config.enable_buffer_limits:
            return False

        async with self.buffer_lock:
            return self.buffer_usage.get(producer_id, 0) >= self.config.max_buffer_size

    async def update_consumer_lag(self, consumer_id: str, lag: int) -> None:
        """
        Update consumer lag.

        Args:
            consumer_id: Consumer identifier
            lag: Number of unprocessed messages
        """
        if not self.config.enable_lag_monitoring:
            return

        async with self.lag_lock:
            self.consumer_lags[consumer_id] = lag

    async def get_consumer_lag(self, consumer_id: str) -> int:
        """
        Get consumer lag.

        Args:
            consumer_id: Consumer identifier

        Returns:
            Number of unprocessed messages
        """
        async with self.lag_lock:
            return self.consumer_lags.get(consumer_id, 0)

    async def should_throttle_producer(self) -> bool:
        """
        Determine if producer should be throttled.

        Based on average lag across all consumers.

        Returns:
            True if producer should throttle
        """
        if not self.config.enable_lag_monitoring:
            return False

        async with self.lag_lock:
            if not self.consumer_lags:
                return False

            avg_lag = sum(self.consumer_lags.values()) // len(self.consumer_lags)
            return avg_lag > self.config.max_consumer_lag

    async def get_throughput_msgs_per_sec(self) -> float:
        """
        Get current throughput.

        Returns:
            Messages per second
        """
        count = await self.message_window.get_count()
        # Scale to per-second
        return count

    async def get_stats(self) -> dict[str, any]:
        """
        Get backpressure statistics.

        Returns:
            Dictionary of backpressure metrics
        """
        async with self.buffer_lock:
            total_buffer = sum(self.buffer_usage.values())

        async with self.lag_lock:
            total_lag = sum(self.consumer_lags.values())
            avg_lag = total_lag / len(self.consumer_lags) if self.consumer_lags else 0

        throughput = await self.get_throughput_msgs_per_sec()

        return {
            "total_buffer_usage": total_buffer,
            "producers_tracked": len(self.buffer_usage),
            "consumers_tracked": len(self.consumer_lags),
            "average_consumer_lag": avg_lag,
            "max_consumer_lag": max(self.consumer_lags.values()) if self.consumer_lags else 0,
            "throughput_msgs_per_sec": throughput,
            "rate_limit_active": self.config.enable_rate_limiting,
        }

    async def reset(self) -> None:
        """Reset all tracking."""
        async with self.buffer_lock:
            self.buffer_usage.clear()

        async with self.lag_lock:
            self.consumer_lags.clear()

        await self.token_bucket.reset()
        await self.message_window.reset()
