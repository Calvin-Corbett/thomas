"""
Tests for DNS cache: TTL expiration, negative caching, LRU eviction, stats.
"""

import json
import time
from ipaddress import IPv4Address

from thomas.marketplace.dns._types import RecordType, ResourceRecord
from thomas.marketplace.dns.cache import CacheEntry, DNSCache


class TestCacheEntry:
    """Test individual cache entries."""

    def test_entry_creation(self):
        """Test cache entry creation."""
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        entry = CacheEntry(records)

        assert entry.records == records
        assert entry.is_negative is False
        assert entry.ttl == 300
        assert entry.access_count == 0

    def test_entry_expiration(self):
        """Test TTL-based expiration."""
        records = [ResourceRecord("example.com.", RecordType.A, 1, 1, IPv4Address("192.0.2.1"))]
        entry = CacheEntry(records)

        assert not entry.is_expired()

        # Wait for TTL to expire
        time.sleep(1.1)
        assert entry.is_expired()

    def test_entry_access_tracking(self):
        """Test access counting."""
        records = []
        entry = CacheEntry(records)

        assert entry.access_count == 0
        entry.access()
        assert entry.access_count == 1
        entry.access()
        assert entry.access_count == 2

    def test_negative_cache_entry(self):
        """Test negative cache entry (NXDOMAIN)."""
        entry = CacheEntry([], is_negative=True)

        assert entry.is_negative is True
        assert entry.ttl > 0  # Has default TTL


class TestDNSCache:
    """Test DNS cache operations."""

    def test_cache_put_and_get(self):
        """Test putting and getting records."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)
        result = cache.get("example.com.", RecordType.A)

        assert result == records

    def test_cache_miss(self):
        """Test cache miss."""
        cache = DNSCache()
        result = cache.get("nonexistent.com.", RecordType.A)

        assert result is None
        assert cache.misses == 1
        assert cache.hits == 0

    def test_cache_hit(self):
        """Test cache hit."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)
        result = cache.get("example.com.", RecordType.A)

        assert result is not None
        assert cache.hits == 1
        assert cache.misses == 0

    def test_cache_expiration(self):
        """Test TTL-based expiration."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 1, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)
        assert cache.get("example.com.", RecordType.A) is not None

        # Wait for expiration
        time.sleep(1.1)
        assert cache.get("example.com.", RecordType.A) is None

    def test_negative_caching(self):
        """Test negative caching (NXDOMAIN)."""
        cache = DNSCache()

        # Cache negative response
        cache.put("nonexistent.com.", RecordType.A, [], is_negative=True)

        # Getting should return None but be a negative hit
        result = cache.get("nonexistent.com.", RecordType.A)
        assert result is None
        assert cache.negative_hits == 1

    def test_cache_delete(self):
        """Test deleting cache entry."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)
        assert cache.delete("example.com.", RecordType.A)
        assert cache.get("example.com.", RecordType.A) is None

    def test_cache_invalidate_domain(self):
        """Test invalidating all records for a domain."""
        cache = DNSCache()

        a_records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        aaaa_records = [ResourceRecord("example.com.", RecordType.AAAA, 1, 300, "2001:db8::1")]

        cache.put("example.com.", RecordType.A, a_records)
        cache.put("example.com.", RecordType.AAAA, aaaa_records)

        count = cache.invalidate("example.com.")
        assert count == 2

        assert cache.get("example.com.", RecordType.A) is None
        assert cache.get("example.com.", RecordType.AAAA) is None

    def test_cache_invalidate_subdomains(self):
        """Test invalidating subdomain records."""
        cache = DNSCache()

        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        sub_records = [ResourceRecord("www.example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.2"))]

        cache.put("example.com.", RecordType.A, records)
        cache.put("www.example.com.", RecordType.A, sub_records)

        count = cache.invalidate("example.com.")
        assert count == 2

    def test_cache_clear(self):
        """Test clearing entire cache."""
        cache = DNSCache()

        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        cache.put("example.com.", RecordType.A, records)

        assert len(cache.cache) > 0
        cache.clear()
        assert len(cache.cache) == 0

    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = DNSCache(max_size=500)  # Very small cache

        # Add records until eviction occurs
        for i in range(10):
            records = [
                ResourceRecord(
                    f"test{i}.com.",
                    RecordType.A,
                    1,
                    300,
                    IPv4Address(f"192.0.2.{i}"),
                )
            ]
            cache.put(f"test{i}.com.", RecordType.A, records)

        # Should have evicted some records
        assert cache.evictions > 0
        assert cache.current_size <= cache.max_size

    def test_cache_statistics(self):
        """Test cache statistics."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)
        cache.get("example.com.", RecordType.A)  # Hit
        cache.get("example.com.", RecordType.A)  # Hit
        cache.get("nothere.com.", RecordType.A)  # Miss

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["entry_count"] == 1
        assert 0 <= stats["hit_rate_percent"] <= 100

    def test_cache_multiple_types_same_name(self):
        """Test caching multiple types for same name."""
        cache = DNSCache()

        a_records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        aaaa_records = [ResourceRecord("example.com.", RecordType.AAAA, 1, 300, "2001:db8::1")]
        mx_records = [
            ResourceRecord("example.com.", RecordType.MX, 1, 300, {"preference": 10, "exchange": "mail.example.com."})
        ]

        cache.put("example.com.", RecordType.A, a_records)
        cache.put("example.com.", RecordType.AAAA, aaaa_records)
        cache.put("example.com.", RecordType.MX, mx_records)

        assert cache.get("example.com.", RecordType.A) == a_records
        assert cache.get("example.com.", RecordType.AAAA) == aaaa_records
        assert cache.get("example.com.", RecordType.MX) == mx_records

    def test_case_insensitive_lookup(self):
        """Test case-insensitive domain name lookup."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]

        cache.put("example.com.", RecordType.A, records)

        # Should find with different case
        assert cache.get("EXAMPLE.COM.", RecordType.A) == records
        assert cache.get("Example.Com.", RecordType.A) == records

    def test_prefetch_expiring(self):
        """Test finding entries about to expire."""
        cache = DNSCache()

        # Add record with short TTL
        records = [ResourceRecord("example.com.", RecordType.A, 1, 10, IPv4Address("192.0.2.1"))]
        cache.put("example.com.", RecordType.A, records)

        # Should be in expiring list
        expiring = cache.prefetch_expiring(threshold_seconds=15)
        assert ("example.com.", RecordType.A) in expiring

    def test_cache_serialization(self):
        """Test cache serialization to JSON."""
        cache = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        cache.put("example.com.", RecordType.A, records)

        serialized = cache.serialize()
        data = json.loads(serialized)

        assert "example.com.:A" in data

    def test_cache_deserialization(self):
        """Test cache deserialization from JSON."""
        cache1 = DNSCache()
        records = [ResourceRecord("example.com.", RecordType.A, 1, 300, IPv4Address("192.0.2.1"))]
        cache1.put("example.com.", RecordType.A, records)

        serialized = cache1.serialize()

        cache2 = DNSCache()
        cache2.deserialize(serialized)

        # Note: deserialized rdata will be string, not IPv4Address
        result = cache2.get("example.com.", RecordType.A)
        assert result is not None
