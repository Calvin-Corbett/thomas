"""Content Delivery Network with edge caching, purge, and origin shield.

Implements a CDN system with caching strategies, geographic distribution, and purging.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class CacheStrategy(str, Enum):
    """Cache strategies."""

    TTL_BASED = "ttl_based"
    LRU = "lru"
    FIFO = "fifo"
    SIZE_BASED = "size_based"


class CompressionType(str, Enum):
    """Compression types."""

    NONE = "none"
    GZIP = "gzip"
    BROTLI = "brotli"


@dataclass
class CacheEntry:
    """A cached content entry."""

    key: str
    content: bytes
    content_type: str = "application/octet-stream"
    ttl_seconds: int = 3600
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    compressed: CompressionType = CompressionType.NONE
    size_bytes: int = 0

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        if self.ttl_seconds <= 0:
            return False
        expiry = self.created_at + timedelta(seconds=self.ttl_seconds)
        return datetime.now() > expiry

    def get_age_seconds(self) -> int:
        """Get age of cache entry in seconds."""
        return int((datetime.now() - self.created_at).total_seconds())


@dataclass
class EdgeLocation:
    """A CDN edge location."""

    id: str
    region: str
    city: str
    capacity_gb: float = 1000.0
    cache: dict[str, CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get_cache_size_gb(self) -> float:
        """Get current cache size in GB."""
        total_bytes = sum(entry.size_bytes for entry in self.cache.values())
        return total_bytes / (1024**3)

    def get_hit_ratio(self) -> float:
        """Get cache hit ratio."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total


class EdgeCache:
    """Cache for an edge location."""

    def __init__(self, strategy: CacheStrategy = CacheStrategy.TTL_BASED, max_size_gb: float = 100.0):
        self.strategy = strategy
        self.max_size_gb = max_size_gb
        self.cache: dict[str, CacheEntry] = {}
        self.access_times: list[tuple[str, datetime]] = []

    def get(self, key: str) -> bytes | None:
        """Get content from cache."""
        if key not in self.cache:
            return None

        entry = self.cache[key]
        if entry.is_expired():
            del self.cache[key]
            return None

        entry.accessed_at = datetime.now()
        entry.access_count += 1
        return entry.content

    def set(
        self, key: str, content: bytes, content_type: str = "application/octet-stream", ttl_seconds: int = 3600
    ) -> bool:
        """Set content in cache."""
        size_gb = len(content) / (1024**3)
        current_size = sum(e.size_bytes for e in self.cache.values()) / (1024**3)

        if current_size + size_gb > self.max_size_gb:
            self._evict_entries(size_gb)

        entry = CacheEntry(
            key=key, content=content, content_type=content_type, ttl_seconds=ttl_seconds, size_bytes=len(content)
        )
        self.cache[key] = entry
        return True

    def _evict_entries(self, required_space: float) -> None:
        """Evict entries based on strategy."""
        if self.strategy == CacheStrategy.LRU:
            sorted_entries = sorted(self.cache.items(), key=lambda x: x[1].accessed_at)
        elif self.strategy == CacheStrategy.FIFO:
            sorted_entries = sorted(self.cache.items(), key=lambda x: x[1].created_at)
        else:  # SIZE_BASED or TTL_BASED
            sorted_entries = sorted(self.cache.items(), key=lambda x: x[1].size_bytes, reverse=True)

        freed = 0.0
        required_bytes = required_space * (1024**3)

        for key, entry in sorted_entries:
            if freed >= required_bytes:
                break
            freed += entry.size_bytes
            del self.cache[key]

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "entries": len(self.cache),
            "size_gb": sum(e.size_bytes for e in self.cache.values()) / (1024**3),
            "strategy": self.strategy.value,
        }


class CDN:
    """Content Delivery Network."""

    def __init__(self, name: str = "cdn"):
        self.name = name
        self.edge_locations: dict[str, EdgeLocation] = {}
        self.origin_servers: dict[str, str] = {}
        self.purge_history: list[dict[str, Any]] = []
        self.origin_shield_enabled = False
        self.default_ttl = 3600
        self.compression = CompressionType.GZIP

    def add_edge_location(self, region: str, city: str) -> EdgeLocation:
        """Add an edge location."""
        location_id = f"{region}-{city}-{uuid.uuid4().hex[:8]}"
        location = EdgeLocation(location_id, region, city)
        self.edge_locations[location_id] = location
        return location

    def register_origin_server(self, name: str, url: str) -> None:
        """Register an origin server."""
        self.origin_servers[name] = url

    def cache_content(self, key: str, content: bytes, edge_location_ids: list[str] | None = None) -> None:
        """Cache content to edge locations."""
        locations = edge_location_ids or list(self.edge_locations.keys())

        for loc_id in locations:
            if loc_id in self.edge_locations:
                cache = EdgeCache()
                cache.set(key, content, ttl_seconds=self.default_ttl)
                self.edge_locations[loc_id].cache[key] = list(cache.cache.values())[0]

    def get_content(self, key: str, preferred_location: str | None = None) -> bytes | None:
        """Get content from edge location."""
        if preferred_location and preferred_location in self.edge_locations:
            location = self.edge_locations[preferred_location]
            if key in location.cache:
                entry = location.cache[key]
                if not entry.is_expired():
                    location.hits += 1
                    return entry.content
                location.misses += 1

        # Try other locations
        for loc_id, location in self.edge_locations.items():
            if loc_id == preferred_location:
                continue
            if key in location.cache:
                entry = location.cache[key]
                if not entry.is_expired():
                    location.hits += 1
                    return entry.content

        # Cache miss
        if preferred_location and preferred_location in self.edge_locations:
            self.edge_locations[preferred_location].misses += 1

        return None

    def purge_cache(self, pattern: str | None = None, edge_location_id: str | None = None) -> int:
        """Purge cache entries."""
        purged = 0

        location_ids = [edge_location_id] if edge_location_id else list(self.edge_locations.keys())

        for loc_id in location_ids:
            if loc_id not in self.edge_locations:
                continue

            location = self.edge_locations[loc_id]
            to_remove = []

            for key in location.cache.keys():
                if pattern is None or pattern in key:
                    to_remove.append(key)
                    purged += 1

            for key in to_remove:
                del location.cache[key]

        self.purge_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "pattern": pattern,
                "location": edge_location_id,
                "purged": purged,
            }
        )

        return purged

    def enable_origin_shield(self, enabled: bool = True) -> None:
        """Enable/disable origin shield."""
        self.origin_shield_enabled = enabled

    def get_cdn_stats(self) -> dict[str, Any]:
        """Get CDN statistics."""
        total_hits = sum(loc.hits for loc in self.edge_locations.values())
        total_misses = sum(loc.misses for loc in self.edge_locations.values())

        return {
            "name": self.name,
            "edge_locations": len(self.edge_locations),
            "origin_servers": len(self.origin_servers),
            "total_cached_gb": sum(loc.get_cache_size_gb() for loc in self.edge_locations.values()),
            "total_hits": total_hits,
            "total_misses": total_misses,
            "hit_ratio": total_hits / (total_hits + total_misses) if (total_hits + total_misses) > 0 else 0,
            "origin_shield_enabled": self.origin_shield_enabled,
        }

    def get_location_stats(self, location_id: str) -> dict[str, Any] | None:
        """Get stats for an edge location."""
        if location_id not in self.edge_locations:
            return None

        location = self.edge_locations[location_id]
        return {
            "id": location.id,
            "region": location.region,
            "city": location.city,
            "cache_size_gb": location.get_cache_size_gb(),
            "hit_ratio": location.get_hit_ratio(),
            "hits": location.hits,
            "misses": location.misses,
        }
