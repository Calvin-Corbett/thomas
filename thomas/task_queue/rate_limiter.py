"""
Rate limiting implementation with token bucket and sliding window.

Implements rate limiting strategies for:
- Per-queue rate limiting
- Per-task-type rate limiting
- Token bucket algorithm
- Sliding window algorithm
- Burst handling
"""

import threading
import time
from collections import deque
from datetime import datetime
from enum import Enum

from thomas.task_queue._exceptions import RateLimitExceededError


class RateLimitStrategy(Enum):
    """Rate limiting strategies."""

    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"


class TokenBucket:
    """
    Token bucket rate limiter.

    Allows bursts of up to `capacity` requests and refills at `rate` per second.
    """

    def __init__(self, capacity: int, rate: float) -> None:
        """
        Initialize TokenBucket.

        Args:
            capacity: Maximum tokens in bucket.
            rate: Tokens added per second.
        """
        self.capacity: int = capacity
        self.rate: float = rate
        self._tokens: float = float(capacity)
        self._last_refill: datetime = datetime.utcnow()
        self._lock: threading.Lock = threading.Lock()

    def allow_request(self, tokens: int = 1) -> bool:
        """
        Check if a request should be allowed.

        Args:
            tokens: Number of tokens required.

        Returns:
            True if request can proceed, False if rate limit exceeded.
        """
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_if_needed(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """
        Wait until request is allowed or timeout expires.

        Args:
            tokens: Number of tokens required.
            timeout: Maximum seconds to wait.

        Returns:
            True if request allowed, False if timeout.
        """
        deadline = time.time() + (timeout or float("inf"))
        while time.time() < deadline:
            if self.allow_request(tokens):
                return True
            time.sleep(0.01)
        return False

    def get_tokens(self) -> float:
        """Get current token count."""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = datetime.utcnow()
        elapsed = (now - self._last_refill).total_seconds()
        tokens_to_add = elapsed * self.rate
        self._tokens = min(self.capacity, self._tokens + tokens_to_add)
        self._last_refill = now


class SlidingWindowLimiter:
    """
    Sliding window rate limiter.

    Tracks requests in a time window and enforces rate limits.
    """

    def __init__(self, limit: int, window_seconds: float) -> None:
        """
        Initialize SlidingWindowLimiter.

        Args:
            limit: Maximum requests in window.
            window_seconds: Size of the window in seconds.
        """
        self.limit: int = limit
        self.window_seconds: float = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock: threading.Lock = threading.Lock()

    def allow_request(self) -> bool:
        """
        Check if a request should be allowed.

        Returns:
            True if request can proceed, False if rate limit exceeded.
        """
        with self._lock:
            self._cleanup_expired()
            if len(self._timestamps) < self.limit:
                self._timestamps.append(time.time())
                return True
            return False

    def get_request_count(self) -> int:
        """Get current request count in window."""
        with self._lock:
            self._cleanup_expired()
            return len(self._timestamps)

    def _cleanup_expired(self) -> None:
        """Remove requests outside the window."""
        cutoff = time.time() - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


class RateLimiter:
    """
    Multi-level rate limiter with per-queue and per-task support.

    Supports both token bucket and sliding window algorithms.
    """

    def __init__(
        self,
        strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET,
    ) -> None:
        """
        Initialize RateLimiter.

        Args:
            strategy: Rate limiting strategy to use.
        """
        self.strategy: RateLimitStrategy = strategy
        self._queue_limiters: dict[str, TokenBucket] = {}
        self._task_limiters: dict[str, TokenBucket] = {}
        self._window_limiters: dict[str, SlidingWindowLimiter] = {}
        self._lock: threading.RLock = threading.RLock()

    def add_queue_limit(
        self,
        queue_name: str,
        rate: float,
        burst: int = 1,
    ) -> None:
        """
        Set rate limit for a queue.

        Args:
            queue_name: Name of the queue.
            rate: Requests per second allowed.
            burst: Maximum burst size.
        """
        with self._lock:
            if self.strategy == RateLimitStrategy.TOKEN_BUCKET:
                self._queue_limiters[queue_name] = TokenBucket(burst, rate)
            else:
                window_size = 1.0
                limit = int(rate * window_size)
                self._window_limiters[queue_name] = SlidingWindowLimiter(limit, window_size)

    def add_task_limit(
        self,
        task_name: str,
        rate: float,
        burst: int = 1,
    ) -> None:
        """
        Set rate limit for a task type.

        Args:
            task_name: Name of the task.
            rate: Requests per second allowed.
            burst: Maximum burst size.
        """
        with self._lock:
            if self.strategy == RateLimitStrategy.TOKEN_BUCKET:
                self._task_limiters[task_name] = TokenBucket(burst, rate)
            else:
                window_size = 1.0
                limit = int(rate * window_size)
                self._window_limiters[f"task_{task_name}"] = SlidingWindowLimiter(limit, window_size)

    def allow_enqueue(
        self,
        queue_name: str,
        task_name: str | None = None,
    ) -> bool:
        """
        Check if task can be enqueued.

        Args:
            queue_name: Name of the queue.
            task_name: Optional task type name.

        Returns:
            True if request allowed, False if rate limited.

        Raises:
            RateLimitExceededError: If rate limit exceeded.
        """
        with self._lock:
            # Check queue limit
            if queue_name in self._queue_limiters:
                if not self._queue_limiters[queue_name].allow_request():
                    raise RateLimitExceededError(
                        f"queue:{queue_name}",
                        self._queue_limiters[queue_name].capacity,
                        1.0,
                    )

            # Check task limit
            if task_name and task_name in self._task_limiters:
                if not self._task_limiters[task_name].allow_request():
                    raise RateLimitExceededError(
                        f"task:{task_name}",
                        self._task_limiters[task_name].capacity,
                        1.0,
                    )

            # Check sliding window limiters
            if queue_name in self._window_limiters:
                if not self._window_limiters[queue_name].allow_request():
                    raise RateLimitExceededError(
                        f"queue:{queue_name}",
                        self._window_limiters[queue_name].limit,
                        self._window_limiters[queue_name].window_seconds,
                    )

            if task_name and f"task_{task_name}" in self._window_limiters:
                if not self._window_limiters[f"task_{task_name}"].allow_request():
                    raise RateLimitExceededError(
                        f"task:{task_name}",
                        self._window_limiters[f"task_{task_name}"].limit,
                        self._window_limiters[f"task_{task_name}"].window_seconds,
                    )

            return True

    def get_queue_status(self, queue_name: str) -> dict[str, float] | None:
        """
        Get rate limit status for a queue.

        Args:
            queue_name: Name of the queue.

        Returns:
            Dictionary with current tokens/requests and capacity.
        """
        with self._lock:
            if queue_name in self._queue_limiters:
                bucket = self._queue_limiters[queue_name]
                return {
                    "tokens": bucket.get_tokens(),
                    "capacity": bucket.capacity,
                    "rate": bucket.rate,
                }
            elif queue_name in self._window_limiters:
                limiter = self._window_limiters[queue_name]
                return {
                    "requests": limiter.get_request_count(),
                    "limit": limiter.limit,
                    "window": limiter.window_seconds,
                }
            return None

    def get_task_status(self, task_name: str) -> dict[str, float] | None:
        """
        Get rate limit status for a task.

        Args:
            task_name: Name of the task.

        Returns:
            Dictionary with current tokens/requests and capacity.
        """
        with self._lock:
            if task_name in self._task_limiters:
                bucket = self._task_limiters[task_name]
                return {
                    "tokens": bucket.get_tokens(),
                    "capacity": bucket.capacity,
                    "rate": bucket.rate,
                }
            elif f"task_{task_name}" in self._window_limiters:
                limiter = self._window_limiters[f"task_{task_name}"]
                return {
                    "requests": limiter.get_request_count(),
                    "limit": limiter.limit,
                    "window": limiter.window_seconds,
                }
            return None

    def reset(self) -> None:
        """Reset all rate limiters."""
        with self._lock:
            self._queue_limiters.clear()
            self._task_limiters.clear()
            self._window_limiters.clear()

    def __repr__(self) -> str:
        return (
            f"RateLimiter(strategy={self.strategy.value}, "
            f"queues={len(self._queue_limiters)}, tasks={len(self._task_limiters)})"
        )
