"""Tests for write-ahead log."""

import tempfile
from pathlib import Path

import pytest

from thomas.kvstore._exceptions import CorruptionError
from thomas.kvstore._types import WriteOp
from thomas.kvstore.wal import WAL


class TestWALBasics:
    """Test basic WAL operations."""

    def test_initialization(self):
        """Test WAL initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            assert wal.dir_path == Path(tmpdir)
            wal.close()

    def test_append_put(self):
        """Test appending PUT operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

    def test_append_delete(self):
        """Test appending DELETE operation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.DELETE, b"key", None)
            wal.close()

    def test_invalid_parameters(self):
        """Test that invalid parameters are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir, rotation_size_mb=100)

            # Empty key
            with pytest.raises(ValueError):
                wal.append(1, WriteOp.PUT, b"", b"value")

            # PUT without value
            with pytest.raises(ValueError):
                wal.append(1, WriteOp.PUT, b"key", None)

            wal.close()


class TestWALRecovery:
    """Test WAL recovery functionality."""

    def test_recovery_puts(self):
        """Test recovering PUT operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write some entries
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.PUT, b"key1", b"value1")
            wal.append(2, WriteOp.PUT, b"key2", b"value2")
            wal.close()

            # Read them back
            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            assert len(entries) == 2
            assert entries[0].sequence == 1
            assert entries[0].op == WriteOp.PUT
            assert entries[0].key == b"key1"
            assert entries[0].value == b"value1"
            assert entries[1].sequence == 2

    def test_recovery_deletes(self):
        """Test recovering DELETE operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.DELETE, b"key", None)
            wal.close()

            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            assert len(entries) == 1
            assert entries[0].op == WriteOp.DELETE
            assert entries[0].value is None

    def test_recovery_mixed_operations(self):
        """Test recovering mixed operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.PUT, b"a", b"1")
            wal.append(2, WriteOp.DELETE, b"b", None)
            wal.append(3, WriteOp.PUT, b"c", b"3")
            wal.close()

            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            assert len(entries) == 3
            assert entries[0].op == WriteOp.PUT
            assert entries[1].op == WriteOp.DELETE
            assert entries[2].op == WriteOp.PUT


class TestWALRotation:
    """Test WAL file rotation."""

    def test_rotation(self):
        """Test that WAL rotates when exceeding size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Small rotation size
            wal = WAL(tmpdir, rotation_size_mb=0.001)  # ~1KB

            # Write enough to exceed rotation size
            for i in range(10):
                wal.append(i, WriteOp.PUT, f"key{i}".encode(), b"x" * 500)

            wal.close()

            # Should have multiple files
            files = list(Path(tmpdir).glob("wal_*.log"))
            assert len(files) >= 2

    def test_recovery_multiple_files(self):
        """Test recovery from multiple WAL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple WAL files
            wal = WAL(tmpdir, rotation_size_mb=0.001)
            for i in range(10):
                wal.append(i, WriteOp.PUT, f"key{i}".encode(), b"x" * 500)
            wal.close()

            # Recover all entries
            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            # Should have all 10 entries in order
            assert len(entries) == 10
            for i in range(10):
                assert entries[i].sequence == i


class TestWALSyncModes:
    """Test different sync modes."""

    def test_sync_always(self):
        """Test 'always' sync mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir, sync_mode="always")
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

            # Should be persisted
            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()
            assert len(entries) == 1

    def test_sync_periodic(self):
        """Test 'periodic' sync mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir, sync_mode="periodic", sync_interval_ms=100)
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

    def test_sync_os(self):
        """Test 'os' sync mode (default OS buffering)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir, sync_mode="os")
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

    def test_invalid_sync_mode(self):
        """Test that invalid sync mode raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError):
                WAL(tmpdir, sync_mode="invalid")


class TestWALCorruptionDetection:
    """Test corruption detection."""

    def test_crc_mismatch_detection(self):
        """Test that CRC mismatches are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

            # Corrupt the file
            wal_file = list(Path(tmpdir).glob("wal_*.log"))[0]
            with open(wal_file, "r+b") as f:
                f.seek(10)
                f.write(b"corrupted")

            # Try to read - should detect corruption
            wal2 = WAL(tmpdir)
            with pytest.raises(CorruptionError):
                list(wal2.iter_entries())
            wal2.close()

    def test_truncated_file_detection(self):
        """Test that truncated files are detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            wal.append(1, WriteOp.PUT, b"key", b"value")
            wal.close()

            # Truncate file
            wal_file = list(Path(tmpdir).glob("wal_*.log"))[0]
            with open(wal_file, "r+b") as f:
                f.truncate(5)

            # Try to read - should detect truncation
            wal2 = WAL(tmpdir)
            with pytest.raises(CorruptionError):
                list(wal2.iter_entries())
            wal2.close()


class TestWALContextManager:
    """Test context manager protocol."""

    def test_context_manager(self):
        """Test WAL works as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with WAL(tmpdir) as wal:
                wal.append(1, WriteOp.PUT, b"key", b"value")
            # Should be closed after context

            # Verify data persisted
            with WAL(tmpdir) as wal2:
                entries = list(wal2.iter_entries())
                assert len(entries) == 1


class TestWALEdgeCases:
    """Test edge cases."""

    def test_large_keys_and_values(self):
        """Test handling of large keys and values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            large_key = b"k" * 10000
            large_value = b"v" * 100000
            wal.append(1, WriteOp.PUT, large_key, large_value)
            wal.close()

            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            assert len(entries) == 1
            assert entries[0].key == large_key
            assert entries[0].value == large_value

    def test_many_small_entries(self):
        """Test handling many small entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            wal = WAL(tmpdir)
            for i in range(1000):
                wal.append(i, WriteOp.PUT, f"k{i}".encode(), f"v{i}".encode())
            wal.close()

            wal2 = WAL(tmpdir)
            entries = list(wal2.iter_entries())
            wal2.close()

            assert len(entries) == 1000
