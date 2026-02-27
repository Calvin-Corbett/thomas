"""Tests for skip list implementation."""

import random

import pytest

from thomas.kvstore.skiplist import SkipList


class TestSkipListBasics:
    """Test basic skip list operations."""

    def test_insert_and_get(self):
        """Test basic insert and retrieve."""
        sl = SkipList()
        sl.insert(b"key1", b"value1")
        assert sl.get(b"key1") == b"value1"

    def test_get_nonexistent_raises_keyerror(self):
        """Test that getting nonexistent key raises KeyError."""
        sl = SkipList()
        with pytest.raises(KeyError):
            sl.get(b"missing")

    def test_update_existing_key(self):
        """Test updating an existing key."""
        sl = SkipList()
        sl.insert(b"key", b"value1")
        sl.insert(b"key", b"value2")
        assert sl.get(b"key") == b"value2"

    def test_size_tracking(self):
        """Test that size is tracked correctly."""
        sl = SkipList()
        assert len(sl) == 0
        sl.insert(b"a", b"1")
        assert len(sl) == 1
        sl.insert(b"b", b"2")
        assert len(sl) == 2
        sl.insert(b"a", b"updated")  # Update
        assert len(sl) == 2  # Size doesn't change on update

    def test_empty_key_raises_error(self):
        """Test that empty keys are rejected."""
        sl = SkipList()
        with pytest.raises(ValueError):
            sl.insert(b"", b"value")

    def test_tombstone(self):
        """Test inserting None as tombstone."""
        sl = SkipList()
        sl.insert(b"key", b"value")
        sl.insert(b"key", None)
        with pytest.raises(KeyError):
            sl.get(b"key")

    def test_contains(self):
        """Test contains method."""
        sl = SkipList()
        sl.insert(b"key", b"value")
        assert sl.contains(b"key")
        assert not sl.contains(b"other")

    def test_contains_tombstone_false(self):
        """Test that contains returns False for tombstones."""
        sl = SkipList()
        sl.insert(b"key", b"value")
        sl.insert(b"key", None)
        assert not sl.contains(b"key")

    def test_contains_or_tombstone(self):
        """Test contains_or_tombstone counts tombstones."""
        sl = SkipList()
        sl.insert(b"key", None)
        assert not sl.contains(b"key")
        assert sl.contains_or_tombstone(b"key")

    def test_delete(self):
        """Test delete operation."""
        sl = SkipList()
        sl.insert(b"key", b"value")
        assert sl.delete(b"key")
        with pytest.raises(KeyError):
            sl.get(b"key")

    def test_delete_nonexistent(self):
        """Test deleting nonexistent key."""
        sl = SkipList()
        assert not sl.delete(b"missing")


class TestSkipListOrdering:
    """Test skip list maintains sorted order."""

    def test_range_query_all(self):
        """Test range query over all keys."""
        sl = SkipList()
        keys = [b"c", b"a", b"b", b"d"]
        for key in keys:
            sl.insert(key, b"v")

        results = [k for k, _ in sl.iter_all()]
        assert results == [b"a", b"b", b"c", b"d"]

    def test_range_query_with_start(self):
        """Test range query with start key."""
        sl = SkipList()
        for key in [b"a", b"b", b"c", b"d"]:
            sl.insert(key, b"v")

        results = [k for k, _ in sl.range_query(start_key=b"b")]
        assert results == [b"b", b"c", b"d"]

    def test_range_query_with_end(self):
        """Test range query with end key."""
        sl = SkipList()
        for key in [b"a", b"b", b"c", b"d"]:
            sl.insert(key, b"v")

        results = [k for k, _ in sl.range_query(end_key=b"c")]
        assert results == [b"a", b"b"]

    def test_range_query_with_start_and_end(self):
        """Test range query with both bounds."""
        sl = SkipList()
        for key in [b"a", b"b", b"c", b"d", b"e"]:
            sl.insert(key, b"v")

        results = [k for k, _ in sl.range_query(start_key=b"b", end_key=b"d")]
        assert results == [b"b", b"c"]

    def test_range_query_empty_range(self):
        """Test range query with no results."""
        sl = SkipList()
        sl.insert(b"a", b"v")
        sl.insert(b"z", b"v")

        results = [k for k, _ in sl.range_query(start_key=b"m", end_key=b"p")]
        assert results == []

    def test_tombstones_in_range_query(self):
        """Test that tombstones are handled in range queries."""
        sl = SkipList()
        sl.insert(b"a", b"1")
        sl.insert(b"b", None)  # Tombstone
        sl.insert(b"c", b"3")

        # Without tombstones
        results = [k for k, _ in sl.range_query(include_tombstones=False)]
        assert results == [b"a", b"c"]

        # With tombstones
        results = [k for k, _ in sl.range_query(include_tombstones=True)]
        assert results == [b"a", b"b", b"c"]


class TestSkipListConcurrency:
    """Test concurrent read operations."""

    def test_concurrent_reads(self):
        """Test multiple threads reading concurrently."""
        import threading

        sl = SkipList()
        for i in range(100):
            sl.insert(f"key{i:03d}".encode(), b"value")

        results = []

        def reader():
            for i in range(100):
                try:
                    val = sl.get(f"key{i:03d}".encode())
                    results.append((i, val))
                except KeyError:
                    results.append((i, None))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should succeed
        assert len(results) == 500


class TestSkipListRobustness:
    """Test skip list robustness."""

    def test_large_dataset(self):
        """Test with large number of insertions."""
        sl = SkipList()
        n = 1000

        for i in range(n):
            sl.insert(f"key{i:05d}".encode(), f"value{i}".encode())

        assert len(sl) == n

        # Check ordering
        prev = None
        for key, _ in sl.iter_all():
            if prev is not None:
                assert prev < key
            prev = key

    def test_random_operations(self):
        """Test with random inserts, updates, deletes."""
        sl = SkipList()
        keys = set()

        for _ in range(500):
            op = random.choice(["insert", "delete"])
            key = f"key{random.randint(0, 50):02d}".encode()

            if op == "insert":
                sl.insert(key, b"value")
                keys.add(key)
            elif key in keys:
                sl.delete(key)
                keys.remove(key)

        # Verify ordering
        prev = None
        count = 0
        for k, _ in sl.iter_all(include_tombstones=False):
            if prev is not None:
                assert prev < k
            prev = k
            count += 1

        assert count == len([k for k in keys if k in sl])

    def test_min_max_keys(self):
        """Test min and max key retrieval."""
        sl = SkipList()
        keys = [b"d", b"a", b"c", b"b"]
        for key in keys:
            sl.insert(key, b"v")

        assert sl.min_key() == b"a"
        assert sl.max_key() == b"d"

    def test_min_max_empty(self):
        """Test min/max on empty list."""
        sl = SkipList()
        assert sl.min_key() is None
        assert sl.max_key() is None

    def test_clear(self):
        """Test clearing the skip list."""
        sl = SkipList()
        sl.insert(b"a", b"1")
        sl.insert(b"b", b"2")
        sl.clear()
        assert len(sl) == 0
        with pytest.raises(KeyError):
            sl.get(b"a")

    def test_bool_conversion(self):
        """Test bool conversion."""
        sl = SkipList()
        assert not sl
        sl.insert(b"a", b"1")
        assert sl
