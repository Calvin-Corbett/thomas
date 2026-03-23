"""Least Recently Used (LRU) cache implementation with TTL support."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Generic, TypeVar

from ._exceptions import CacheFullError
from ._types import CacheConfig, CacheEntry, CacheStats, CacheTier

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _Node(Generic[T]):
    """Node in the doubly-linked list for LRU ordering."""

    def __init__(self, key: str, entry: CacheEntry[T]) -> None:
        self.key = key
        self.entry = entry
        self.prev: _Node[T] | None = None
        self.next: _Node[T] | None = None


class LRUCache(Generic[T]):
    """Least Recently Used cache with O(1) operations."""

    def __init__(self, config: CacheConfig) -> None:
        self.config = config
        self._map: dict[str, _Node[T]] = {}
        self._head: _Node[T] | None = None
        self._tail: _Node[T] | None = None
        self._current_size_bytes = 0
        self._stats = CacheStats()
        self._lock = threading.RLock()
        logger.info(
            "Initialized LRU cache: max_size=%s bytes, max_entries=%s",
            config.max_size_bytes,
            config.max_entries,
        )

    def get(self, key: str, default: T | None = None) -> T | None:
        """Get a value from the cache and mark as recently used."""
        with self._lock:
            node = self._map.get(key)
            if node is None:
                self._stats.misses += 1
                self._stats.operations += 1
                logger.debug("Cache miss for key: %s", key)
                return default

            if node.entry.is_expired():
                logger.debug("Entry expired for key: %s", key)
                self._delete_node(node)
                self._stats.misses += 1
                self._stats.ttl_expirations += 1
                self._stats.operations += 1
                return default

            self._move_to_head(node)
            node.entry.access_count += 1
            node.entry.last_accessed_at = datetime.utcnow()

            self._stats.hits += 1
            self._stats.operations += 1
            logger.debug("Cache hit for key: %s", key)
            return node.entry.value

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

            if key in self._map:
                old_node = self._map[key]
                self._current_size_bytes -= old_node.entry.size_bytes
                self._delete_node(old_node)

            while (
                self._current_size_bytes + size_bytes > self.config.max_size_bytes
                or len(self._map) >= self.config.max_entries
            ):
                if not self._evict_lru():
                    raise CacheFullError(f"Cannot fit entry of size {size_bytes}")

            node = _Node(key, entry)
            self._map[key] = node
            self._move_to_head(node)
            self._current_size_bytes += size_bytes

            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._map)
            self._stats.operations += 1
            logger.debug("Put entry for key: %s", key)

    def delete(self, key: str) -> bool:
        """Delete a key from the cache."""
        with self._lock:
            node = self._map.get(key)
            if node is None:
                return False
            self._current_size_bytes -= node.entry.size_bytes
            self._delete_node(node)
            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._map)
            self._stats.operations += 1
            logger.debug("Deleted key: %s", key)
            return True

    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._map.clear()
            self._head = None
            self._tail = None
            self._current_size_bytes = 0
            self._stats.size_bytes = 0
            self._stats.entry_count = 0
            logger.info("Cache cleared")

    def contains(self, key: str) -> bool:
        """Check if a key exists and hasn't expired."""
        with self._lock:
            node = self._map.get(key)
            if node is None:
                return False
            if node.entry.is_expired():
                self._delete_node(node)
                return False
            return True

    def size(self) -> int:
        """Get the number of entries."""
        with self._lock:
            return len(self._map)

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
            removed_count = 0
            keys_to_remove = [k for k, n in self._map.items() if n.entry.is_expired()]

            for key in keys_to_remove:
                node = self._map[key]
                self._current_size_bytes -= node.entry.size_bytes
                self._delete_node(node)
                removed_count += 1

            self._stats.ttl_expirations += removed_count
            self._stats.size_bytes = self._current_size_bytes
            self._stats.entry_count = len(self._map)

            if removed_count > 0:
                logger.info("Cleaned up %d expired entries", removed_count)

            return removed_count

    def _move_to_head(self, node: _Node[T]) -> None:
        """Move a node to head (most recently used)."""
        if node is self._head:
            return

        in_list = node.prev is not None or node.next is not None or node is self._tail

        if in_list:
            if node.prev:
                node.prev.next = node.next
            else:
                self._head = node.next

            if node.next:
                node.next.prev = node.prev
            else:
                self._tail = node.prev

        node.prev = None
        node.next = self._head

        if self._head:
            self._head.prev = node
        self._head = node

        if self._tail is None:
            self._tail = node

    def _delete_node(self, node: _Node[T]) -> None:
        """Remove a node from the list."""
        if node.prev:
            node.prev.next = node.next
        else:
            self._head = node.next

        if node.next:
            node.next.prev = node.prev
        else:
            self._tail = node.prev

        del self._map[node.key]

    def _evict_lru(self) -> bool:
        """Evict the least recently used entry."""
        if self._tail is None:
            return False

        node = self._tail
        self._current_size_bytes -= node.entry.size_bytes
        self._delete_node(node)
        self._stats.evictions += 1
        self._stats.size_bytes = self._current_size_bytes
        self._stats.entry_count = len(self._map)
        logger.debug("Evicted LRU entry: %s", node.key)
        return True
