"""
Write-Ahead Logging (WAL) for crash recovery.

This module implements:
- Log record types (INSERT, UPDATE, DELETE, COMMIT, ABORT, CHECKPOINT)
- Log buffer with force-on-commit strategy
- ARIES-style recovery (analysis, redo, undo phases)
- LSN tracking and log truncation
- Checkpoint mechanism (fuzzy checkpoint)
- Crash recovery simulation
"""

import time
from dataclasses import dataclass, field

from ._types import LogRecord


@dataclass
class CheckpointRecord:
    """Checkpoint record for crash recovery."""

    lsn: int
    timestamp: float = 0.0
    dirty_pages: set[int] = field(default_factory=set)
    active_transactions: list[int] = field(default_factory=list)


class WriteAheadLog:
    """
    Write-Ahead Logging for durability and crash recovery.

    Implements ARIES recovery algorithm:
    - Analysis phase: discover state at crash
    - Redo phase: replay all committed transactions
    - Undo phase: rollback uncommitted transactions
    """

    def __init__(self, buffer_size: int = 1000) -> None:
        """
        Initialize WAL.

        Args:
            buffer_size: Size of log buffer in records
        """
        self.buffer_size = buffer_size
        self.log_records: list[LogRecord] = []
        self.log_buffer: list[LogRecord] = []
        self.next_lsn = 0
        self.flushed_lsn = 0
        self.checkpoint_lsn = 0
        self.dirty_pages: set[int] = set()
        self.transaction_table: dict[int, int] = {}  # txn_id -> last_lsn
        self.checkpoint_records: list[CheckpointRecord] = []

    def append_record(
        self,
        transaction_id: int,
        record_type: str,
        table_id: int | None = None,
        page_id: int | None = None,
        slot_id: int | None = None,
        before_image: bytes | None = None,
        after_image: bytes | None = None,
    ) -> int:
        """
        Append a log record.

        Args:
            transaction_id: Transaction ID
            record_type: Type of record (INSERT, UPDATE, DELETE, COMMIT, ABORT, CHECKPOINT)
            table_id: Table ID
            page_id: Page ID
            slot_id: Slot ID
            before_image: Before image of record
            after_image: After image of record

        Returns:
            LSN of the record
        """
        lsn = self.next_lsn
        self.next_lsn += 1

        record = LogRecord(
            lsn=lsn,
            transaction_id=transaction_id,
            record_type=record_type,
            table_id=table_id,
            page_id=page_id,
            slot_id=slot_id,
            before_image=before_image,
            after_image=after_image,
            timestamp=time.time(),
            prev_lsn=self.transaction_table.get(transaction_id),
        )

        self.log_buffer.append(record)
        self.transaction_table[transaction_id] = lsn

        # Track dirty pages
        if page_id is not None and record_type in ["INSERT", "UPDATE", "DELETE"]:
            self.dirty_pages.add(page_id)

        # Auto-flush if buffer full
        if len(self.log_buffer) >= self.buffer_size:
            self.flush()

        return lsn

    def flush(self) -> None:
        """Flush log buffer to disk."""
        if not self.log_buffer:
            return

        # In real implementation, would write to disk
        self.log_records.extend(self.log_buffer)
        self.flushed_lsn = self.next_lsn - 1
        self.log_buffer.clear()

    def force_flush(self) -> None:
        """Force flush log buffer (for commit)."""
        self.flush()

    def create_checkpoint(
        self,
        active_transactions: list[int],
    ) -> int:
        """
        Create a checkpoint.

        Args:
            active_transactions: List of active transaction IDs

        Returns:
            Checkpoint LSN

        Raises:
            CheckpointException: If checkpoint fails
        """
        # Flush all pending records
        self.flush()

        checkpoint_lsn = self.next_lsn
        checkpoint = CheckpointRecord(
            lsn=checkpoint_lsn,
            timestamp=time.time(),
            dirty_pages=set(self.dirty_pages),
            active_transactions=active_transactions,
        )

        # Append checkpoint record
        record = LogRecord(
            lsn=checkpoint_lsn,
            transaction_id=0,
            record_type="CHECKPOINT",
            timestamp=checkpoint.timestamp,
        )

        self.log_records.append(record)
        self.checkpoint_records.append(checkpoint)
        self.checkpoint_lsn = checkpoint_lsn
        self.next_lsn += 1

        return checkpoint_lsn

    def recover(self) -> tuple[list[LogRecord], list[LogRecord]]:
        """
        Recover from crash using ARIES algorithm.

        Returns:
            (redo_log, undo_log) - records to redo and undo

        Raises:
            RecoveryException: If recovery fails
        """
        # Phase 1: Analysis
        redo_log, undo_log = self._analyze_recovery_point()

        # Phase 2: Redo (would replay changes)
        # Phase 3: Undo (would rollback uncommitted)

        return redo_log, undo_log

    def _analyze_recovery_point(self) -> tuple[list[LogRecord], list[LogRecord]]:
        """
        Analyze phase of ARIES recovery.

        Returns:
            (redo_log, undo_log)
        """
        # Find latest checkpoint
        if not self.checkpoint_records:
            redo_start = 0
        else:
            last_checkpoint = self.checkpoint_records[-1]
            redo_start = last_checkpoint.lsn

        # Collect all records after checkpoint (flushed + buffered).
        all_records = self._all_records()
        redo_log = [r for r in all_records if r.lsn >= redo_start]

        # Determine which transactions were active
        active_txns = set()
        committed_txns = set()
        aborted_txns = set()

        for record in redo_log:
            if record.transaction_id > 0:
                if record.record_type == "COMMIT":
                    committed_txns.add(record.transaction_id)
                    active_txns.discard(record.transaction_id)
                elif record.record_type == "ABORT":
                    aborted_txns.add(record.transaction_id)
                    active_txns.discard(record.transaction_id)
                else:
                    active_txns.add(record.transaction_id)

        # Undo log contains records from uncommitted transactions
        undo_log = [r for r in reversed(redo_log) if r.transaction_id in active_txns and r.before_image is not None]

        return redo_log, undo_log

    def truncate_log(self, up_to_lsn: int) -> None:
        """
        Truncate log up to given LSN.

        Args:
            up_to_lsn: LSN to truncate up to
        """
        self.log_records = [r for r in self.log_records if r.lsn > up_to_lsn]
        self.log_buffer = [r for r in self.log_buffer if r.lsn > up_to_lsn]

        # Rebuild transaction table after truncation.
        self.transaction_table.clear()
        for record in self._all_records():
            if record.transaction_id > 0:
                self.transaction_table[record.transaction_id] = record.lsn

    def _all_records(self) -> list[LogRecord]:
        """Return all WAL records (flushed + buffered) ordered by LSN."""
        if not self.log_buffer:
            return list(self.log_records)

        return sorted(
            [*self.log_records, *self.log_buffer],
            key=lambda record: record.lsn,
        )

    def get_log_record(self, lsn: int) -> LogRecord | None:
        """Get a log record by LSN."""
        for record in self.log_buffer:
            if record.lsn == lsn:
                return record

        for record in self.log_records:
            if record.lsn == lsn:
                return record
        return None

    def get_transaction_log(self, transaction_id: int) -> list[LogRecord]:
        """Get all log records for a transaction."""
        records = []
        current_lsn = self.transaction_table.get(transaction_id)

        while current_lsn is not None:
            record = self.get_log_record(current_lsn)
            if record is None:
                break

            records.append(record)
            current_lsn = record.prev_lsn

        return list(reversed(records))

    def get_statistics(self) -> dict[str, int]:
        """Get WAL statistics."""
        return {
            "total_records": len(self.log_records) + len(self.log_buffer),
            "next_lsn": self.next_lsn,
            "flushed_lsn": self.flushed_lsn,
            "checkpoint_lsn": self.checkpoint_lsn,
            "buffer_size": len(self.log_buffer),
            "dirty_pages": len(self.dirty_pages),
            "num_checkpoints": len(self.checkpoint_records),
        }


class RecoveryManager:
    """Manages crash recovery process."""

    def __init__(self, wal: WriteAheadLog) -> None:
        """Initialize recovery manager."""
        self.wal = wal

    def perform_recovery(self) -> dict[str, any]:
        """
        Perform complete crash recovery.

        Returns:
            Recovery statistics
        """
        start_time = time.time()

        # Phase 1: Analysis
        redo_log, undo_log = self.wal.recover()

        # Phase 2: Redo - in real system would replay to storage
        redo_count = len(redo_log)

        # Phase 3: Undo - in real system would rollback changes
        undo_count = len(undo_log)

        elapsed = time.time() - start_time

        return {
            "status": "SUCCESS",
            "redo_count": redo_count,
            "undo_count": undo_count,
            "elapsed_ms": elapsed * 1000,
            "recovery_point_lsn": self.wal.checkpoint_lsn,
        }

    def redo_log_records(self, records: list[LogRecord]) -> int:
        """
        Redo a list of log records.

        Args:
            records: Log records to redo

        Returns:
            Number of records redone
        """
        count = 0
        for record in records:
            if record.record_type == "INSERT":
                # Reinsert record
                count += 1
            elif record.record_type == "UPDATE":
                # Reapply update
                count += 1
            elif record.record_type == "DELETE":
                # Redelete record
                count += 1

        return count

    def undo_log_records(self, records: list[LogRecord]) -> int:
        """
        Undo a list of log records.

        Args:
            records: Log records to undo (should be in reverse order)

        Returns:
            Number of records undone
        """
        count = 0
        for record in records:
            if record.before_image is None:
                continue

            if record.record_type == "INSERT":
                # Delete inserted record
                count += 1
            elif record.record_type == "UPDATE":
                # Restore before image
                count += 1
            elif record.record_type == "DELETE":
                # Restore deleted record
                count += 1

        return count


class CheckpointManager:
    """Manages checkpoint operations."""

    def __init__(self, wal: WriteAheadLog, checkpoint_interval: int = 1000) -> None:
        """
        Initialize checkpoint manager.

        Args:
            wal: Write-ahead log
            checkpoint_interval: Checkpoint every N records
        """
        self.wal = wal
        self.checkpoint_interval = checkpoint_interval
        self.records_since_checkpoint = 0

    def should_checkpoint(self) -> bool:
        """Check if checkpoint should be triggered."""
        return self.records_since_checkpoint >= self.checkpoint_interval

    def do_checkpoint(self, active_transactions: list[int]) -> int:
        """
        Perform a checkpoint.

        Args:
            active_transactions: List of active transaction IDs

        Returns:
            Checkpoint LSN
        """
        checkpoint_lsn = self.wal.create_checkpoint(active_transactions)
        self.records_since_checkpoint = 0
        return checkpoint_lsn

    def record_log_entry(self) -> None:
        """Record that a log entry was added."""
        self.records_since_checkpoint += 1
