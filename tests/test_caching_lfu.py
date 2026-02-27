"""Tests for LFU cache implementation."""

import time
from datetime import timedelta

import pytest

from thomas.caching import CacheConfig, LFUCache


class TestLFUBasicOps:
    """Test basic LFU cache operations."""

    def test_put_and_get(self):
        """Test basic put and get operations."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent(self):
        """Test getting a non-existent key."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        assert cache.get("nonexistent") is None
        assert cache.get("nonexistent", "default") == "default"

    def test_delete(self):
        """Test deleting entries."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache.delete("key1")
        assert cache.get("key1") is None
        assert not cache.delete("key1")

    def test_contains(self):
        """Test contains check."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache.contains("key1")
        assert not cache.contains("nonexistent")

    def test_clear(self):
        """Test clearing the cache."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.clear()

        assert cache.size() == 0


class TestLFUFrequencyTracking:
    """Test frequency tracking in LFU cache."""

    def test_frequency_increment(self):
        """Test that frequency increments on access."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache._frequencies["key1"] == 1

        cache.get("key1")
        assert cache._frequencies["key1"] == 2

        cache.get("key1")
        assert cache._frequencies["key1"] == 3

    def test_least_frequent_eviction(self):
        """Test that least frequently used entries are evicted."""
        config = CacheConfig(max_size_bytes=1000, max_entries=3)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # Access key2 and key3 to increase frequency
        cache.get("key2")
        cache.get("key2")
        cache.get("key3")

        # key1 has lowest frequency, should be evicted
        cache.put("key4", "value4")

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_equal_frequency_eviction(self):
        """Test eviction when multiple entries have same frequency."""
        config = CacheConfig(max_size_bytes=1000, max_entries=2)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")

        # Both have frequency 1, one should be evicted
        cache.put("key3", "value3")

        assert cache.size() == 2
        # One of key1 or key2 should be evicted (both had freq=1)
        present_keys = set()
        if cache.get("key1"):
            present_keys.add("key1")
        if cache.get("key2"):
            present_keys.add("key2")

        assert len(present_keys) == 1


class TestLFUAging:
    """Test frequency aging to prevent pollution."""

    def test_age_frequencies(self):
        """Test aging reduces all frequencies."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.get("key1")
        cache.get("key1")

        assert cache._frequencies["key1"] == 3

        cache.age_frequencies(factor=0.5)

        # Frequency should be reduced
        assert cache._frequencies["key1"] == 1

    def test_aging_prevents_immortality(self):
        """Test that aging prevents frequently used entries from being immortal."""
        config = CacheConfig(max_size_bytes=1000, max_entries=3)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # Make key1 very frequent
        for _ in range(10):
            cache.get("key1")

        # Apply aging
        cache.age_frequencies(factor=0.25)

        # key1 frequency should be reduced significantly
        assert cache._frequencies["key1"] < 10

    def test_aging_invalid_factor(self):
        """Test that invalid aging factors are rejected."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        with pytest.raises(ValueError):
            cache.age_frequencies(factor=0)

        with pytest.raises(ValueError):
            cache.age_frequencies(factor=1.5)


class TestLFUTTL:
    """Test TTL expiration in LFU cache."""

    def test_ttl_expiration(self):
        """Test that expired entries are not returned."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        ttl = timedelta(milliseconds=100)
        cache.put("key1", "value1", ttl=ttl)

        assert cache.get("key1") == "value1"

        time.sleep(0.15)

        assert cache.get("key1") is None

    def test_cleanup_expired(self):
        """Test manual cleanup of expired entries."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1", ttl=timedelta(milliseconds=50))
        cache.put("key2", "value2", ttl=timedelta(hours=1))

        time.sleep(0.1)

        removed = cache.cleanup_expired()
        assert removed == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"


class TestLFUEviction:
    """Test LFU eviction behavior."""

    def test_eviction_by_entries(self):
        """Test eviction when max_entries is exceeded."""
        config = CacheConfig(max_size_bytes=10000, max_entries=3)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # This should evict one of them (all have freq=1)
        cache.put("key4", "value4")

        assert cache.size() == 3

    def test_eviction_by_size(self):
        """Test eviction when max_size_bytes is exceeded."""
        config = CacheConfig(max_size_bytes=100, max_entries=100)
        cache = LFUCache(config)

        cache.put("key1", "x" * 50, size_bytes=50)
        cache.put("key2", "x" * 50, size_bytes=50)

        # This should trigger eviction
        cache.put("key3", "x" * 50, size_bytes=50)

        assert cache.size() == 2


class TestLFUStats:
    """Test LFU cache statistics."""

    def test_hit_miss_stats(self):
        """Test hit/miss statistics."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")

        # Hit
        cache.get("key1")
        # Miss
        cache.get("nonexistent")

        stats = cache.stats()
        assert stats.hits == 1
        assert stats.misses == 1

    def test_eviction_stats(self):
        """Test eviction statistics."""
        config = CacheConfig(max_size_bytes=1000, max_entries=2)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")  # Causes eviction

        stats = cache.stats()
        assert stats.evictions == 1


class TestLFUBoundaryConditions:
    """Test boundary conditions and edge cases."""

    def test_empty_cache_cleanup(self):
        """Test cleanup on empty cache."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        removed = cache.cleanup_expired()
        assert removed == 0

    def test_single_entry(self):
        """Test cache with single entry."""
        config = CacheConfig(max_size_bytes=1000, max_entries=1)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

        # Adding another should evict the first
        cache.put("key2", "value2")
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_replacement(self):
        """Test replacing an entry."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.put("key1", "value2")

        assert cache.get("key1") == "value2"
        assert cache.size() == 1

    def test_access_count_tracking(self):
        """Test that access count is tracked."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        assert cache._entries["key1"].access_count == 0

        cache.get("key1")
        assert cache._entries["key1"].access_count == 1

        cache.get("key1")
        assert cache._entries["key1"].access_count == 2

    def test_frequency_bucket_cleanup(self):
        """Test that empty frequency buckets are cleaned up."""
        config = CacheConfig(max_size_bytes=1000, max_entries=10)
        cache = LFUCache(config)

        cache.put("key1", "value1")
        cache.get("key1")  # freq = 2

        # Delete key1
        cache.delete("key1")

        # Frequency bucket for freq 2 should be gone
        assert 2 not in cache._frequency_buckets
