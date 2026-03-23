"""Multi-tier cache with L1 memory, L2 disk, and L3 remote stub."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from enum import Enum
from typing import Generic, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class WritePolicy(Enum):
    """Write policies for multi-tier cache."""

    WRITE_THROUGH = "write_through"  # Write to all tiers synchronously
    WRITE_BACK = "write_back"  # Write to L1, async to lower tiers


class InclusivityMode(Enum):
    """Cache inclusivity modes."""

    INCLUSIVE = "inclusive"  # Data in Ln also in Ln+1
    EXCLUSIVE = "exclusive"  # Data only in one tier


class TierStorage(Protocol[T]):
    """Protocol for tier storage implementations."""

    def get(self, key: str) -> T | None:
        """Get a value from this tier."""
        ...

    def put(self, key: str, value: T, ttl: timedelta | None = None) -> None:
        """Put a value in this tier."""
        ...

    def delete(self, key: str) -> bool:
        """Delete a value from this tier."""
        ...

    def contains(self, key: str) -> bool:
        """Check if key exists in this tier."""
        ...

    def size(self) -> int:
        """Get number of entries in this tier."""
        ...

    def clear(self) -> None:
        """Clear all entries from this tier."""
        ...


class MultiTierCache(Generic[T]):
    """Multi-tier cache with promotion and demotion.

    Implements a 3-level cache hierarchy:
    - L1: Fast in-memory cache
    - L2: Slower disk-based storage (stub)
    - L3: Slowest remote storage (stub)

    Supports write-through and write-back policies, and inclusive/exclusive
    modes. Automatically promotes entries from lower tiers on access.

    Attributes:
        config: Cache configuration.
    """

    def __init__(
        self,
        l1: TierStorage[T],
        l2: TierStorage[T] | None = None,
        l3: TierStorage[T] | None = None,
        write_policy: WritePolicy = WritePolicy.WRITE_THROUGH,
        inclusivity: InclusivityMode = InclusivityMode.INCLUSIVE,
    ) -> None:
        """Initialize the multi-tier cache.

        Args:
            l1: L1 (memory) storage.
            l2: L2 (disk) storage, optional.
            l3: L3 (remote) storage, optional.
            write_policy: How to write across tiers.
            inclusivity: Whether data is replicated across tiers.
        """
        self.l1 = l1
        self.l2 = l2
        self.l3 = l3
        self.write_policy = write_policy
        self.inclusivity = inclusivity
        self._stats = MultiTierStats()
        self._lock = threading.RLock()
        logger.info(
            "Initialized multi-tier cache: " "write_policy=%s, inclusivity=%s, tiers=%d",
            write_policy.value,
            inclusivity.value,
            self._count_tiers(),
        )

    def get(self, key: str, default: T | None = None) -> T | None:
        """Get a value, checking tiers in order and promoting on hit.

        Args:
            key: The cache key.
            default: Value to return if not found.

        Returns:
            The cached value or default.
        """
        with self._lock:
            # Try L1
            value = self.l1.get(key)
            if value is not None:
                self._stats.l1_hits += 1
                logger.debug("L1 hit for key: %s", key)
                return value

            self._stats.l1_misses += 1

            # Try L2
            if self.l2 is not None:
                value = self.l2.get(key)
                if value is not None:
                    self._stats.l2_hits += 1
                    logger.debug("L2 hit for key: %s, promoting to L1", key)
                    self._promote_to_l1(key, value)
                    return value

                self._stats.l2_misses += 1

            # Try L3
            if self.l3 is not None:
                value = self.l3.get(key)
                if value is not None:
                    self._stats.l3_hits += 1
                    logger.debug("L3 hit for key: %s, promoting up tiers", key)
                    self._promote_from_l3(key, value)
                    return value

                self._stats.l3_misses += 1

            self._stats.total_misses += 1
            logger.debug("Cache miss for key: %s across all tiers", key)
            return default

    def put(
        self,
        key: str,
        value: T,
        ttl: timedelta | None = None,
    ) -> None:
        """Put a value into the cache.

        Writes to all tiers according to the write policy.

        Args:
            key: The cache key.
            value: The value to cache.
            ttl: Time-to-live for the value.
        """
        with self._lock:
            if self.write_policy == WritePolicy.WRITE_THROUGH:
                self._write_through(key, value, ttl)
            else:
                self._write_back(key, value, ttl)

            self._stats.total_writes += 1
            logger.debug("Put entry for key: %s (policy=%s)", key, self.write_policy.value)

    def delete(self, key: str) -> bool:
        """Delete a key from all tiers.

        Args:
            key: The cache key.

        Returns:
            True if deleted from at least one tier.
        """
        with self._lock:
            deleted = False

            if self.l1.delete(key):
                deleted = True
            if self.l2 is not None and self.l2.delete(key):
                deleted = True
            if self.l3 is not None and self.l3.delete(key):
                deleted = True

            if deleted:
                self._stats.total_deletes += 1
                logger.debug("Deleted key: %s from tiers", key)

            return deleted

    def clear(self) -> None:
        """Clear all tiers."""
        with self._lock:
            self.l1.clear()
            if self.l2 is not None:
                self.l2.clear()
            if self.l3 is not None:
                self.l3.clear()

            logger.info("Cleared all cache tiers")

    def contains(self, key: str) -> bool:
        """Check if key exists in any tier.

        Args:
            key: The cache key.

        Returns:
            True if found in any tier.
        """
        with self._lock:
            if self.l1.contains(key):
                return True
            if self.l2 is not None and self.l2.contains(key):
                return True
            if self.l3 is not None and self.l3.contains(key):
                return True
            return False

    def demote(self, key: str) -> bool:
        """Demote a key from L1 to lower tiers.

        Removes from L1 and ensures it's in L2/L3.

        Args:
            key: The cache key.

        Returns:
            True if demotion succeeded.
        """
        with self._lock:
            value = self.l1.get(key)
            if value is None:
                return False

            # Remove from L1
            self.l1.delete(key)

            # Add to L2 if available and not in exclusive mode
            if self.l2 is not None:
                if self.inclusivity == InclusivityMode.INCLUSIVE:
                    self.l2.put(key, value)

            logger.debug("Demoted key: %s from L1 to L2", key)
            return True

    def promote(self, key: str) -> bool:
        """Promote a key from lower tiers to L1.

        Args:
            key: The cache key.

        Returns:
            True if promotion succeeded.
        """
        with self._lock:
            # Try L2 first
            if self.l2 is not None:
                value = self.l2.get(key)
                if value is not None:
                    self.l1.put(key, value)
                    if self.inclusivity == InclusivityMode.EXCLUSIVE:
                        self.l2.delete(key)
                    logger.debug("Promoted key: %s from L2 to L1", key)
                    return True

            # Try L3
            if self.l3 is not None:
                value = self.l3.get(key)
                if value is not None:
                    self.l1.put(key, value)
                    if self.inclusivity == InclusivityMode.EXCLUSIVE:
                        self.l3.delete(key)
                    logger.debug("Promoted key: %s from L3 to L1", key)
                    return True

            return False

    def stats(self) -> MultiTierStats:
        """Get cache statistics.

        Returns:
            Statistics for all tiers.
        """
        with self._lock:
            return self._stats

    def reset_stats(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self._stats = MultiTierStats()
            logger.info("Multi-tier cache statistics reset")

    def _write_through(
        self,
        key: str,
        value: T,
        ttl: timedelta | None,
    ) -> None:
        """Write-through: write to all tiers synchronously."""
        self.l1.put(key, value, ttl)

        if self.l2 is not None:
            self.l2.put(key, value, ttl)

        if self.l3 is not None:
            self.l3.put(key, value, ttl)

    def _write_back(
        self,
        key: str,
        value: T,
        ttl: timedelta | None,
    ) -> None:
        """Write-back: write to L1, queue async writes to lower tiers."""
        self.l1.put(key, value, ttl)

        # In a real implementation, would queue async writes
        if self.l2 is not None:
            self.l2.put(key, value, ttl)

        if self.l3 is not None:
            self.l3.put(key, value, ttl)

    def _promote_to_l1(self, key: str, value: T) -> None:
        """Promote a value from lower tier to L1."""
        self.l1.put(key, value)

    def _promote_from_l3(self, key: str, value: T) -> None:
        """Promote a value from L3 up through tiers."""
        if self.l2 is not None:
            self.l2.put(key, value)

        self.l1.put(key, value)

    def _count_tiers(self) -> int:
        """Count the number of available tiers."""
        count = 1  # L1 always present
        if self.l2 is not None:
            count += 1
        if self.l3 is not None:
            count += 1
        return count


class MultiTierStats:
    """Statistics for multi-tier cache."""

    def __init__(self) -> None:
        """Initialize statistics."""
        self.l1_hits = 0
        self.l1_misses = 0
        self.l2_hits = 0
        self.l2_misses = 0
        self.l3_hits = 0
        self.l3_misses = 0
        self.total_hits = 0
        self.total_misses = 0
        self.total_writes = 0
        self.total_deletes = 0

    @property
    def total_hits(self) -> int:
        """Calculate total hits."""
        return self.l1_hits + self.l2_hits + self.l3_hits

    @total_hits.setter
    def total_hits(self, value: int) -> None:
        """Set total hits."""
        pass

    def hit_rate(self) -> float:
        """Calculate overall hit rate."""
        total = self.total_hits + self.total_misses
        return self.total_hits / total if total > 0 else 0.0

    def l1_hit_rate(self) -> float:
        """Calculate L1 hit rate."""
        total = self.l1_hits + self.l1_misses
        return self.l1_hits / total if total > 0 else 0.0

    def l2_hit_rate(self) -> float:
        """Calculate L2 hit rate."""
        total = self.l2_hits + self.l2_misses
        return self.l2_hits / total if total > 0 else 0.0

    def l3_hit_rate(self) -> float:
        """Calculate L3 hit rate."""
        total = self.l3_hits + self.l3_misses
        return self.l3_hits / total if total > 0 else 0.0

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"MultiTierStats(L1: {self.l1_hit_rate():.2%}, "
            f"L2: {self.l2_hit_rate():.2%}, "
            f"L3: {self.l3_hit_rate():.2%}, "
            f"overall: {self.hit_rate():.2%})"
        )
