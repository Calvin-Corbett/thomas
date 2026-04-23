"""Type definitions and data structures for the caching module."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Generic, TypeVar

T = TypeVar("T")


class EvictionPolicy(Enum):
    """Cache eviction policies."""

    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    FIFO = "fifo"  # First In, First Out
    RANDOM = "random"  # Random eviction


class CacheTier(Enum):
    """Cache tier levels in a multi-tier hierarchy."""

    L1_MEMORY = "l1_memory"
    L2_DISK = "l2_disk"
    L3_REMOTE = "l3_remote"


class TTLPolicy(Enum):
    """Time-to-live expiration policies."""

    LAZY = "lazy"  # Expire on access
    ACTIVE = "active"  # Background expiration
    HYBRID = "hybrid"  # Both lazy and active


@dataclass
class CacheEntry(Generic[T]):
    """Represents a single cache entry with metadata.

    Attributes:
        value: The cached value.
        created_at: Timestamp when entry was created.
        last_accessed_at: Timestamp of last access.
        access_count: Number of times accessed.
        ttl: Time-to-live duration, None for no expiration.
        tier: Which tier this entry resides in.
        size_bytes: Estimated size in bytes.
    """

    value: T
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed_at: datetime = field(default_factory=datetime.utcnow)
    access_count: int = field(default=0)
    ttl: timedelta | None = None
    tier: CacheTier = CacheTier.L1_MEMORY
    size_bytes: int = field(default=0)

    def is_expired(self) -> bool:
        """Check if entry has exceeded its TTL.

        Returns:
            True if the entry has expired, False otherwise.
        """
        if self.ttl is None:
            return False
        expiry_time = self.created_at + self.ttl
        return datetime.utcnow() > expiry_time

    def time_until_expiry(self) -> timedelta | None:
        """Calculate time remaining until expiry.

        Returns:
            Timedelta until expiry, or None if no TTL.
        """
        if self.ttl is None:
            return None
        expiry_time = self.created_at + self.ttl
        remaining = expiry_time - datetime.utcnow()
        return remaining if remaining.total_seconds() > 0 else None


@dataclass
class CacheStats:
    """Statistics about cache performance.

    Attributes:
        hits: Number of cache hits.
        misses: Number of cache misses.
        evictions: Number of evictions.
        size_bytes: Current size in bytes.
        entry_count: Number of entries in cache.
        ttl_expirations: Number of entries expired by TTL.
        operations: Total operations performed.
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size_bytes: int = 0
    entry_count: int = 0
    ttl_expirations: int = 0
    operations: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate as a percentage.

        Returns:
            Hit rate between 0.0 and 1.0, or 0.0 if no operations.
        """
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def miss_rate(self) -> float:
        """Calculate miss rate as a percentage.

        Returns:
            Miss rate between 0.0 and 1.0, or 0.0 if no operations.
        """
        return 1.0 - self.hit_rate


@dataclass
class TTLConfig:
    """Configuration for TTL-based expiration.

    Attributes:
        policy: The TTL expiration policy to use.
        default_ttl: Default TTL for new entries.
        cleanup_interval: How often to run active expiration cleanup.
        jitter_enabled: Whether to add jitter to prevent thundering herd.
        max_jitter_ratio: Maximum jitter as ratio of TTL (0.0-1.0).
    """

    policy: TTLPolicy = TTLPolicy.HYBRID
    default_ttl: timedelta = field(default_factory=lambda: timedelta(hours=1))
    cleanup_interval: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    jitter_enabled: bool = True
    max_jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if not (0.0 <= self.max_jitter_ratio <= 1.0):
            raise ValueError("max_jitter_ratio must be between 0.0 and 1.0")
        if self.cleanup_interval.total_seconds() <= 0:
            raise ValueError("cleanup_interval must be positive")


@dataclass
class CacheConfig:
    """Complete cache configuration.

    Attributes:
        max_size_bytes: Maximum cache size in bytes.
        max_entries: Maximum number of entries.
        eviction_policy: Which eviction policy to use.
        ttl_config: TTL configuration.
        enable_stats: Whether to collect statistics.
        enable_compression: Whether to compress values.
        compression_format: Format for compression (e.g., 'zlib', 'lz4').
        enable_warming: Whether to enable cache warming.
        warming_interval: How often to warm cache.
    """

    max_size_bytes: int = 1024 * 1024  # 1MB default
    max_entries: int = 10000
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    ttl_config: TTLConfig = field(default_factory=TTLConfig)
    enable_stats: bool = True
    enable_compression: bool = False
    compression_format: str = "zlib"
    enable_warming: bool = False
    warming_interval: timedelta = field(default_factory=lambda: timedelta(minutes=10))

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        if self.max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if self.compression_format not in ("zlib", "lz4", "none"):
            raise ValueError(f"compression_format must be 'zlib', 'lz4', or 'none', " f"got {self.compression_format}")
