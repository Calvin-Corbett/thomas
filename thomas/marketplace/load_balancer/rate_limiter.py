"""
Rate limiting implementation.

Supports token bucket, sliding window counter, fixed window, and leaky bucket
algorithms for rate limiting at client, backend, or global level.
"""

import threading
import time

from thomas.marketplace.load_balancer._types import RequestContext


class TokenBucket:
    """Token bucket rate limiter."""

    def __init__(self, capacity: int, refill_rate: float) -> None:
        """
        Initialize token bucket.

        Args:
            capacity: Maximum number of tokens in the bucket.
            refill_rate: Tokens added per second.
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def try_consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume (default 1).

        Returns:
            True if tokens were available and consumed, False otherwise.
        """
        with self._lock:
            self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
        self.last_refill = now

    def get_available_tokens(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self.tokens


class SlidingWindowCounter:
    """Sliding window counter rate limiter."""

    def __init__(self, limit: int, window_size: int) -> None:
        """
        Initialize sliding window counter.

        Args:
            limit: Maximum requests per window.
            window_size: Window size in seconds.
        """
        self.limit = limit
        self.window_size = window_size
        self.requests: list = []
        self._lock = threading.Lock()

    def try_consume(self) -> bool:
        """
        Try to consume one request quota.

        Returns:
            True if within limit, False if quota exceeded.
        """
        with self._lock:
            now = time.time()
            cutoff = now - self.window_size

            # Remove old requests outside window
            self.requests = [req_time for req_time in self.requests if req_time > cutoff]

            if len(self.requests) < self.limit:
                self.requests.append(now)
                return True

            return False


class FixedWindowCounter:
    """Fixed window counter rate limiter."""

    def __init__(self, limit: int, window_size: int) -> None:
        """
        Initialize fixed window counter.

        Args:
            limit: Maximum requests per window.
            window_size: Window size in seconds.
        """
        self.limit = limit
        self.window_size = window_size
        self.requests_in_window = 0
        self.window_start = time.time()
        self._lock = threading.Lock()

    def try_consume(self) -> bool:
        """
        Try to consume one request quota.

        Returns:
            True if within limit, False if quota exceeded.
        """
        with self._lock:
            now = time.time()

            # Check if window has expired
            if now - self.window_start >= self.window_size:
                self.window_start = now
                self.requests_in_window = 0

            if self.requests_in_window < self.limit:
                self.requests_in_window += 1
                return True

            return False


class LeakyBucket:
    """Leaky bucket rate limiter."""

    def __init__(self, capacity: int, leak_rate: float) -> None:
        """
        Initialize leaky bucket.

        Args:
            capacity: Maximum bucket capacity.
            leak_rate: Requests processed per second.
        """
        self.capacity = capacity
        self.leak_rate = leak_rate
        self.water_level = 0.0
        self.last_leak = time.time()
        self._lock = threading.Lock()

    def try_consume(self) -> bool:
        """
        Try to add water to the bucket.

        Returns:
            True if water was added, False if bucket is full.
        """
        with self._lock:
            now = time.time()
            elapsed = now - self.last_leak

            # Leak water
            self.water_level = max(0, self.water_level - (elapsed * self.leak_rate))
            self.last_leak = now

            # Try to add water
            if self.water_level < self.capacity:
                self.water_level += 1
                return True

            return False


class RateLimiter:
    """
    Rate limiting system.

    Supports rate limiting by client IP, API key, backend, or globally.
    Uses configurable algorithms (token bucket, sliding window, etc).
    """

    def __init__(
        self,
        algorithm: str = "token_bucket",
        global_limit: int = 10000,
        window_size: int = 60,
    ) -> None:
        """
        Initialize rate limiter.

        Args:
            algorithm: Algorithm to use ('token_bucket', 'sliding_window', 'fixed_window', 'leaky_bucket').
            global_limit: Global limit (requests per window).
            window_size: Window size in seconds.
        """
        self.algorithm = algorithm
        self.global_limit = global_limit
        self.window_size = window_size

        # Per-client limiters
        self._client_limiters: dict[str, object] = {}
        # Per-backend limiters
        self._backend_limiters: dict[str, object] = {}
        # Global limiter
        self._global_limiter: object | None = None
        self._lock = threading.Lock()

        self._init_global_limiter()

    def _init_global_limiter(self) -> None:
        """Initialize the global rate limiter."""
        if self.algorithm == "token_bucket":
            # Calculate refill rate: global_limit tokens per window_size seconds
            refill_rate = self.global_limit / self.window_size
            self._global_limiter = TokenBucket(self.global_limit, refill_rate)
        elif self.algorithm == "sliding_window":
            self._global_limiter = SlidingWindowCounter(self.global_limit, self.window_size)
        elif self.algorithm == "fixed_window":
            self._global_limiter = FixedWindowCounter(self.global_limit, self.window_size)
        elif self.algorithm == "leaky_bucket":
            leak_rate = self.global_limit / self.window_size
            self._global_limiter = LeakyBucket(self.global_limit, leak_rate)

    def _get_or_create_limiter(
        self,
        key: str,
        limit: int,
        limiter_dict: dict,
    ) -> object:
        """Get or create a rate limiter for a key."""
        if key not in limiter_dict:
            if self.algorithm == "token_bucket":
                refill_rate = limit / self.window_size
                limiter_dict[key] = TokenBucket(limit, refill_rate)
            elif self.algorithm == "sliding_window":
                limiter_dict[key] = SlidingWindowCounter(limit, self.window_size)
            elif self.algorithm == "fixed_window":
                limiter_dict[key] = FixedWindowCounter(limit, self.window_size)
            elif self.algorithm == "leaky_bucket":
                leak_rate = limit / self.window_size
                limiter_dict[key] = LeakyBucket(limit, leak_rate)

        return limiter_dict[key]

    def is_allowed(
        self,
        context: RequestContext,
        client_limit: int | None = None,
        backend_id: str | None = None,
        backend_limit: int | None = None,
    ) -> tuple[bool, dict[str, any]]:
        """
        Check if a request is allowed by rate limits.

        Args:
            context: Request context.
            client_limit: Per-client limit (requests per window).
            backend_id: ID of the target backend (for per-backend limiting).
            backend_limit: Per-backend limit (requests per window).

        Returns:
            Tuple of (allowed: bool, headers: dict with rate limit info).
        """
        headers = {}

        # Check global limit
        if self._global_limiter:
            if not self._get_limiter_allow(self._global_limiter):
                headers = self._get_rate_limit_headers(
                    limit=self.global_limit,
                    remaining=0,
                    window=self.window_size,
                )
                return False, headers

        # Check per-client limit
        if client_limit:
            with self._lock:
                limiter = self._get_or_create_limiter(
                    context.client_ip,
                    client_limit,
                    self._client_limiters,
                )

            if not self._get_limiter_allow(limiter):
                headers = self._get_rate_limit_headers(
                    limit=client_limit,
                    remaining=0,
                    window=self.window_size,
                )
                return False, headers

        # Check per-backend limit
        if backend_id and backend_limit:
            with self._lock:
                limiter = self._get_or_create_limiter(
                    backend_id,
                    backend_limit,
                    self._backend_limiters,
                )

            if not self._get_limiter_allow(limiter):
                headers = self._get_rate_limit_headers(
                    limit=backend_limit,
                    remaining=0,
                    window=self.window_size,
                )
                return False, headers

        # Request allowed
        headers = self._get_rate_limit_headers(
            limit=client_limit or self.global_limit,
            remaining=self._get_remaining(self._global_limiter),
            window=self.window_size,
        )
        return True, headers

    def _get_limiter_allow(self, limiter: object) -> bool:
        """Check if a limiter allows the request."""
        if (
            isinstance(limiter, TokenBucket)
            or isinstance(limiter, SlidingWindowCounter)
            or isinstance(limiter, FixedWindowCounter)
            or isinstance(limiter, LeakyBucket)
        ):
            return limiter.try_consume()
        return True

    def _get_remaining(self, limiter: object) -> int:
        """Get remaining quota from a limiter."""
        if isinstance(limiter, TokenBucket):
            return max(0, int(limiter.get_available_tokens()))
        elif isinstance(limiter, SlidingWindowCounter):
            return max(0, limiter.limit - len(limiter.requests))
        elif isinstance(limiter, FixedWindowCounter):
            return max(0, limiter.limit - limiter.requests_in_window)
        elif isinstance(limiter, LeakyBucket):
            return max(0, int(limiter.capacity - limiter.water_level))
        return 0

    def _get_rate_limit_headers(
        self,
        limit: int,
        remaining: int,
        window: int,
    ) -> dict[str, str]:
        """
        Generate rate limit headers for response.

        Args:
            limit: Request limit.
            remaining: Remaining requests.
            window: Window size in seconds.

        Returns:
            Dict with rate limit headers.
        """
        reset_time = int(time.time()) + window

        return {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_time),
        }

    def reset_client(self, client_ip: str) -> None:
        """
        Reset rate limit for a client.

        Args:
            client_ip: Client IP address.
        """
        with self._lock:
            self._client_limiters.pop(client_ip, None)

    def reset_backend(self, backend_id: str) -> None:
        """
        Reset rate limit for a backend.

        Args:
            backend_id: Backend ID.
        """
        with self._lock:
            self._backend_limiters.pop(backend_id, None)

    def reset_all(self) -> None:
        """Reset all rate limiters."""
        with self._lock:
            self._client_limiters.clear()
            self._backend_limiters.clear()
            self._init_global_limiter()

    def get_stats(self) -> dict:
        """
        Get rate limiter statistics.

        Returns:
            Dict with statistics.
        """
        with self._lock:
            return {
                "algorithm": self.algorithm,
                "global_limit": self.global_limit,
                "window_size": self.window_size,
                "active_clients": len(self._client_limiters),
                "active_backends": len(self._backend_limiters),
            }
