"""Tests for multi-tier cache implementation."""

from datetime import timedelta

from thomas.marketplace.caching import InclusivityMode, MultiTierCache, WritePolicy


class SimpleMemoryTier:
    """Simple in-memory storage tier for testing."""

    def __init__(self):
        self.data = {}

    def get(self, key: str):
        return self.data.get(key)

    def put(self, key: str, value, ttl: timedelta | None = None):
        self.data[key] = value

    def delete(self, key: str) -> bool:
        if key in self.data:
            del self.data[key]
            return True
        return False

    def contains(self, key: str) -> bool:
        return key in self.data

    def size(self) -> int:
        return len(self.data)

    def clear(self) -> None:
        self.data.clear()


class TestMultiTierBasicOps:
    """Test basic multi-tier cache operations."""

    def test_two_tier_cache(self):
        """Test cache with two tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        cache.put("key1", "value1")

        assert cache.get("key1") == "value1"

    def test_three_tier_cache(self):
        """Test cache with three tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        l3 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2, l3)

        cache.put("key1", "value1")

        assert cache.get("key1") == "value1"

    def test_single_tier_fallback(self):
        """Test cache with only L1 tier."""
        l1 = SimpleMemoryTier()
        cache = MultiTierCache(l1)

        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"


class TestMultiTierPromotion:
    """Test promotion of entries from lower tiers."""

    def test_promotion_from_l2_to_l1(self):
        """Test promoting entry from L2 to L1."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        # Put in L2 only
        l2.put("key1", "value1")

        # Get should promote to L1
        value = cache.get("key1")
        assert value == "value1"
        assert l1.contains("key1")

    def test_promotion_from_l3_through_tiers(self):
        """Test promoting entry from L3 through L2 to L1."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        l3 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2, l3)

        # Put in L3 only
        l3.put("key1", "value1")

        # Get should promote through tiers
        value = cache.get("key1")
        assert value == "value1"
        assert l1.contains("key1")
        assert l2.contains("key1")


class TestMultiTierWritePolicies:
    """Test write policies."""

    def test_write_through(self):
        """Test write-through policy writes to all tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        l3 = SimpleMemoryTier()
        cache = MultiTierCache(
            l1,
            l2,
            l3,
            write_policy=WritePolicy.WRITE_THROUGH,
        )

        cache.put("key1", "value1")

        assert l1.contains("key1")
        assert l2.contains("key1")
        assert l3.contains("key1")

    def test_write_back(self):
        """Test write-back policy."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(
            l1,
            l2,
            write_policy=WritePolicy.WRITE_BACK,
        )

        cache.put("key1", "value1")

        assert l1.contains("key1")
        # In async write-back, might also be in L2 (simplified implementation)
        assert l2.contains("key1")


class TestMultiTierInclusivity:
    """Test inclusivity modes."""

    def test_inclusive_mode(self):
        """Test inclusive mode keeps data in all tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(
            l1,
            l2,
            inclusivity=InclusivityMode.INCLUSIVE,
        )

        # Manually put in L2
        l2.put("key1", "value1")

        # Promote from L2 to L1
        cache.promote("key1")

        # In inclusive mode, stays in both
        assert l1.contains("key1")
        assert l2.contains("key1")

    def test_exclusive_mode(self):
        """Test exclusive mode removes data from lower tier."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(
            l1,
            l2,
            inclusivity=InclusivityMode.EXCLUSIVE,
        )

        # Manually put in L2
        l2.put("key1", "value1")

        # Promote from L2 to L1
        cache.promote("key1")

        # In exclusive mode, removes from L2
        assert l1.contains("key1")
        assert not l2.contains("key1")


class TestMultiTierDemotion:
    """Test demotion of entries to lower tiers."""

    def test_demote_from_l1_to_l2(self):
        """Test demoting entry from L1 to L2."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        cache.put("key1", "value1")
        assert l1.contains("key1")

        cache.demote("key1")

        assert not l1.contains("key1")
        assert l2.contains("key1")

    def test_demote_nonexistent(self):
        """Test demoting non-existent entry."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        assert not cache.demote("nonexistent")


class TestMultiTierDelete:
    """Test deletion across tiers."""

    def test_delete_from_all_tiers(self):
        """Test that delete removes from all tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        l3 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2, l3)

        # Put everywhere
        cache.put("key1", "value1")

        # Delete
        cache.delete("key1")

        assert not l1.contains("key1")
        assert not l2.contains("key1")
        assert not l3.contains("key1")


class TestMultiTierStats:
    """Test statistics collection."""

    def test_hit_stats(self):
        """Test hit statistics."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        cache.put("key1", "value1")

        # Hit in L1
        cache.get("key1")

        stats = cache.stats()
        assert stats.l1_hits == 1

    def test_tier_hit_rates(self):
        """Test hit rate per tier."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        # Put in L2 only
        l2.put("key1", "value1")

        # Get (promotes from L2)
        cache.get("key1")

        stats = cache.stats()
        assert stats.l2_hits == 1
        assert stats.l1_hits == 0  # Not a hit since not in L1

    def test_overall_hit_rate(self):
        """Test overall hit rate calculation."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        cache.put("key1", "value1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        assert cache.stats().hit_rate() == 0.5


class TestMultiTierClear:
    """Test clearing all tiers."""

    def test_clear_all_tiers(self):
        """Test that clear removes entries from all tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        l3 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2, l3)

        cache.put("key1", "value1")
        cache.put("key2", "value2")

        cache.clear()

        assert l1.size() == 0
        assert l2.size() == 0
        assert l3.size() == 0


class TestMultiTierContains:
    """Test contains checks."""

    def test_contains_in_any_tier(self):
        """Test that contains checks all tiers."""
        l1 = SimpleMemoryTier()
        l2 = SimpleMemoryTier()
        cache = MultiTierCache(l1, l2)

        # Put in L2 only
        l2.put("key1", "value1")

        assert cache.contains("key1")

    def test_not_contains(self):
        """Test contains returns false for missing keys."""
        l1 = SimpleMemoryTier()
        cache = MultiTierCache(l1)

        assert not cache.contains("nonexistent")
