"""Least Frequently Used (LFU) cache implementation with aging."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from ._exceptions import CacheFullError
from ._types import CacheConfig, CacheEntry, CacheStats, CacheTier

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LFUCache(Generic[T]):
    """Least Frequently Used cache with frequency buckets."""

    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self._entries: dict[str, CacheEntry[T]] = {}
        self._frequencies: dict[str, int] = {}
        self._frequency_buckets: dict[int, set[str]] = {}
        self._min_frequency = 0
        self._current_size_bytes = 0
        self._stats = CacheStats()
        self._lock = threading.RLock()
        logger.info("Initialized LFU cache: max_size=%s, max_entries=%s", config.max_size_bytes, config.max_entries)

    def get(self, key: str, default: T | None = None) -> T | None:
        """Get a value and increment its frequency."""
        with self._lock:
            if key not in self._entries:
                self._stats.misses += 1
                self._stats.operations += 1
                logger.debug("Cache miss for key: %s", key)
                return default

            entry = self._entries[key]
            if entry.is_expired():
                logger.debug("Entry expired for key: %s", key)
                self._remove_entry(key)
                self._stats.misses += 1
                self._stats.ttl_expirations += 1
                self._stats.operations += 1
                return default

            self._increment_frequency(key)
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
        """Put a value into the cache."""
        with self._lock:
            if ttl is None:
                ttl = self.config.ttl_config.default_ttl

            entry = CacheEntry(
                value=value,
                ttl=ttl,
                tier=CacheTier.L1_MEMORY,
                size_bytes=size_bytes,
            )

            if key in self._entries:
                old_entry = self._entries[key]
                self._current_size_bytes -= old_entry.size_bytes
                self._entries[key] = entry
                self._frequencies[key] = 1
                self._current_size_bytes += size_bytes
            else:
                while (
                    self._current_size_bytes + size_bytes > self.config.max_size_bytes
                    or len(self._entries) >= self.config.max_entries
                ):
                    if not self._evict_lfu():
                        raise CacheFullError("Cannot fit entry")

                self._entries[key] = entry
                self._frequencies[key] = 1
                self._current_size_bytes += size_bytes

                if 1 not in self._frequency_buckets:
                    self._frequency_buckets[1] = set()
                self._frequency_buckets[1].add(key)
                self._min_frequency = 1

            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._entries)
            self._stats.operations += 1
            logger.debug("Put entry for key: %s", key)

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        with self._lock:
            if key not in self._entries:
                return False
            self._remove_entry(key)
            return True

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._entries.clear()
            self._frequencies.clear()
            self._frequency_buckets.clear()
            self._min_frequency = 0
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
                self._remove_entry(key)
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
        """Remove all expired entries."""
        with self._lock:
            keys_to_remove = [k for k, e in self._entries.items() if e.is_expired()]
            for key in keys_to_remove:
                self._remove_entry(key)

            self._stats.ttl_expirations += len(keys_to_remove)
            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._entries)

            if keys_to_remove:
                logger.info("Cleaned up %d expired entries", len(keys_to_remove))

            return len(keys_to_remove)

    def age_frequencies(self, factor: float = 0.5) -> None:
        """Apply aging to reduce frequency pollution."""
        with self._lock:
            if factor <= 0 or factor > 1:
                raise ValueError("Aging factor must be between 0 and 1")

            new_frequencies: dict[str, int] = {}
            new_buckets: dict[int, set[str]] = {}

            for key, freq in self._frequencies.items():
                new_freq = max(1, int(freq * factor))
                new_frequencies[key] = new_freq

                if new_freq not in new_buckets:
                    new_buckets[new_freq] = set()
                new_buckets[new_freq].add(key)

            self._frequencies = new_frequencies
            self._frequency_buckets = new_buckets
            self._min_frequency = min(self._frequencies.values()) if self._frequencies else 0

            logger.info("Applied frequency aging (factor=%.2f)", factor)

    def _increment_frequency(self, key: str) -> None:
        """Increment the frequency of a key."""
        old_freq = self._frequencies[key]
        new_freq = old_freq + 1

        if key in self._frequency_buckets.get(old_freq, set()):
            self._frequency_buckets[old_freq].discard(key)
            if not self._frequency_buckets[old_freq]:
                del self._frequency_buckets[old_freq]

        if new_freq not in self._frequency_buckets:
            self._frequency_buckets[new_freq] = set()
        self._frequency_buckets[new_freq].add(key)

        self._frequencies[key] = new_freq

    def _remove_entry(self, key: str) -> None:
        """Remove an entry and update tracking."""
        if key not in self._entries:
            return

        entry = self._entries[key]
        freq = self._frequencies[key]

        self._current_size_bytes -= entry.size_bytes
        del self._entries[key]
        del self._frequencies[key]

        if key in self._frequency_buckets.get(freq, set()):
            self._frequency_buckets[freq].discard(key)
            if not self._frequency_buckets[freq]:
                del self._frequency_buckets[freq]

    def _evict_lfu(self) -> bool:
        """Evict the least frequently used entry."""
        if not self._entries:
            return False

        if self._min_frequency not in self._frequency_buckets:
            self._min_frequency = min(self._frequency_buckets.keys())

        min_bucket = self._frequency_buckets[self._min_frequency]
        if not min_bucket:
            return False

        key_to_evict = next(iter(min_bucket))
        entry = self._entries[key_to_evict]

        self._remove_entry(key_to_evict)
        self._stats.evictions += 1
        self._stats.size_bytes = self._current_size_bytes
        self._stats.entry_count = len(self._entries)

        logger.debug("Evicted LFU entry: %s", key_to_evict)
        return True
