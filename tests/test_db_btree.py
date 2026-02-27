"""
Tests for B+ tree index implementation.

Tests cover:
- Basic insertion and search
- Node splitting
- Deletion with merging
- Range scans
- Bulk loading
- Uniqueness constraints
- Tree statistics
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thomas.db_internals._exceptions import (
    DuplicateKeyException,
    KeyNotFoundException,
)
from thomas.db_internals._types import Index
from thomas.db_internals.btree import BPlusTree, BTreeKey, BTreeNode


class TestBTreeKeyBasic:
    """Tests for BTreeKey."""

    def test_create_key(self) -> None:
        """Test creating a BTree key."""
        key = BTreeKey(values=(1, "hello"), rid=(0, 5))
        assert key.values == (1, "hello")
        assert key.rid == (0, 5)

    def test_key_comparison(self) -> None:
        """Test key comparison."""
        key1 = BTreeKey(values=(1,))
        key2 = BTreeKey(values=(2,))

        assert key1 < key2
        assert key2 > key1
        assert key1 != key2

    def test_key_equality(self) -> None:
        """Test key equality."""
        key1 = BTreeKey(values=(1, "a"))
        key2 = BTreeKey(values=(1, "a"))

        assert key1 == key2

    def test_key_hash(self) -> None:
        """Test key hashing."""
        key = BTreeKey(values=(1, "a"))
        d = {key: "value"}
        assert d[key] == "value"

    def test_prefix_match(self) -> None:
        """Test prefix matching."""
        key1 = BTreeKey(values=(1, "a", "b"))
        key2 = BTreeKey(values=(1, "a"))

        assert key1.matches_prefix(key2)


class TestBTreeNodeBasic:
    """Tests for BTreeNode."""

    def test_create_node(self) -> None:
        """Test creating a node."""
        node = BTreeNode(node_id=1, is_leaf=True)
        assert node.node_id == 1
        assert node.is_leaf is True
        assert len(node.keys) == 0

    def test_node_full_check(self) -> None:
        """Test checking if node is full."""
        node = BTreeNode(node_id=1, is_leaf=True)
        order = 256

        # Add keys up to capacity
        for i in range(2 * order - 2):
            node.keys.append(BTreeKey(values=(i,)))

        assert not node.is_full(order)

        # Add one more to make it full
        node.keys.append(BTreeKey(values=(2 * order - 1,)))
        assert node.is_full(order)

    def test_binary_search(self) -> None:
        """Test binary search in node."""
        node = BTreeNode(node_id=1, is_leaf=True)
        for i in [1, 3, 5, 7, 9]:
            node.keys.append(BTreeKey(values=(i,)))

        # Search for existing
        idx = node.binary_search(BTreeKey(values=(5,)))
        assert node.keys[idx].values == (5,)

        # Search for non-existing
        idx = node.binary_search(BTreeKey(values=(4,)))
        assert idx < len(node.keys)


class TestBTreeInsertion:
    """Tests for B+ tree insertion."""

    def test_insert_single_key(self) -> None:
        """Test inserting a single key."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1,)), (0, 1))
        assert btree.num_keys == 1

    def test_insert_multiple_keys(self) -> None:
        """Test inserting multiple keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        assert btree.num_keys == 10

    def test_insert_duplicate_non_unique(self) -> None:
        """Test inserting duplicate into non-unique index."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"], is_unique=False)
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1,)), (0, 1))
        btree.insert(BTreeKey(values=(1,)), (0, 2))  # Should update RID

        assert btree.num_keys == 1

    def test_insert_duplicate_unique_error(self) -> None:
        """Test that duplicate in unique index raises error."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"], is_unique=True)
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1,)), (0, 1), unique=True)

        with pytest.raises(DuplicateKeyException):
            btree.insert(BTreeKey(values=(1,)), (0, 2), unique=True)

    def test_insert_creates_root(self) -> None:
        """Test that first insertion creates root."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        assert btree.root is None

        btree.insert(BTreeKey(values=(1,)), (0, 1))

        assert btree.root is not None
        assert btree.height == 1


class TestBTreeSearch:
    """Tests for B+ tree search."""

    def test_search_found(self) -> None:
        """Test searching for existing key."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(5,)), (0, 5))
        rid = btree.search(BTreeKey(values=(5,)))

        assert rid == (0, 5)

    def test_search_not_found(self) -> None:
        """Test searching for non-existent key."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(5,)), (0, 5))
        rid = btree.search(BTreeKey(values=(3,)))

        assert rid is None

    def test_search_empty_tree(self) -> None:
        """Test searching in empty tree."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        rid = btree.search(BTreeKey(values=(1,)))
        assert rid is None

    def test_search_multiple_keys(self) -> None:
        """Test searching in tree with multiple keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(20):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        # Search for middle
        rid = btree.search(BTreeKey(values=(10,)))
        assert rid == (0, 10)

        # Search for boundary
        rid = btree.search(BTreeKey(values=(0,)))
        assert rid == (0, 0)

        rid = btree.search(BTreeKey(values=(19,)))
        assert rid == (0, 19)


class TestBTreeRangeScan:
    """Tests for range scans."""

    def test_range_scan_all(self) -> None:
        """Test scanning all keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        results = list(btree.range_scan())
        assert len(results) == 10

    def test_range_scan_with_start(self) -> None:
        """Test range scan with start key."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        results = list(btree.range_scan(start_key=BTreeKey(values=(5,))))
        assert len(results) >= 5

    def test_range_scan_with_bounds(self) -> None:
        """Test range scan with both bounds."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        results = list(btree.range_scan(start_key=BTreeKey(values=(3,)), end_key=BTreeKey(values=(7,))))
        assert len(results) <= 5

    def test_range_scan_empty_tree(self) -> None:
        """Test range scan on empty tree."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        results = list(btree.range_scan())
        assert len(results) == 0


class TestBTreeBulkLoad:
    """Tests for bulk loading."""

    def test_bulk_load(self) -> None:
        """Test bulk loading keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        keys = [BTreeKey(values=(i,), rid=(0, i)) for i in range(100)]
        btree.bulk_load(keys)

        assert btree.num_keys == 100

    def test_bulk_load_empty(self) -> None:
        """Test bulk loading empty list."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.bulk_load([])

        assert btree.num_keys == 0

    def test_bulk_load_non_empty_tree_fails(self) -> None:
        """Test bulk load into non-empty tree fails."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(0,)), (0, 0))

        keys = [BTreeKey(values=(i,), rid=(0, i)) for i in range(10)]

        with pytest.raises(Exception):
            btree.bulk_load(keys)


class TestBTreeDeletion:
    """Tests for key deletion."""

    def test_delete_single_key(self) -> None:
        """Test deleting a key."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1,)), (0, 1))
        assert btree.num_keys == 1

        btree.delete(BTreeKey(values=(1,)))
        assert btree.num_keys == 0

    def test_delete_nonexistent_key(self) -> None:
        """Test deleting non-existent key raises error."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        with pytest.raises(KeyNotFoundException):
            btree.delete(BTreeKey(values=(1,)))

    def test_delete_multiple_keys(self) -> None:
        """Test deleting multiple keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        for i in range(5):
            btree.delete(BTreeKey(values=(i,)))

        assert btree.num_keys == 5


class TestBTreeStatistics:
    """Tests for tree statistics."""

    def test_get_statistics(self) -> None:
        """Test getting tree statistics."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        for i in range(10):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        stats = btree.get_statistics()
        assert stats["num_keys"] == 10
        assert stats["height"] >= 1

    def test_height_single_node(self) -> None:
        """Test height calculation for single node."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1,)), (0, 1))
        assert btree.height == 1

    def test_height_multiple_nodes(self) -> None:
        """Test height with multiple nodes."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a"])
        btree = BPlusTree(index)

        # Insert enough to force internal nodes
        for i in range(500):
            btree.insert(BTreeKey(values=(i,)), (0, i))

        assert btree.height > 1


class TestBTreeComposite:
    """Tests for composite keys."""

    def test_composite_key_insertion(self) -> None:
        """Test inserting composite keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a", "b"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1, "a")), (0, 1))
        btree.insert(BTreeKey(values=(1, "b")), (0, 2))
        btree.insert(BTreeKey(values=(2, "a")), (0, 3))

        assert btree.num_keys == 3

    def test_composite_key_search(self) -> None:
        """Test searching with composite keys."""
        index = Index(index_id=1, name="idx", table_name="t", columns=["a", "b"])
        btree = BPlusTree(index)

        btree.insert(BTreeKey(values=(1, "a")), (0, 1))

        rid = btree.search(BTreeKey(values=(1, "a")))
        assert rid == (0, 1)

        rid = btree.search(BTreeKey(values=(1, "b")))
        assert rid is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
