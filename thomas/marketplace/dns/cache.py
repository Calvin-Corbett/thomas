"""
DNS cache with TTL expiration, negative caching, LRU eviction, and statistics.
"""

import json
import time
from collections import OrderedDict
from typing import Any

from thomas.marketplace.dns._types import RecordType, ResourceRecord


class CacheEntry:
    """Single cache entry with TTL expiration."""

    def __init__(self, records: list[ResourceRecord], is_negative: bool = False) -> None:
        """Initialize cache entry.

        Args:
            records: List of resource records
            is_negative: Whether this is a negative cache entry (NXDOMAIN)
        """
        self.records = records
        self.is_negative = is_negative
        self.timestamp = time.time()
        self.ttl = self._calculate_ttl(records)
        self.access_count = 0
        self.last_accessed = time.time()

    def _calculate_ttl(self, records: list[ResourceRecord]) -> int:
        """Calculate entry TTL as minimum of record TTLs.

        Args:
            records: List of records

        Returns:
            TTL in seconds
        """
        if not records:
            return 300  # Default 5 minutes for negative cache
        return min(r.ttl for r in records)

    def is_expired(self) -> bool:
        """Check if entry has expired.

        Returns:
            True if entry has exceeded TTL
        """
        return time.time() - self.timestamp > self.ttl

    def access(self) -> None:
        """Record access for LRU tracking."""
        self.access_count += 1
        self.last_accessed = time.time()


class DNSCache:
    """DNS response cache with TTL expiration, negative caching, and LRU eviction."""

    def __init__(self, max_size: int = 10 * 1024 * 1024) -> None:
        """Initialize cache.

        Args:
            max_size: Maximum cache size in bytes
        """
        self.max_size = max_size
        self.current_size = 0
        self.cache: dict[tuple[str, RecordType], CacheEntry] = OrderedDict()

        # Statistics
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.negative_hits = 0

    def get(self, name: str, rtype: RecordType) -> list[ResourceRecord] | None:
        """Get records from cache.

        Args:
            name: Domain name (lowercase)
            rtype: Record type

        Returns:
            List of records or None if not cached/expired
        """
        key = (name.lower(), rtype)

        if key not in self.cache:
            self.misses += 1
            return None

        entry = self.cache[key]

        if entry.is_expired():
            self._remove_entry(key)
            self.misses += 1
            return None

        entry.access()

        if entry.is_negative:
            self.negative_hits += 1
            return None

        self.hits += 1
        return entry.records

    def put(
        self,
        name: str,
        rtype: RecordType,
        records: list[ResourceRecord],
        is_negative: bool = False,
    ) -> None:
        """Add records to cache.

        Args:
            name: Domain name (lowercase)
            rtype: Record type
            records: List of resource records
            is_negative: Whether this is a negative cache (NXDOMAIN)
        """
        key = (name.lower(), rtype)

        # Remove old entry if exists
        if key in self.cache:
            old_size = self._estimate_entry_size(self.cache[key])
            self.current_size -= old_size
            del self.cache[key]

        # Create new entry
        entry = CacheEntry(records, is_negative)
        new_size = self._estimate_entry_size(entry)

        # Evict if necessary
        while self.current_size + new_size > self.max_size and self.cache:
            self._evict_lru()

        # Add to cache
        self.cache[key] = entry
        self.current_size += new_size

    def delete(self, name: str, rtype: RecordType) -> bool:
        """Remove specific cache entry.

        Args:
            name: Domain name
            rtype: Record type

        Returns:
            True if entry was removed
        """
        key = (name.lower(), rtype)
        if key in self.cache:
            size = self._estimate_entry_size(self.cache[key])
            self.current_size -= size
            del self.cache[key]
            return True
        return False

    def invalidate(self, name: str) -> int:
        """Invalidate all cache entries for a name and subdomains.

        Args:
            name: Domain name (and subdomains)

        Returns:
            Number of entries invalidated
        """
        name_lower = name.lower()
        keys_to_delete = [
            k for k in self.cache.keys() if k[0].lower() == name_lower or k[0].lower().endswith("." + name_lower)
        ]

        count = 0
        for key in keys_to_delete:
            size = self._estimate_entry_size(self.cache[key])
            self.current_size -= size
            del self.cache[key]
            count += 1

        return count

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()
        self.current_size = 0

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with hit rate, size, entry count, etc.
        """
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "negative_hits": self.negative_hits,
            "evictions": self.evictions,
            "hit_rate_percent": hit_rate,
            "current_size_bytes": self.current_size,
            "max_size_bytes": self.max_size,
            "entry_count": len(self.cache),
            "utilization_percent": (self.current_size / self.max_size * 100) if self.max_size > 0 else 0,
        }

    def prefetch_expiring(self, threshold_seconds: int = 300) -> list[tuple[str, RecordType]]:
        """Get cache entries about to expire.

        Useful for proactive refresh before expiration.

        Args:
            threshold_seconds: How far ahead to look for expiration (default 5 min)

        Returns:
            List of (name, rtype) tuples
        """
        expiring = []
        now = time.time()

        for (name, rtype), entry in self.cache.items():
            time_to_expiry = entry.ttl - (now - entry.timestamp)
            if 0 < time_to_expiry < threshold_seconds:
                expiring.append((name, rtype))

        return expiring

    def _remove_entry(self, key: tuple[str, RecordType]) -> None:
        """Remove entry and update size."""
        if key in self.cache:
            size = self._estimate_entry_size(self.cache[key])
            self.current_size -= size
            del self.cache[key]

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self.cache:
            return

        # Find LRU entry (earliest last_accessed or lowest access_count)
        lru_key = min(
            self.cache.keys(),
            key=lambda k: (self.cache[k].last_accessed, self.cache[k].access_count),
        )

        size = self._estimate_entry_size(self.cache[lru_key])
        self.current_size -= size
        del self.cache[lru_key]
        self.evictions += 1

    def _estimate_entry_size(self, entry: CacheEntry) -> int:
        """Estimate memory size of cache entry.

        Args:
            entry: Cache entry

        Returns:
            Estimated size in bytes
        """
        size = 0
        for record in entry.records:
            size += len(record.name) + 4 + 4  # name, type, class
            size += 4  # TTL
            size += len(str(record.rdata))  # rdata
        return size + 100  # Overhead

    def serialize(self) -> str:
        """Serialize cache to JSON.

        Returns:
            JSON string representation of cache
        """
        entries = {}
        now = time.time()

        for (name, rtype), entry in self.cache.items():
            if not entry.is_expired():
                key = f"{name}:{rtype.name}"
                entries[key] = {
                    "records": [
                        {
                            "name": r.name,
                            "type": r.rtype.name,
                            "class": r.rclass,
                            "ttl": r.ttl,
                            "rdata": str(r.rdata),
                        }
                        for r in entry.records
                    ],
                    "is_negative": entry.is_negative,
                    "timestamp": entry.timestamp,
                    "ttl": entry.ttl,
                }

        return json.dumps(entries)

    def deserialize(self, data: str) -> None:
        """Deserialize cache from JSON.

        Args:
            data: JSON string from serialize()
        """
        entries = json.loads(data)

        for key_str, entry_data in entries.items():
            name, rtype_str = key_str.rsplit(":", 1)
            rtype = RecordType[rtype_str]

            records = [
                ResourceRecord(
                    name=r["name"],
                    rtype=RecordType[r["type"]],
                    rclass=r["class"],
                    ttl=r["ttl"],
                    rdata=r["rdata"],
                )
                for r in entry_data["records"]
            ]

            self.put(name, rtype, records, entry_data["is_negative"])
