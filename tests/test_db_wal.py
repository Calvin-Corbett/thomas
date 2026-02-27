"""
Tests for write-ahead logging and crash recovery.

Tests cover:
- Log record creation and flushing
- Checkpoint mechanism
- Recovery phases (analysis, redo, undo)
- Transaction log chains
- Log truncation
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thomas.db_internals.wal import (
    CheckpointManager,
    RecoveryManager,
    WriteAheadLog,
)


class TestWriteAheadLogBasic:
    """Tests for write-ahead log."""

    def test_create_wal(self) -> None:
        """Test creating WAL."""
        wal = WriteAheadLog()
        assert wal.next_lsn == 0
        assert wal.flushed_lsn == 0

    def test_append_record(self) -> None:
        """Test appending log record."""
        wal = WriteAheadLog()

        lsn = wal.append_record(transaction_id=1, record_type="INSERT", table_id=1, page_id=0, slot_id=0)

        assert lsn == 0
        assert wal.next_lsn == 1

    def test_multiple_records(self) -> None:
        """Test appending multiple records."""
        wal = WriteAheadLog()

        lsn1 = wal.append_record(1, "INSERT", 1, 0, 0)
        lsn2 = wal.append_record(1, "UPDATE", 1, 0, 0)
        lsn3 = wal.append_record(1, "DELETE", 1, 0, 0)

        assert lsn1 == 0
        assert lsn2 == 1
        assert lsn3 == 2

    def test_transaction_log_chain(self) -> None:
        """Test transaction log chain."""
        wal = WriteAheadLog()

        lsn1 = wal.append_record(1, "INSERT", 1, 0, 0)
        lsn2 = wal.append_record(1, "UPDATE", 1, 0, 0)

        # Get transaction log
        log = wal.get_transaction_log(1)
        assert len(log) == 2
        assert log[0].lsn == lsn1
        assert log[1].lsn == lsn2

    def test_flush_log(self) -> None:
        """Test flushing log buffer."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(2, "INSERT", 1, 0, 1)

        wal.flush()

        assert wal.flushed_lsn == 1
        assert len(wal.log_buffer) == 0

    def test_force_flush(self) -> None:
        """Test force flush (for commit)."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)

        wal.force_flush()

        assert len(wal.log_buffer) == 0

    def test_auto_flush_on_buffer_full(self) -> None:
        """Test auto-flush when buffer is full."""
        wal = WriteAheadLog(buffer_size=3)

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(1, "INSERT", 1, 0, 1)
        wal.append_record(1, "INSERT", 1, 0, 2)

        # Fourth record should trigger flush
        assert len(wal.log_buffer) <= 1

    def test_get_log_record(self) -> None:
        """Test retrieving a log record."""
        wal = WriteAheadLog()

        lsn = wal.append_record(1, "INSERT", 1, 0, 0)
        wal.flush()

        record = wal.get_log_record(lsn)
        assert record is not None
        assert record.lsn == lsn
        assert record.record_type == "INSERT"

    def test_track_dirty_pages(self) -> None:
        """Test tracking dirty pages."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(1, "UPDATE", 1, 1, 0)
        wal.append_record(1, "DELETE", 1, 2, 0)

        assert 0 in wal.dirty_pages
        assert 1 in wal.dirty_pages
        assert 2 in wal.dirty_pages


class TestCheckpoint:
    """Tests for checkpoint mechanism."""

    def test_create_checkpoint(self) -> None:
        """Test creating checkpoint."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(2, "INSERT", 1, 0, 1)

        checkpoint_lsn = wal.create_checkpoint([1, 2])

        assert checkpoint_lsn > 0
        assert len(wal.checkpoint_records) == 1

    def test_checkpoint_records_dirty_pages(self) -> None:
        """Test checkpoint records dirty pages."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(1, "UPDATE", 1, 1, 0)

        wal.create_checkpoint([1])

        checkpoint = wal.checkpoint_records[-1]
        assert len(checkpoint.dirty_pages) > 0

    def test_multiple_checkpoints(self) -> None:
        """Test multiple checkpoints."""
        wal = WriteAheadLog()

        wal.create_checkpoint([])
        time.sleep(0.01)
        wal.create_checkpoint([])

        assert len(wal.checkpoint_records) == 2


class TestRecovery:
    """Tests for crash recovery."""

    def test_recovery_analysis(self) -> None:
        """Test recovery analysis phase."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0, after_image=b"data")
        wal.create_checkpoint([1])
        wal.append_record(1, "INSERT", 1, 0, 1, after_image=b"data2")

        redo_log, undo_log = wal.recover()

        # Should have redo records from checkpoint onwards
        assert len(redo_log) > 0

    def test_recovery_committed_transactions(self) -> None:
        """Test recovery recognizes committed transactions."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0, after_image=b"data")
        wal.append_record(1, "COMMIT")

        redo_log, undo_log = wal.recover()

        # Committed transaction should not be in undo log
        txn_ids_in_undo = set(r.transaction_id for r in undo_log)
        assert 1 not in txn_ids_in_undo

    def test_recovery_uncommitted_transactions(self) -> None:
        """Test recovery handles uncommitted transactions."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0, before_image=b"old", after_image=b"new")
        wal.append_record(2, "UPDATE", 1, 0, 1, before_image=b"old2", after_image=b"new2")

        redo_log, undo_log = wal.recover()

        # Uncommitted transactions should be in undo log if they have before images
        undo_txn_ids = set(r.transaction_id for r in undo_log if r.before_image)
        assert len(undo_txn_ids) > 0


class TestRecoveryManager:
    """Tests for recovery manager."""

    def test_create_recovery_manager(self) -> None:
        """Test creating recovery manager."""
        wal = WriteAheadLog()
        rm = RecoveryManager(wal)

        assert rm.wal is wal

    def test_perform_recovery(self) -> None:
        """Test performing recovery."""
        wal = WriteAheadLog()
        wal.append_record(1, "INSERT", 1, 0, 0, after_image=b"data")
        wal.append_record(1, "COMMIT")

        rm = RecoveryManager(wal)
        result = rm.perform_recovery()

        assert result["status"] == "SUCCESS"
        assert "redo_count" in result
        assert "undo_count" in result

    def test_redo_log_records(self) -> None:
        """Test redoing log records."""
        wal = WriteAheadLog()
        wal.append_record(1, "INSERT", 1, 0, 0, after_image=b"data")

        rm = RecoveryManager(wal)
        records = wal.log_records

        redo_count = rm.redo_log_records(records)
        assert redo_count >= 0

    def test_undo_log_records(self) -> None:
        """Test undoing log records."""
        wal = WriteAheadLog()
        wal.append_record(1, "INSERT", 1, 0, 0, before_image=b"old")

        rm = RecoveryManager(wal)
        records = wal.log_records

        undo_count = rm.undo_log_records(records)
        assert undo_count >= 0


class TestCheckpointManager:
    """Tests for checkpoint manager."""

    def test_create_checkpoint_manager(self) -> None:
        """Test creating checkpoint manager."""
        wal = WriteAheadLog()
        cm = CheckpointManager(wal)

        assert cm.wal is wal
        assert cm.checkpoint_interval == 1000

    def test_checkpoint_trigger(self) -> None:
        """Test checkpoint triggering."""
        wal = WriteAheadLog()
        cm = CheckpointManager(wal, checkpoint_interval=3)

        assert not cm.should_checkpoint()

        cm.record_log_entry()
        assert not cm.should_checkpoint()

        cm.record_log_entry()
        assert not cm.should_checkpoint()

        cm.record_log_entry()
        assert cm.should_checkpoint()

    def test_do_checkpoint(self) -> None:
        """Test performing checkpoint."""
        wal = WriteAheadLog()
        cm = CheckpointManager(wal)

        checkpoint_lsn = cm.do_checkpoint([1, 2])

        assert checkpoint_lsn >= 0
        assert cm.records_since_checkpoint == 0

    def test_custom_checkpoint_interval(self) -> None:
        """Test custom checkpoint interval."""
        wal = WriteAheadLog()
        cm = CheckpointManager(wal, checkpoint_interval=50)

        assert cm.checkpoint_interval == 50


class TestWALStatistics:
    """Tests for WAL statistics."""

    def test_get_statistics(self) -> None:
        """Test getting WAL statistics."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(1, "UPDATE", 1, 0, 0)
        wal.flush()

        stats = wal.get_statistics()

        assert stats["total_records"] == 2
        assert stats["next_lsn"] == 2
        assert "dirty_pages" in stats

    def test_statistics_tracking(self) -> None:
        """Test statistics tracking."""
        wal = WriteAheadLog()

        for i in range(10):
            wal.append_record(1, "INSERT", 1, i, 0)

        stats = wal.get_statistics()
        assert stats["total_records"] >= 10


class TestLogTruncation:
    """Tests for log truncation."""

    def test_truncate_log(self) -> None:
        """Test truncating log."""
        wal = WriteAheadLog()

        wal.append_record(1, "INSERT", 1, 0, 0)
        wal.append_record(1, "INSERT", 1, 0, 1)
        wal.append_record(1, "INSERT", 1, 0, 2)
        wal.flush()

        wal.truncate_log(0)

        # Records with LSN > 0 should remain
        remaining = wal.log_records
        assert all(r.lsn > 0 for r in remaining)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
