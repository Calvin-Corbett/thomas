"""TTL-based cache with lazy and active expiration strategies."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from ._types import CacheConfig, CacheEntry, CacheStats, CacheTier, TTLPolicy

logger = logging.getLogger(__name__)

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Time-to-Live cache with lazy and active expiration."""

    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self._entries: dict[str, CacheEntry[T]] = {}
        self._current_size_bytes = 0
        self._stats = CacheStats()
        self._lock = threading.RLock()
        self._cleanup_thread: threading.Thread | None = None
        self._should_stop = False

        if config.ttl_config.policy in (TTLPolicy.ACTIVE, TTLPolicy.HYBRID):
            self._start_cleanup_thread()

        logger.info("Initialized TTL cache: policy=%s", config.ttl_config.policy.value)

    def get(self, key: str, default: T | None = None) -> T | None:
        """Get a value from the cache (lazy expiration)."""
        with self._lock:
            if key not in self._entries:
                self._stats.misses += 1
                self._stats.operations += 1
                logger.debug("Cache miss for key: %s", key)
                return default

            entry = self._entries[key]

            if entry.is_expired():
                logger.debug("Entry expired for key: %s", key)
                self._current_size_bytes -= entry.size_bytes
                del self._entries[key]
                self._stats.misses += 1
                self._stats.ttl_expirations += 1
                self._stats.operations += 1
                self._stats.size_bytes = self._current_size_bytes
                self._stats.entry_count = len(self._entries)
                return default

            entry.access_count += 1
            entry.last_accessed_at = datetime.utcnow()

            self._stats.hits += 1
            self._stats.operations += 1
            logger.debug("Cache hit for key: %s", key)
            return entry.value

    def put(
        self,
        key: str,
        value: T,
        ttl: timedelta | None = None,
        size_bytes: int = 0,
    ) -> None:
        """Put a value into the cache with TTL."""
        with self._lock:
            if ttl is None:
                ttl = self.config.ttl_config.default_ttl

            if ttl.total_seconds() <= 0:
                raise ValueError("TTL must be positive")

            adjusted_ttl = self._apply_jitter(ttl)

            entry = CacheEntry(
                value=value,
                ttl=adjusted_ttl,
                tier=CacheTier.L1_MEMORY,
                size_bytes=size_bytes,
            )

            if key in self._entries:
                self._current_size_bytes -= self._entries[key].size_bytes

            self._entries[key] = entry
            self._current_size_bytes += size_bytes

            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._entries)
            self._stats.operations += 1
            logger.debug("Put entry for key: %s", key)

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        with self._lock:
            if key not in self._entries:
                return False

            entry = self._entries[key]
            self._current_size_bytes -= entry.size_bytes
            del self._entries[key]

            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._entries)
            self._stats.operations += 1
            logger.debug("Deleted key: %s", key)
            return True

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._entries.clear()
            self._current_size_bytes = 0
            self._stats.size_bytes = 0
            self._stats.entry_count = 0
            logger.info("Cache cleared")

    def contains(self, key: str) -> bool:
        """Check if a key exists and hasn't expired."""
        with self._lock:
            if key not in self._entries:
                return False
            if self._entries[key].is_expired():
                entry = self._entries[key]
                self._current_size_bytes -= entry.size_bytes
                del self._entries[key]
                return False
            return True

    def size(self) -> int:
        """Get the number of entries."""
        with self._lock:
            return len(self._entries)

    def size_bytes(self) -> int:
        """Get the current size in bytes."""
        with self._lock:
            return self._current_size_bytes

    def stats(self) -> CacheStats:
        """Get cache statistics."""
        with self._lock:
            return CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                size_bytes=self._stats.size_bytes,
                entry_count=self._stats.entry_count,
                ttl_expirations=self._stats.ttl_expirations,
                operations=self._stats.operations,
            )

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        with self._lock:
            self._stats = CacheStats()
            logger.info("Cache statistics reset")

    def cleanup_expired(self) -> int:
        """Manually remove all expired entries."""
        with self._lock:
            keys_to_remove = [k for k, e in self._entries.items() if e.is_expired()]

            for key in keys_to_remove:
                entry = self._entries[key]
                self._current_size_bytes -= entry.size_bytes
                del self._entries[key]

            self._stats.ttl_expirations += len(keys_to_remove)
            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._entries)

            if keys_to_remove:
                logger.info("Cleaned up %d expired entries", len(keys_to_remove))

            return len(keys_to_remove)

    def set_policy(self, policy: TTLPolicy) -> None:
        """Change the TTL expiration policy."""
        with self._lock:
            if self.config.ttl_config.policy != policy:
                self.config.ttl_config.policy = policy

                if policy in (TTLPolicy.ACTIVE, TTLPolicy.HYBRID):
                    if self._cleanup_thread is None:
                        self._start_cleanup_thread()
                else:
                    if self._cleanup_thread is not None:
                        self._stop_cleanup_thread()

                logger.info("Changed TTL policy to: %s", policy.value)

    def shutdown(self) -> None:
        """Shutdown the cache and cleanup thread."""
        self._stop_cleanup_thread()
        with self._lock:
            self.clear()
        logger.info("TTL cache shutdown")

    def _apply_jitter(self, ttl: timedelta) -> timedelta:
        """Apply jitter to TTL if enabled."""
        if not self.config.ttl_config.jitter_enabled:
            return ttl

        ttl_seconds = ttl.total_seconds()
        max_jitter_seconds = ttl_seconds * self.config.ttl_config.max_jitter_ratio
        jitter_seconds = random.uniform(0, max_jitter_seconds)

        return timedelta(seconds=ttl_seconds + jitter_seconds)

    def _start_cleanup_thread(self) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is not None:
            return

        self._should_stop = False
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_worker,
            daemon=True,
            name="TTLCache-Cleanup",
        )
        self._cleanup_thread.start()
        logger.info("Started TTL cache cleanup thread")

    def _stop_cleanup_thread(self) -> None:
        """Stop the background cleanup thread."""
        if self._cleanup_thread is None:
            return

        self._should_stop = True
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
        self._cleanup_thread = None
        logger.info("Stopped TTL cache cleanup thread")

    def _cleanup_worker(self) -> None:
        """Background worker that periodically cleans up expired entries."""
        cleanup_interval = self.config.ttl_config.cleanup_interval.total_seconds()

        while not self._should_stop:
            try:
                time.sleep(cleanup_interval)
                if not self._should_stop:
                    removed = self.cleanup_expired()
                    if removed > 0:
                        logger.debug("Active cleanup removed %d entries", removed)
            except Exception as e:
                logger.error("Error in TTL cache cleanup: %s", e)
