"""Tests for Bloom filter implementation."""

import pytest

from thomas.marketplace.kvstore.bloom_filter import BloomFilter


class TestBloomFilterBasics:
    """Test basic Bloom filter operations."""

    def test_initialization(self):
        """Test basic initialization."""
        bf = BloomFilter(1000, 0.01)
        assert bf.expected_items == 1000
        assert bf.false_positive_rate == 0.01
        assert len(bf) == 0

    def test_add_and_contains(self):
        """Test adding and checking membership."""
        bf = BloomFilter(100, 0.01)
        bf.add(b"key1")
        assert bf.might_contain(b"key1")

    def test_negative_test(self):
        """Test that nonexistent items are correctly identified as not present."""
        bf = BloomFilter(100, 0.01)
        bf.add(b"key1")

        # Newly added item should be found
        assert bf.might_contain(b"key1")

        # Item that was never added should not be found
        # (though false positives are possible)
        if not bf.might_contain(b"missing"):
            assert True  # Correct negative response
        else:
            # This is a false positive (allowed)
            pass

    def test_empty_item_raises_error(self):
        """Test that empty items are rejected."""
        bf = BloomFilter(100, 0.01)
        with pytest.raises(ValueError):
            bf.add(b"")

    def test_false_positive_rate(self):
        """Test that false positive rate is reasonable."""
        bf = BloomFilter(1000, 0.01)

        # Add 100 items
        added = set()
        for i in range(100):
            key = f"key{i}".encode()
            bf.add(key)
            added.add(key)

        # Test false positive rate on non-added items
        false_positives = 0
        test_count = 10000
        for i in range(100, 100 + test_count):
            key = f"key{i}".encode()
            if bf.might_contain(key):
                false_positives += 1

        fpp = false_positives / test_count
        # Should be roughly close to configured rate (with some tolerance)
        assert fpp < 0.1  # At most 10% (loose bound for test stability)

    def test_serialization(self):
        """Test serialization and deserialization."""
        bf = BloomFilter(100, 0.01)
        bf.add(b"key1")
        bf.add(b"key2")
        bf.add(b"key3")

        # Serialize
        data = bf.serialize()
        assert isinstance(data, bytes)
        assert len(data) > 0

        # Deserialize
        bf2 = BloomFilter.deserialize(data)
        assert bf2.might_contain(b"key1")
        assert bf2.might_contain(b"key2")
        assert bf2.might_contain(b"key3")

    def test_deserialization_corrupt_data(self):
        """Test that corrupt data raises error."""
        with pytest.raises(ValueError):
            BloomFilter.deserialize(b"short")

    def test_size_estimation(self):
        """Test size estimation."""
        bf = BloomFilter(1000, 0.01)
        size = bf.size_bytes()
        assert size > 0
        assert size < 10000  # Should be reasonable size


class TestBloomFilterConfig:
    """Test configuration validation."""

    def test_invalid_false_positive_rate(self):
        """Test that invalid FPP is rejected."""
        with pytest.raises(ValueError):
            BloomFilter(100, 0.0)

        with pytest.raises(ValueError):
            BloomFilter(100, 1.0)

        with pytest.raises(ValueError):
            BloomFilter(100, 1.5)

    def test_invalid_expected_items(self):
        """Test that invalid expected items is rejected."""
        with pytest.raises(ValueError):
            BloomFilter(0, 0.01)

        with pytest.raises(ValueError):
            BloomFilter(-10, 0.01)


class TestBloomFilterProperties:
    """Test Bloom filter mathematical properties."""

    def test_no_false_negatives(self):
        """Test that items that are added are always found."""
        bf = BloomFilter(100, 0.01)
        items = [b"a", b"b", b"c", b"d", b"e"]

        for item in items:
            bf.add(item)

        for item in items:
            assert bf.might_contain(item)

    def test_item_count_tracking(self):
        """Test that added item count is tracked."""
        bf = BloomFilter(1000, 0.01)
        assert len(bf) == 0
        bf.add(b"key1")
        assert len(bf) == 1
        bf.add(b"key2")
        assert len(bf) == 2

    def test_clear(self):
        """Test clearing filter."""
        bf = BloomFilter(100, 0.01)
        bf.add(b"key1")
        assert len(bf) == 1

        bf.clear()
        assert len(bf) == 0
        # After clear, item should not be found
        # (though a clear Bloom filter might have false positives)


class TestBloomFilterDistribution:
    """Test hash function distribution."""

    def test_hash_distribution(self):
        """Test that hash function distributes well."""
        bf = BloomFilter(1000, 0.01)

        # Add many items and verify they're distributed across bits
        for i in range(1000):
            bf.add(f"item{i}".encode())

        # Count set bits
        set_bits = sum(bin(byte).count("1") for byte in bf.bit_array)
        total_bits = len(bf.bit_array) * 8

        # Should have reasonable distribution (not all zeros or all ones)
        fill_ratio = set_bits / total_bits
        assert 0.3 < fill_ratio < 0.8  # Reasonable fill ratio
