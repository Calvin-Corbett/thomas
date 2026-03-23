"""
Tests for columnar indexes: bitmaps, zone maps, bloom filters, inverted indexes.
"""

from thomas.marketplace.columnar._types import Statistics
from thomas.marketplace.columnar.indexes import (
    BitmapIndex,
    BloomFilter,
    IndexAdvisor,
    InvertedIndex,
    ZoneMap,
)


class TestBitmapIndex:
    """Tests for bitmap indexes."""

    def test_set_and_get(self) -> None:
        """Test setting and getting bits."""
        idx = BitmapIndex("value_a")

        idx.set(0)
        idx.set(5)
        idx.set(10)

        assert idx.is_set(0)
        assert idx.is_set(5)
        assert idx.is_set(10)
        assert not idx.is_set(3)

    def test_clear_bit(self) -> None:
        """Test clearing bits."""
        idx = BitmapIndex("value_a")

        idx.set(5)
        assert idx.is_set(5)

        idx.clear(5)
        assert not idx.is_set(5)

    def test_and_operation(self) -> None:
        """Test AND operation between bitmaps."""
        idx1 = BitmapIndex("a")
        idx2 = BitmapIndex("b")

        idx1.set(0)
        idx1.set(2)
        idx1.set(4)

        idx2.set(0)
        idx2.set(1)
        idx2.set(4)

        result = idx1.and_mask(idx2)

        assert result[0] == True
        assert result[1] == False
        assert result[2] == False
        assert result[4] == True

    def test_or_operation(self) -> None:
        """Test OR operation between bitmaps."""
        idx1 = BitmapIndex("a")
        idx2 = BitmapIndex("b")

        idx1.set(0)
        idx1.set(2)

        idx2.set(1)
        idx2.set(3)

        result = idx1.or_mask(idx2)

        assert result[0] == True
        assert result[1] == True
        assert result[2] == True
        assert result[3] == True

    def test_count_set_bits(self) -> None:
        """Test counting set bits."""
        idx = BitmapIndex("value")

        for i in range(10):
            idx.set(i)

        assert idx.count() == 10

    def test_to_mask(self) -> None:
        """Test converting bitmap to boolean mask."""
        idx = BitmapIndex("value")

        idx.set(0)
        idx.set(2)
        idx.set(4)

        mask = idx.to_mask(5)

        assert mask == [True, False, True, False, True]


class TestZoneMap:
    """Tests for zone maps (min/max indexes)."""

    def test_add_zone(self) -> None:
        """Test adding zones to zone map."""
        zm = ZoneMap("age")

        zm.add_zone(0, 10)
        zm.add_zone(10, 20)
        zm.add_zone(20, 30)

        assert len(zm.zones) == 3

    def test_find_matching_zones_equal(self) -> None:
        """Test finding zones matching equality predicate."""
        zm = ZoneMap("age")

        zm.add_zone(0, 10)
        zm.add_zone(10, 20)
        zm.add_zone(20, 30)

        matching = zm.find_matching_zones("==", 15)

        assert 1 in matching
        assert len(matching) > 0

    def test_find_matching_zones_range(self) -> None:
        """Test finding zones matching range predicate."""
        zm = ZoneMap("age")

        zm.add_zone(0, 10)
        zm.add_zone(10, 20)
        zm.add_zone(20, 30)

        matching = zm.find_matching_zones(">", 15)

        assert 2 in matching

    def test_prune_zones(self) -> None:
        """Test pruning zones."""
        zm = ZoneMap("score")

        zm.add_zone(0, 50)
        zm.add_zone(50, 75)
        zm.add_zone(75, 100)

        pruned = zm.prune_zones("<=", 50)

        assert len(pruned) > 0


class TestBloomFilter:
    """Tests for Bloom filters."""

    def test_add_and_contains(self) -> None:
        """Test adding and checking membership."""
        bf = BloomFilter(expected_elements=100)

        bf.add("apple")
        bf.add("banana")
        bf.add("cherry")

        assert bf.contains("apple")
        assert bf.contains("banana")
        assert bf.contains("cherry")

    def test_not_contains(self) -> None:
        """Test checking non-membership."""
        bf = BloomFilter(expected_elements=100)

        bf.add("apple")
        bf.add("banana")

        # May have false positives, but definitely doesn't contain
        assert not bf.contains("xyz")

    def test_numeric_values(self) -> None:
        """Test Bloom filter with numeric values."""
        bf = BloomFilter(expected_elements=1000)

        for i in range(100):
            bf.add(i)

        for i in range(100):
            assert bf.contains(i)

    def test_serialization(self) -> None:
        """Test Bloom filter serialization."""
        bf = BloomFilter(expected_elements=100)

        bf.add("test_value")

        serialized = bf.serialize()
        assert len(serialized) > 0

        bf2 = BloomFilter.deserialize(serialized)
        assert bf2.contains("test_value")


class TestInvertedIndex:
    """Tests for inverted indexes."""

    def test_add_and_search(self) -> None:
        """Test adding values and searching."""
        idx = InvertedIndex("text")

        idx.add(0, "hello world")
        idx.add(1, "world peace")
        idx.add(2, "hello there")

        result = idx.search("hello world")

        assert 0 in result
        assert 1 not in result

    def test_search_or(self) -> None:
        """Test searching with OR semantics."""
        idx = InvertedIndex("text")

        idx.add(0, "apple banana")
        idx.add(1, "apple cherry")
        idx.add(2, "banana cherry")

        result = idx.search_or("apple cherry")

        assert 0 in result
        assert 1 in result
        assert 2 in result

    def test_single_term_search(self) -> None:
        """Test single term search."""
        idx = InvertedIndex("tags")

        idx.add(0, "python")
        idx.add(1, "java")
        idx.add(2, "python")

        result = idx.search("python")

        assert len(result) == 2
        assert 0 in result
        assert 2 in result

    def test_case_insensitive(self) -> None:
        """Test case-insensitive search."""
        idx = InvertedIndex("text")

        idx.add(0, "Hello World")
        idx.add(1, "hello world")

        result = idx.search("HELLO")

        assert 0 in result
        assert 1 in result


class TestIndexAdvisor:
    """Tests for index advisor."""

    def test_recommend_indexes_low_cardinality(self) -> None:
        """Test index recommendations for low cardinality column."""
        stats = Statistics()
        stats.total_value_count = 1000
        stats.distinct_count = 10

        recommendations = IndexAdvisor.recommend_indexes({"category": stats})

        assert "category" in recommendations

    def test_recommend_indexes_high_cardinality(self) -> None:
        """Test index recommendations for high cardinality column."""
        stats = Statistics()
        stats.total_value_count = 1000
        stats.distinct_count = 900

        recommendations = IndexAdvisor.recommend_indexes({"id": stats})

        assert "id" in recommendations
        assert recommendations["id"] == "zone_map"

    def test_should_create_bitmap(self) -> None:
        """Test bitmap creation recommendation."""
        stats = Statistics()
        stats.total_value_count = 1000
        stats.distinct_count = 100

        should_create = IndexAdvisor.should_create_bitmap(stats)

        assert should_create

    def test_should_create_bloom_filter(self) -> None:
        """Test Bloom filter creation recommendation."""
        stats = Statistics()
        stats.total_value_count = 1000
        stats.distinct_count = 50

        should_create = IndexAdvisor.should_create_bloom_filter(stats)

        assert should_create

    def test_should_create_inverted_index(self) -> None:
        """Test inverted index creation recommendation."""
        stats = Statistics()
        stats.total_value_count = 1000
        stats.distinct_count = 300

        should_create = IndexAdvisor.should_create_inverted_index(stats)

        assert should_create


class TestIndexEdgeCases:
    """Tests for index edge cases."""

    def test_bitmap_large_row_ids(self) -> None:
        """Test bitmap with large row IDs."""
        idx = BitmapIndex("value")

        idx.set(1000000)
        idx.set(2000000)

        assert idx.is_set(1000000)
        assert idx.is_set(2000000)

    def test_bloom_filter_false_positive_rate(self) -> None:
        """Test Bloom filter false positive rate."""
        bf = BloomFilter(expected_elements=1000, false_positive_rate=0.01)

        for i in range(500):
            bf.add(i)

        false_positives = 0
        for i in range(500, 2000):
            if bf.contains(i):
                false_positives += 1

        # Should have some false positives but not too many
        assert 0 <= false_positives < 200

    def test_inverted_index_empty_query(self) -> None:
        """Test inverted index with empty query."""
        idx = InvertedIndex("text")

        idx.add(0, "hello")

        result = idx.search("")

        assert len(result) == 0

    def test_zone_map_null_bounds(self) -> None:
        """Test zone map with null bounds."""
        zm = ZoneMap("value")

        zm.add_zone(None, None)
        zm.add_zone(None, 10)
        zm.add_zone(10, None)

        matching = zm.find_matching_zones("is_null", None)

        assert len(matching) > 0
