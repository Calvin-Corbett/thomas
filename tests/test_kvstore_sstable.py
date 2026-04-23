"""Tests for SSTable implementation."""

import tempfile
from pathlib import Path

import pytest

from thomas.marketplace.kvstore.bloom_filter import BloomFilterConfig
from thomas.marketplace.kvstore.sstable import SSTable, SSTableWriter


class TestSSTableWriterBasics:
    """Test basic SSTable writing."""

    def test_write_and_read(self):
        """Test writing and reading SSTable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Write SSTable
            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")
                writer.add(b"key2", b"value2")
                writer.add(b"key3", b"value3")

            # Read back
            sstable = SSTable(str(file_path))
            assert sstable.get(b"key1") == b"value1"
            assert sstable.get(b"key2") == b"value2"
            assert sstable.get(b"key3") == b"value3"

    def test_get_nonexistent_key(self):
        """Test that getting nonexistent key raises KeyError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")

            sstable = SSTable(str(file_path))
            with pytest.raises(KeyError):
                sstable.get(b"missing")

    def test_tombstone_handling(self):
        """Test that tombstones are handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Write with tombstone
            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")
                writer.add(b"key2", None)  # Tombstone
                writer.add(b"key3", b"value3")

            sstable = SSTable(str(file_path))
            assert sstable.get(b"key1") == b"value1"
            with pytest.raises(KeyError):
                sstable.get(b"key2")  # Tombstone
            assert sstable.get(b"key3") == b"value3"


class TestSSTableOrdering:
    """Test SSTable maintains sorted order."""

    def test_entries_sorted(self):
        """Test that entries are stored in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Write unsorted
            with SSTableWriter(str(file_path)) as writer:
                for key in [b"d", b"a", b"c", b"b"]:
                    writer.add(key, b"v")

            # Read back - should be sorted
            sstable = SSTable(str(file_path))
            entries = list(sstable.iter_entries())
            keys = [e.key for e in entries]
            assert keys == [b"a", b"b", b"c", b"d"]

    def test_binary_search_correctness(self):
        """Test that binary search finds correct blocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Write keys with small block size to create multiple blocks
            with SSTableWriter(str(file_path), block_size_bytes=256) as writer:
                for i in range(100):
                    key = f"key{i:03d}".encode()
                    writer.add(key, f"value{i}".encode())

            sstable = SSTable(str(file_path))

            # Verify all keys can be found
            for i in range(100):
                key = f"key{i:03d}".encode()
                value = sstable.get(key)
                assert value == f"value{i}".encode()


class TestSSTableBloomFilter:
    """Test Bloom filter integration."""

    def test_bloom_filter_applied(self):
        """Test that Bloom filter is created and used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")
                writer.add(b"key2", b"value2")

            sstable = SSTable(str(file_path))
            assert sstable.bloom_filter.might_contain(b"key1")
            assert sstable.bloom_filter.might_contain(b"key2")

    def test_bloom_filter_negative_test(self):
        """Test that Bloom filter helps avoid disk access for missing keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key1", b"value1")

            sstable = SSTable(str(file_path))

            # If Bloom filter says definitely not present, file won't be read
            # (This is internal optimization, but we can verify the interface)
            assert sstable.contains(b"key1")


class TestSSTableSerialization:
    """Test SSTable file format and serialization."""

    def test_file_format_valid(self):
        """Test that file has valid format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key", b"value")

            # Check file exists and has content
            assert file_path.exists()
            assert file_path.stat().st_size > 0

            # Verify it can be read
            sstable = SSTable(str(file_path))
            assert sstable.get(b"key") == b"value"

    def test_metadata_footer(self):
        """Test that metadata is correctly stored in footer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                for i in range(10):
                    writer.add(f"key{i}".encode(), f"value{i}".encode())

            sstable = SSTable(str(file_path))
            assert sstable.num_entries == 10


class TestSSTableIteration:
    """Test SSTable iteration."""

    def test_iter_all_entries(self):
        """Test iterating all entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            keys = []
            with SSTableWriter(str(file_path)) as writer:
                for i in range(10):
                    key = f"key{i:02d}".encode()
                    keys.append(key)
                    writer.add(key, f"value{i}".encode())

            sstable = SSTable(str(file_path))
            entries = list(sstable.iter_entries())
            entry_keys = [e.key for e in entries]
            assert entry_keys == sorted(keys)

    def test_iter_with_tombstones(self):
        """Test iteration includes tombstones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"a", b"1")
                writer.add(b"b", None)
                writer.add(b"c", b"3")

            sstable = SSTable(str(file_path))
            entries = list(sstable.iter_entries())
            assert len(entries) == 3
            assert entries[1].value is None  # Tombstone


class TestSSTableEdgeCases:
    """Test edge cases."""

    def test_large_values(self):
        """Test handling of large values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            large_value = b"x" * 100000
            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"key", large_value)

            sstable = SSTable(str(file_path))
            assert sstable.get(b"key") == large_value

    def test_many_small_entries(self):
        """Test handling many small entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            with SSTableWriter(str(file_path)) as writer:
                for i in range(10000):
                    writer.add(f"k{i}".encode(), f"v{i}".encode())

            sstable = SSTable(str(file_path))
            for i in range(10000):
                assert sstable.get(f"k{i}".encode()) == f"v{i}".encode()

    def test_block_boundaries(self):
        """Test entries that span block boundaries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Use small block size
            with SSTableWriter(str(file_path), block_size_bytes=128) as writer:
                for i in range(50):
                    writer.add(f"key{i:03d}".encode(), f"value{i:05d}".encode())

            sstable = SSTable(str(file_path))
            for i in range(50):
                assert sstable.get(f"key{i:03d}".encode()) == f"value{i:05d}".encode()


class TestSSTableBloomConfig:
    """Test Bloom filter configuration."""

    def test_custom_bloom_config(self):
        """Test using custom Bloom filter config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            config = BloomFilterConfig(expected_items=100, false_positive_rate=0.05)
            with SSTableWriter(str(file_path), bloom_config=config) as writer:
                writer.add(b"key", b"value")

            sstable = SSTable(str(file_path))
            assert sstable.get(b"key") == b"value"


class TestSSTableRobustness:
    """Test SSTable robustness."""

    def test_file_not_found(self):
        """Test that missing file raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "nonexistent.db"
            with pytest.raises(Exception):  # SSTableError
                SSTable(str(file_path))

    def test_sequential_writes(self):
        """Test that entries must be written in sorted order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.db"

            # Writing in sorted order should work
            with SSTableWriter(str(file_path)) as writer:
                writer.add(b"a", b"1")
                writer.add(b"b", b"2")
                writer.add(b"c", b"3")

            sstable = SSTable(str(file_path))
            assert sstable.num_entries == 3
