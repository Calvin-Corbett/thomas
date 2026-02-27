"""Integration tests for the complete KV store."""

import tempfile
import time

import pytest

from thomas.kvstore import CompactionStrategy, KVStore, KVStoreConfig
from thomas.kvstore._exceptions import KeyNotFoundError


class TestKVStoreBasics:
    """Test basic KV store operations."""

    def test_put_and_get(self):
        """Test basic put and get."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value")
                assert store.get(b"key") == b"value"

    def test_get_missing_key(self):
        """Test getting missing key raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                with pytest.raises(KeyNotFoundError):
                    store.get(b"missing")

    def test_update_key(self):
        """Test updating an existing key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value1")
                store.put(b"key", b"value2")
                assert store.get(b"key") == b"value2"

    def test_delete_key(self):
        """Test deleting a key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value")
                store.delete(b"key")
                with pytest.raises(KeyNotFoundError):
                    store.get(b"key")

    def test_contains(self):
        """Test contains method."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value")
                assert store.contains(b"key")
                assert not store.contains(b"missing")
                store.delete(b"key")
                assert not store.contains(b"key")

    def test_invalid_keys(self):
        """Test that empty keys are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                with pytest.raises(ValueError):
                    store.put(b"", b"value")

    def test_closed_store_raises_error(self):
        """Test that operations on closed store raise error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = KVStore(KVStoreConfig(data_dir=tmpdir))
            store.close()
            with pytest.raises(Exception):  # KVStoreError
                store.put(b"key", b"value")


class TestKVStoreMemtableFlush:
    """Test memtable flushing to SSTable."""

    def test_automatic_flush(self):
        """Test that memtable flushes when exceeding size threshold."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = KVStoreConfig(
                data_dir=tmpdir,
                memtable_size_mb=1,  # Small size to trigger flush
            )
            with KVStore(config) as store:
                # Write large enough data to trigger flush
                for i in range(100):
                    store.put(f"key{i:04d}".encode(), b"x" * 10000)

                # Give compaction thread time
                time.sleep(0.5)

                # Verify all keys still accessible
                for i in range(100):
                    assert store.get(f"key{i:04d}".encode()) == b"x" * 10000

    def test_recovery_from_wal(self):
        """Test that data is recovered from WAL after crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write data
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key1", b"value1")
                store.put(b"key2", b"value2")

            # Simulate restart
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store2:
                assert store2.get(b"key1") == b"value1"
                assert store2.get(b"key2") == b"value2"


class TestKVStoreScan:
    """Test range scan operations."""

    def test_scan_all(self):
        """Test scanning all keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                for i in range(10):
                    store.put(f"key{i:02d}".encode(), f"value{i}".encode())

                results = list(store.scan())
                assert len(results) == 10
                keys = [k for k, _ in results]
                assert keys == sorted(keys)

    def test_scan_with_start_key(self):
        """Test scan with start key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                for i in range(10):
                    store.put(f"key{i:02d}".encode(), f"value{i}".encode())

                results = list(store.scan(start_key=b"key05"))
                keys = [k for k, _ in results]
                assert b"key05" in keys
                assert b"key04" not in keys

    def test_scan_with_end_key(self):
        """Test scan with end key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                for i in range(10):
                    store.put(f"key{i:02d}".encode(), f"value{i}".encode())

                results = list(store.scan(end_key=b"key05"))
                keys = [k for k, _ in results]
                assert b"key05" not in keys
                assert all(k < b"key05" for k in keys)

    def test_scan_range(self):
        """Test scan with both start and end keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                for i in range(20):
                    store.put(f"key{i:02d}".encode(), f"value{i}".encode())

                results = list(store.scan(start_key=b"key05", end_key=b"key10"))
                keys = [k for k, _ in results]
                assert all(b"key05" <= k < b"key10" for k in keys)


class TestKVStoreCompaction:
    """Test compaction functionality."""

    def test_manual_compaction(self):
        """Test manual compaction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                # Write enough to create SSTables
                for i in range(100):
                    store.put(f"key{i:03d}".encode(), f"value{i}".encode())

                store.compact()

                # Verify data is still accessible
                for i in range(100):
                    assert store.get(f"key{i:03d}".encode()) == f"value{i}".encode()

    def test_automatic_l0_compaction(self):
        """Test automatic L0 compaction when file count threshold exceeded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = KVStoreConfig(data_dir=tmpdir, memtable_size_mb=1, compaction_level0_file_count_threshold=3)
            with KVStore(config) as store:
                # Write enough data to trigger L0 compaction
                for i in range(200):
                    store.put(f"key{i:03d}".encode(), f"value{i}".encode())

                # Wait for compaction
                time.sleep(2)

                # Data should still be accessible
                assert store.get(b"key000") == b"value0"


class TestKVStoreStats:
    """Test statistics collection."""

    def test_stats(self):
        """Test getting stats."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value")
                stats = store.stats()
                assert "memtable_size_bytes" in stats
                assert "memtable_entries" in stats
                assert "levels" in stats
                assert "sequence" in stats


class TestKVStoreConcurrency:
    """Test concurrent operations."""

    def test_concurrent_reads(self):
        """Test concurrent read operations."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            store = KVStore(KVStoreConfig(data_dir=tmpdir))

            # Pre-populate
            for i in range(100):
                store.put(f"key{i:03d}".encode(), f"value{i}".encode())

            results = []

            def reader():
                for i in range(100):
                    try:
                        val = store.get(f"key{i:03d}".encode())
                        results.append((i, val))
                    except KeyNotFoundError:
                        pass

            threads = [threading.Thread(target=reader) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            store.close()

            # All reads should succeed
            assert len(results) == 500

    def test_concurrent_writes(self):
        """Test concurrent write operations."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            store = KVStore(KVStoreConfig(data_dir=tmpdir))

            def writer(thread_id):
                for i in range(50):
                    store.put(f"key{thread_id}_{i:03d}".encode(), f"value{thread_id}_{i}".encode())

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            store.close()

            # Verify all writes persisted
            store2 = KVStore(KVStoreConfig(data_dir=tmpdir))
            for thread_id in range(5):
                for i in range(50):
                    assert store2.get(f"key{thread_id}_{i:03d}".encode()) == f"value{thread_id}_{i}".encode()
            store2.close()


class TestKVStoreContextManager:
    """Test context manager protocol."""

    def test_context_manager(self):
        """Test KVStore works as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                store.put(b"key", b"value")
                assert store.get(b"key") == b"value"


class TestKVStoreConfiguration:
    """Test different configurations."""

    def test_leveled_compaction(self):
        """Test with leveled compaction strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = KVStoreConfig(data_dir=tmpdir, compaction_strategy=CompactionStrategy.LEVELED)
            with KVStore(config) as store:
                store.put(b"key", b"value")
                assert store.get(b"key") == b"value"

    def test_size_tiered_compaction(self):
        """Test with size-tiered compaction strategy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = KVStoreConfig(data_dir=tmpdir, compaction_strategy=CompactionStrategy.SIZE_TIERED)
            with KVStore(config) as store:
                store.put(b"key", b"value")
                assert store.get(b"key") == b"value"


class TestKVStoreEdgeCases:
    """Test edge cases."""

    def test_large_values(self):
        """Test handling large values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir)) as store:
                large_value = b"x" * 1000000  # 1MB
                store.put(b"key", large_value)
                assert store.get(b"key") == large_value

    def test_many_keys(self):
        """Test handling many keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with KVStore(KVStoreConfig(data_dir=tmpdir, memtable_size_mb=32)) as store:
                for i in range(10000):
                    store.put(f"k{i}".encode(), f"v{i}".encode())

                # Wait for compaction
                time.sleep(1)

                # Verify random keys
                for i in [0, 100, 1000, 5000, 9999]:
                    assert store.get(f"k{i}".encode()) == f"v{i}".encode()
