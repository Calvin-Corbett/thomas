"""Rate limiting middleware using token bucket algorithm.

Provides configurable per-client rate limiting based on IP address or API token.
Can be tuned via thomas.toml [server.rate_limit] section or environment variables.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import math
import time

from aiohttp import web

log = logging.getLogger(__name__)


class RateLimitBucket:
    """Token bucket for rate limiting a single client."""

    def __init__(self, capacity: int, refill_rate: float):
        """Initialize bucket.

        Args:
            capacity: Maximum requests allowed per window
            refill_rate: Tokens refilled per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()

    def consume(self, amount: float = 1.0) -> tuple[bool, int]:
        """Try to consume tokens from the bucket.

        Returns:
            (allowed, retry_after_seconds) tuple
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0

        # Calculate retry_after: how long until we have enough tokens
        deficit = amount - self.tokens
        retry_after = math.ceil(deficit / self.refill_rate)
        return False, max(1, retry_after)


class RateLimitStore:
    """Thread-safe in-memory store of rate limit buckets per client."""

    def __init__(self, window_seconds: int = 60, cleanup_interval_seconds: float = 30.0):
        """Initialize the store.

        Args:
            window_seconds: Rate limit window size (affects default rates)
            cleanup_interval_seconds: How often to cleanup stale buckets
        """
        self._buckets: dict[str, RateLimitBucket] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = cleanup_interval_seconds
        self._window_seconds = window_seconds
        self._stale_threshold = window_seconds * 2  # buckets not used for 2 windows are stale

    async def check_rate_limit(
        self,
        client_key: str,
        max_requests: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        """Check and consume from rate limit bucket for a client.

        Args:
            client_key: Unique identifier for the client (e.g., "ip:127.0.0.1")
            max_requests: Max requests allowed per window
            window_seconds: Window duration in seconds

        Returns:
            (allowed, retry_after_seconds) tuple
        """
        refill_rate = float(max_requests) / float(window_seconds)

        async with self._lock:
            bucket = self._buckets.get(client_key)
            if bucket is None or bucket.capacity != max_requests:
                bucket = RateLimitBucket(max_requests, refill_rate)
                self._buckets[client_key] = bucket

            allowed, retry_after = bucket.consume(1.0)

            # Opportunistic cleanup
            now = time.monotonic()
            if (now - self._last_cleanup) >= self._cleanup_interval:
                await self._cleanup_stale_buckets(now)

            return allowed, retry_after

    async def _cleanup_stale_buckets(self, now: float) -> None:
        """Remove buckets that haven't been used recently."""
        stale_keys = [k for k, b in self._buckets.items() if (now - b.last_refill) > self._stale_threshold]
        for key in stale_keys:
            del self._buckets[key]
        if stale_keys:
            log.debug(f"Rate limit cleanup: removed {len(stale_keys)} stale buckets")
        self._last_cleanup = now


def create_rate_limit_middleware(
    store: RateLimitStore,
    chat_limit: int = 60,
    general_limit: int = 120,
    window_seconds: int = 60,
    skip_loopback: bool = True,
) -> web.middleware:
    """Create a rate limit middleware factory.

    Args:
        store: RateLimitStore instance for bucket management
        chat_limit: Max requests/window for /api/chat endpoints
        general_limit: Max requests/window for other /api endpoints
        window_seconds: Window size in seconds
        skip_loopback: If True, skip rate limiting for 127.0.0.1, ::1

    Returns:
        aiohttp middleware function
    """

    def _extract_client_key(request: web.Request) -> str:
        """Extract a unique identifier for the client."""
        # First check for API token
        auth = str(request.headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            # Bucket key only (not auth/storage); flag as non-security hashing.
            digest = hashlib.sha256(token.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
            return f"token:{digest}"

        token = str(request.headers.get("X-Api-Token") or "").strip()
        if token:
            # Bucket key only (not auth/storage); flag as non-security hashing.
            digest = hashlib.sha256(token.encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
            return f"token:{digest}"

        # Fall back to IP address
        remote = str(request.remote or "").strip() or "unknown"
        return f"ip:{remote}"

    def _is_loopback(request: web.Request) -> bool:
        """Check if request is from localhost."""
        remote = request.remote or ""
        try:
            ip = ipaddress.ip_address(remote)
            return ip.is_loopback
        except ValueError:
            return False

    def _get_limit_for_path(path: str) -> int:
        """Determine rate limit for a given path."""
        if path.startswith("/api/chat"):
            return chat_limit
        return general_limit

    @web.middleware
    async def rate_limit_middleware(request: web.Request, handler):  # type: ignore[no-untyped-def]
        """Rate limit middleware using token bucket algorithm."""
        # Only apply to API endpoints
        if not request.path.startswith("/api/"):
            return await handler(request)

        # Skip loopback by default (local development)
        if skip_loopback and _is_loopback(request):
            return await handler(request)

        client_key = _extract_client_key(request)
        limit = _get_limit_for_path(request.path)

        allowed, retry_after = await store.check_rate_limit(
            client_key,
            max_requests=limit,
            window_seconds=window_seconds,
        )

        if not allowed:
            log.warning(
                f"Rate limit exceeded for {client_key} on {request.method} {request.path} "
                f"(limit={limit}/{window_seconds}s, retry_after={retry_after}s)"
            )
            raise web.HTTPTooManyRequests(
                text="rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        return await handler(request)

    return rate_limit_middleware
