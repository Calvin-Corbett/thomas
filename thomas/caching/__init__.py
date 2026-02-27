"""Multi-tier caching infrastructure for the Thomas project.

This module provides production-ready caching implementations including:
- LRU and LFU caches with TTL support
- Multi-tier cache with promotion/demotion
- Distributed cache with consistent hashing
- Cache warming and invalidation strategies
- Statistics collection and serialization
"""

from ._exceptions import (
    CacheCorruptionError,
    CacheError,
    CacheExpirationError,
    CacheFullError,
    CacheMissError,
    EvictionError,
    SerializationError,
)
from ._types import (
    CacheConfig,
    CacheEntry,
    CacheStats,
    CacheTier,
    EvictionPolicy,
    TTLConfig,
    TTLPolicy,
)
from .distributed import ConsistentHashRing, SlotBasedRouter
from .invalidation import (
    CascadingInvalidation,
    InvalidationBus,
    InvalidationManager,
    PatternBasedInvalidation,
    TagBasedInvalidation,
)
from .lfu import LFUCache
from .lru import LRUCache
from .multi_tier import InclusivityMode, MultiTierCache, WritePolicy
from .serializers import (
    CompressedSerializer,
    JSONSerializer,
    PickleSerializer,
    SerializationContext,
    Serializer,
    SerializerFactory,
)
from .stats import LatencyMetrics, StatsCollector
from .ttl import TTLCache
from .warming import (
    BatchWarmer,
    CacheWarmer,
    PatternBasedWarmer,
    ScheduledWarmer,
    WarmingStrategy,
)

__all__ = [
    # Exceptions
    "CacheError",
    "CacheMissError",
    "CacheFullError",
    "CacheExpirationError",
    "SerializationError",
    "CacheCorruptionError",
    "EvictionError",
    # Types
    "CacheConfig",
    "CacheEntry",
    "CacheStats",
    "CacheTier",
    "EvictionPolicy",
    "TTLConfig",
    "TTLPolicy",
    # Cache implementations
    "LRUCache",
    "LFUCache",
    "TTLCache",
    "MultiTierCache",
    "WritePolicy",
    "InclusivityMode",
    # Distributed caching
    "ConsistentHashRing",
    "SlotBasedRouter",
    # Warming strategies
    "CacheWarmer",
    "WarmingStrategy",
    "PatternBasedWarmer",
    "BatchWarmer",
    "ScheduledWarmer",
    # Invalidation
    "InvalidationManager",
    "InvalidationBus",
    "TagBasedInvalidation",
    "PatternBasedInvalidation",
    "CascadingInvalidation",
    # Statistics
    "StatsCollector",
    "LatencyMetrics",
    # Serialization
    "Serializer",
    "JSONSerializer",
    "PickleSerializer",
    "CompressedSerializer",
    "SerializerFactory",
    "SerializationContext",
]

__version__ = "1.0.0"
