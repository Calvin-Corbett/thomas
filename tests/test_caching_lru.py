"""Tests for LRU cache implementation."""

import threading
import time
from datetime import timedelta

from thomas.marketplace.caching import CacheConfig, LRUCache, TTLConfig


class TestLRUBasicOps:
    """Test basic LRU cache operations."""

    def test_put_and_get(self):
        """Test basic put and get operations."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self):
        """Test getting a non-existent key."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        assert cache.get("nonexistent") is None
        assert cache.get("nonexistent", "default") == "default"

    def test_delete(self):
        """Test deleting entries."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        assert cache.delete("key1")
        assert cache.get("key1") is None
        assert not cache.delete("key1")

    def test_contains(self):
        """Test contains check."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        assert cache.contains("key1")
        assert not cache.contains("nonexistent")

    def test_clear(self):
        """Test clearing the cache."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.clear()

        assert cache.size() == 0
        assert cache.get("key1") is None

    def test_size(self):
        """Test getting cache size."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        assert cache.size() == 0
        cache.put("key1", "value1")
        assert cache.size() == 1
        cache.put("key2", "value2")
        assert cache.size() == 2


class TestLRUEviction:
    """Test LRU eviction behavior."""

    def test_eviction_by_entries(self):
        """Test eviction when max_entries is exceeded."""
        config = CacheConfig(max_size_bytes=10000, max_entries=3)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # This should evict key1 (least recently used)
        cache.put("key4", "value4")

        assert cache.size() == 3
        assert cache.get("key1") is None
        assert cache.get("key4") == "value4"

    def test_eviction_order(self):
        """Test that LRU evicts the least recently used."""
        config = CacheConfig(max_size_bytes=10000, max_entries=3)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # Access key1 to make it recently used
        cache.get("key1")

        # This should evict key2 (now least recently used)
        cache.put("key4", "value4")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_eviction_by_size(self):
        """Test eviction when max_size_bytes is exceeded."""
        config = CacheConfig(max_size_bytes=100, max_entries=100)
        cache = LRUCache(config)

        # Add items, each 50 bytes
        cache.put("key1", "x" * 50, size_bytes=50)
        cache.put("key2", "x" * 50, size_bytes=50)

        # This should trigger eviction
        cache.put("key3", "x" * 50, size_bytes=50)

        assert cache.size() == 2
        assert cache.size_bytes() <= 100

    def test_replacement_removes_old_entry(self):
        """Test that putting a duplicate key removes the old entry."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1", size_bytes=50)
        cache.put("key1", "value2", size_bytes=60)

        assert cache.get("key1") == "value2"
        assert cache.size() == 1
        assert cache.size_bytes() == 60


class TestLRUTTL:
    """Test TTL expiration in LRU cache."""

    def test_ttl_expiration_on_access(self):
        """Test that expired entries are not returned."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        # Put with short TTL
        ttl = timedelta(milliseconds=100)
        cache.put("key1", "value1", ttl=ttl)

        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired now
        assert cache.get("key1") is None

    def test_ttl_config_default(self):
        """Test that config default TTL is used."""
        ttl_config = TTLConfig(default_ttl=timedelta(milliseconds=100))
        config = CacheConfig(ttl_config=ttl_config)
        cache = LRUCache(config)

        cache.put("key1", "value1")  # No TTL specified, uses default

        assert cache.get("key1") == "value1"
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_cleanup_expired(self):
        """Test manual cleanup of expired entries."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1", ttl=timedelta(milliseconds=50))
        cache.put("key2", "value2", ttl=timedelta(hours=1))

        time.sleep(0.1)

        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"


class TestLRUStats:
    """Test LRU cache statistics."""

    def test_hit_miss_stats(self):
        """Test hit/miss statistics."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")

        # Hit
        cache.get("key1")
        # Miss
        cache.get("nonexistent")

        stats = cache.stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 0.5

    def test_eviction_stats(self):
        """Test eviction statistics."""
        config = CacheConfig(max_size_bytes=1000, max_entries=2)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")  # Causes eviction

        stats = cache.stats()
        assert stats.evictions == 1

    def test_reset_stats(self):
        """Test resetting statistics."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        cache.get("key1")

        cache.reset_stats()
        stats = cache.stats()

        assert stats.hits == 0
        assert stats.misses == 0


class TestLRUThreadSafety:
    """Test thread safety of LRU cache."""

    def test_concurrent_puts(self):
        """Test concurrent put operations."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)

        def worker(start, end):
            for i in range(start, end):
                cache.put(f"key{i}", f"value{i}")

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i * 100, (i + 1) * 100))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All entries should be present
        assert cache.size() == 500

    def test_concurrent_gets(self):
        """Test concurrent get operations."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)

        # Populate cache
        for i in range(100):
            cache.put(f"key{i}", f"value{i}")

        def worker(start, end):
            for i in range(start, end):
                cache.get(f"key{i}")

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(0, 100))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        stats = cache.stats()
        assert stats.hits == 500

    def test_concurrent_mixed_operations(self):
        """Test concurrent mixed operations."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)

        def read_worker():
            for i in range(100):
                cache.get(f"key{i}")

        def write_worker():
            for i in range(100):
                cache.put(f"key{i}", f"value{i}")

        threads = []
        for i in range(3):
            threads.append(threading.Thread(target=write_worker))
            threads.append(threading.Thread(target=read_worker))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert cache.size() > 0


class TestLRUEdgeCases:
    """Test edge cases and error conditions."""

    def test_large_value(self):
        """Test caching large values."""
        config = CacheConfig(max_size_bytes=10000, max_entries=100)
        cache = LRUCache(config)

        large_value = "x" * 1000
        cache.put("large", large_value, size_bytes=1000)

        assert cache.get("large") == large_value

    def test_many_entries(self):
        """Test cache with many small entries."""
        config = CacheConfig(max_size_bytes=100000, max_entries=1000)
        cache = LRUCache(config)

        for i in range(500):
            cache.put(f"key{i}", f"value{i}", size_bytes=10)

        assert cache.size() == 500

    def test_zero_size_entries(self):
        """Test entries with zero size."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1", size_bytes=0)
        cache.put("key2", "value2", size_bytes=0)

        assert cache.size() == 2

    def test_access_count_tracking(self):
        """Test that access count is tracked."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LRUCache(config)

        cache.put("key1", "value1")
        assert cache._map["key1"].entry.access_count == 0

        cache.get("key1")
        assert cache._map["key1"].entry.access_count == 1

        cache.get("key1")
        assert cache._map["key1"].entry.access_count == 2
