"""Integration tests for caching module."""

import pickle
import threading
import time
from datetime import timedelta

import pytest

from thomas.marketplace.caching import (
    BatchWarmer,
    CacheConfig,
    CacheWarmer,
    InvalidationManager,
    LFUCache,
    LRUCache,
    SerializerFactory,
    StatsCollector,
    TTLCache,
    TTLConfig,
    TTLPolicy,
)


class TestLRUWithStats:
    """Test LRU cache with statistics collection."""

    def test_lru_with_stats_collector(self):
        """Test LRU cache integrated with stats collector."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)
        stats_collector = StatsCollector()

        cache.put("key1", "value1")
        stats_collector.record_memory_usage(cache.size_bytes(), cache.size())

        assert stats_collector.get_average_entry_count() == 1

    def test_hit_miss_latency_tracking(self):
        """Test tracking latency of hits and misses."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)
        stats_collector = StatsCollector()

        cache.put("key1", "value1")

        # Record hit latency
        start = time.time()
        cache.get("key1")
        latency_ms = (time.time() - start) * 1000
        stats_collector.record_hit(latency_ms)

        # Record miss latency
        start = time.time()
        cache.get("nonexistent")
        latency_ms = (time.time() - start) * 1000
        stats_collector.record_miss(latency_ms)

        assert stats_collector.get_hit_count() == 1
        assert stats_collector.get_miss_count() == 1


class TestCacheWithInvalidation:
    """Test cache with invalidation strategies."""

    def test_lru_with_tag_invalidation(self):
        """Test LRU cache with tag-based invalidation."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        cache = LRUCache(config)
        invalidation = InvalidationManager()

        cache.put("user:1:name", "Alice")
        cache.put("user:1:email", "alice@example.com")
        cache.put("user:2:name", "Bob")

        # Tag the entries
        invalidation.tag_strategy.tag_key("user:1:name", "user:1", "profile")
        invalidation.tag_strategy.tag_key("user:1:email", "user:1", "profile")
        invalidation.tag_strategy.tag_key("user:2:name", "user:2", "profile")

        # Invalidate user:1
        invalidation.tag_strategy.invalidate_tag("user:1")

        # Check which should be invalidated
        assert invalidation.should_invalidate("user:1:name")
        assert invalidation.should_invalidate("user:1:email")
        assert not invalidation.should_invalidate("user:2:name")

    def test_pattern_based_invalidation(self):
        """Test pattern-based invalidation."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        LRUCache(config)
        invalidation = InvalidationManager()

        # Add pattern for session keys
        invalidation.pattern_strategy.add_pattern(r"^session:.*")

        assert invalidation.should_invalidate("session:abc123")
        assert invalidation.should_invalidate("session:def456")
        assert not invalidation.should_invalidate("user:1:name")

    def test_cascading_invalidation(self):
        """Test cascading invalidation."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        LRUCache(config)
        invalidation = InvalidationManager()

        # Set up dependencies
        invalidation.cascading_strategy.add_dependency("user:1:posts", "user:1")
        invalidation.cascading_strategy.add_dependency("user:1:likes", "user:1")
        invalidation.cascading_strategy.add_dependency("feed:home", "user:1:posts")

        # Invalidate user:1
        count = invalidation.cascading_strategy.invalidate_key("user:1")

        # Should cascade to dependent keys
        assert count == 3  # user:1 + its 2 dependents
        assert invalidation.should_invalidate("user:1:posts")
        assert invalidation.should_invalidate("feed:home")


class TestCacheWarming:
    """Test cache warming strategies."""

    def test_batch_warming(self):
        """Test batch warming strategy."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100, enable_warming=False)
        cache = LRUCache(config)
        warmer = CacheWarmer(config)

        # Create batch warmer with initial data
        batch_data = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3",
        }
        batch_warmer = BatchWarmer(batch_data)
        warmer.add_strategy(batch_warmer)

        # Set up callbacks
        warmer.set_callbacks(
            put_callback=lambda k, v: cache.put(k, v),
            stats_callback=lambda: cache.stats(),
        )

        # Warm the cache
        warmed = warmer.warm()

        assert warmed == 3
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"

    def test_hit_rate_monitoring(self):
        """Test monitoring hit rate to trigger warming."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        cache = LRUCache(config)
        warmer = CacheWarmer(config)

        # Set up callback
        warmer.set_callbacks(
            put_callback=lambda k, v: cache.put(k, v),
            stats_callback=lambda: cache.stats(),
        )

        # Create situation with low hit rate
        cache.put("key1", "value1")
        cache.get("key1")  # 1 hit
        cache.get("key2")  # miss
        cache.get("key3")  # miss
        cache.get("key4")  # miss

        # Hit rate is 0.25
        below_threshold = warmer.check_hit_rate(threshold=0.7)

        assert below_threshold


class TestMultipleCachesWithInvalidation:
    """Test multiple caches with shared invalidation."""

    def test_dual_cache_with_invalidation_bus(self):
        """Test dual caches synchronized via invalidation bus."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        cache1 = LRUCache(config)
        cache2 = LFUCache(config)
        invalidation = InvalidationManager()

        # Put data in both caches
        cache1.put("user:1", "Alice")
        cache2.put("user:1", "Alice")

        # Set up bus subscriber
        invalidated_keys = []
        invalidation.bus.subscribe(lambda key: invalidated_keys.append(key))

        # Invalidate via bus
        invalidation.bus.publish("user:1")

        assert "user:1" in invalidated_keys
        assert invalidation.bus.event_count() == 1


class TestCacheWithSerialization:
    """Test cache with serialization."""

    def test_json_serialization(self):
        """Test JSON serializer."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        LRUCache(config)

        serializer = SerializerFactory.create("json")

        data = {"user": "Alice", "age": 30}
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        assert deserialized == data

    def test_pickle_serialization(self):
        """Test pickle serializer."""
        serializer = SerializerFactory.create("pickle")

        class CustomObject:
            def __init__(self, value):
                self.value = value

        obj = CustomObject("test")
        serialized = serializer.serialize(obj)
        deserialized = serializer.deserialize(serialized)

        assert deserialized.value == "test"

    def test_compressed_serialization(self):
        """Test compressed serialization."""
        serializer = SerializerFactory.create("json", compression="zlib")

        data = {"large": "x" * 1000}
        serialized = serializer.serialize(data)
        deserialized = serializer.deserialize(serialized)

        assert deserialized == data
        # Compressed should be smaller
        uncompressed = SerializerFactory.create("json")
        uncompressed_size = len(uncompressed.serialize(data))
        assert len(serialized) < uncompressed_size

    def test_pickle_deserialization_blocks_unsafe_globals(self):
        """Test pickle serializer rejects unsafe globals during load."""
        serializer = SerializerFactory.create("pickle")

        class _Exploit:
            def __reduce__(self):
                return (eval, ("1 + 1",))

        payload = pickle.dumps(_Exploit())

        with pytest.raises(Exception):
            serializer.deserialize(payload)


class TestTTLCacheWithActiveExpiration:
    """Test TTL cache with active expiration."""

    def test_active_ttl_expiration(self):
        """Test active TTL expiration."""
        ttl_config = TTLConfig(
            policy=TTLPolicy.ACTIVE,
            cleanup_interval=timedelta(milliseconds=100),
        )
        config = CacheConfig(ttl_config=ttl_config)
        cache = TTLCache(config)

        cache.put("key1", "value1", ttl=timedelta(milliseconds=50))
        cache.put("key2", "value2", ttl=timedelta(hours=1))

        assert cache.size() == 2

        # Wait for active cleanup
        time.sleep(0.2)

        # key1 should be cleaned up
        assert cache.size() == 1
        assert cache.get("key2") == "value2"

    def test_ttl_shutdown(self):
        """Test proper shutdown of TTL cache."""
        ttl_config = TTLConfig(policy=TTLPolicy.ACTIVE)
        config = CacheConfig(ttl_config=ttl_config)
        cache = TTLCache(config)

        cache.put("key1", "value1")
        cache.shutdown()

        # Should not raise
        cache.put("key2", "value2")


class TestConcurrentCaching:
    """Test concurrent caching operations."""

    def test_concurrent_read_write(self):
        """Test concurrent read/write operations."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)
        results = {"errors": 0}

        def reader():
            try:
                for i in range(100):
                    cache.get(f"key{i % 50}")
            except Exception:
                results["errors"] += 1

        def writer():
            try:
                for i in range(100):
                    cache.put(f"key{i % 50}", f"value{i}")
            except Exception:
                results["errors"] += 1

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert results["errors"] == 0

    def test_concurrent_invalidation(self):
        """Test concurrent invalidation operations."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)
        invalidation = InvalidationManager()

        # Populate cache
        for i in range(100):
            cache.put(f"key{i}", f"value{i}")
            invalidation.tag_strategy.tag_key(f"key{i}", "batch1" if i < 50 else "batch2")

        def invalidator():
            try:
                for _ in range(10):
                    invalidation.tag_strategy.invalidate_tag("batch1")
                    time.sleep(0.001)
            except Exception:
                pass

        threads = [threading.Thread(target=invalidator) for _ in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Should still be able to check invalidation
        assert invalidation.should_invalidate("key1")


class TestCacheMemoryUsage:
    """Test memory usage tracking."""

    def test_size_bytes_tracking(self):
        """Test tracking cache size in bytes."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        cache = LRUCache(config)

        assert cache.size_bytes() == 0

        cache.put("key1", "value1", size_bytes=100)
        assert cache.size_bytes() == 100

        cache.put("key2", "value2", size_bytes=200)
        assert cache.size_bytes() == 300

        cache.delete("key1")
        assert cache.size_bytes() == 200

    def test_size_enforcement(self):
        """Test that cache respects size limits."""
        config = CacheConfig(max_size_bytes=500, max_entries=1000)
        cache = LRUCache(config)

        # Fill to capacity
        cache.put("key1", "x" * 250, size_bytes=250)
        cache.put("key2", "x" * 250, size_bytes=250)

        # This should trigger eviction
        cache.put("key3", "x" * 250, size_bytes=250)

        # Should not exceed max size
        assert cache.size_bytes() <= 500
