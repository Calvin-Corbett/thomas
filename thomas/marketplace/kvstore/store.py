"""Main KV store implementation combining all components."""

import threading
from collections.abc import Iterator
from pathlib import Path

from thomas.marketplace.kvstore._exceptions import KeyNotFoundError, KVStoreError
from thomas.marketplace.kvstore._types import KVStoreConfig, WriteOp
from thomas.marketplace.kvstore.compaction import Compactor, LeveledCompactor
from thomas.marketplace.kvstore.iterators import MergeIterator
from thomas.marketplace.kvstore.manifest import Manifest
from thomas.marketplace.kvstore.memtable import Memtable
from thomas.marketplace.kvstore.sstable import SSTable, SSTableWriter
from thomas.marketplace.kvstore.wal import WAL


class KVStore:
    """A complete LSM-tree key-value store.

    Provides a durable key-value store with:
    - Write-ahead logging for crash recovery
    - In-memory memtable with skip list
    - Multi-level SSTables
    - Configurable compaction strategies
    - Range queries and snapshots
    """

    def __init__(self, config: KVStoreConfig | None = None):
        """Initialize KV store.

        Args:
            config: KVStoreConfig instance (uses defaults if None)
        """
        self.config = config or KVStoreConfig()
        self._validate_config()

        # Create data directory
        self.data_dir = Path(self.config.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.manifest = Manifest(str(self.data_dir))
        self.wal = WAL(
            str(self.data_dir / "wal"),
            rotation_size_mb=self.config.wal_rotation_size_mb,
            sync_mode=self.config.wal_sync_mode,
            sync_interval_ms=self.config.wal_sync_interval_ms,
        )

        self.memtable = Memtable(
            max_size_bytes=self.config.memtable_size_mb * 1024 * 1024,
            skiplist_max_level=self.config.memtable_skiplist_max_level,
        )

        self.compactor: Compactor = LeveledCompactor(
            str(self.data_dir),
            strategy=self.config.compaction_strategy,
            level_multiplier=self.config.compaction_level_multiplier,
        )

        self._sequence = self.manifest.sequence
        self._lock = threading.RLock()
        self._closed = False

        # Recovery
        self._recover_from_wal()

        # Compaction thread
        self._compaction_thread: threading.Thread | None = None
        self._compaction_stop = threading.Event()
        self._start_compaction_thread()

    def _validate_config(self) -> None:
        """Validate configuration."""
        try:
            # This will call __post_init__ validation
            self.config.bloom_filter_config.__post_init__()
        except ValueError as e:
            raise KVStoreError(f"Invalid config: {e}")

    def _recover_from_wal(self) -> None:
        """Recover state from WAL after crash.

        Replays all WAL entries into memtable.
        """
        try:
            wal_dir = self.data_dir / "wal"
            if not wal_dir.exists():
                return

            wal = WAL(str(wal_dir))
            for entry in wal.iter_entries():
                if entry.op == WriteOp.PUT:
                    self.memtable.put(entry.key, entry.value)
                else:  # DELETE
                    self.memtable.delete(entry.key)
                self._sequence = max(self._sequence, entry.sequence)
            wal.close()
        except Exception as e:
            raise KVStoreError(f"WAL recovery failed: {e}")

    def _start_compaction_thread(self) -> None:
        """Start background compaction thread."""
        self._compaction_thread = threading.Thread(target=self._compaction_loop, daemon=True)
        self._compaction_thread.start()

    def _compaction_loop(self) -> None:
        """Background compaction loop."""
        while not self._compaction_stop.is_set():
            try:
                with self._lock:
                    # Check if compaction needed
                    l0_files = self.manifest.get_level_files(0)
                    if len(l0_files) >= self.config.compaction_level0_file_count_threshold:
                        self.compactor.compact_level0()

                    # Check higher levels
                    for level in range(1, self.manifest.max_level() + 2):
                        if self.compactor.should_trigger_compaction(level):
                            self.compactor.compact_level(level)

            except Exception as e:
                print(f"Compaction error: {e}")

            # Sleep before next check
            self._compaction_stop.wait(1.0)

    def put(self, key: bytes, value: bytes) -> None:
        """Insert or update a key-value pair.

        Args:
            key: The key
            value: The value

        Raises:
            ValueError: If key or value is empty
            KVStoreError: If store is closed
        """
        if self._closed:
            raise KVStoreError("Store is closed")
        if not key or not value:
            raise ValueError("Key and value cannot be empty")

        with self._lock:
            self._sequence += 1

            # Write to WAL first
            self.wal.append(self._sequence, WriteOp.PUT, key, value)

            # Write to memtable
            self.memtable.put(key, value)

            # Check if flush needed
            if self.memtable.should_flush():
                self._flush_memtable()

    def delete(self, key: bytes) -> None:
        """Delete a key (tombstone).

        Args:
            key: The key to delete

        Raises:
            KVStoreError: If store is closed
        """
        if self._closed:
            raise KVStoreError("Store is closed")
        if not key:
            raise ValueError("Key cannot be empty")

        with self._lock:
            self._sequence += 1

            # Write to WAL
            self.wal.append(self._sequence, WriteOp.DELETE, key, None)

            # Write to memtable
            self.memtable.delete(key)

    def get(self, key: bytes) -> bytes:
        """Get a value by key.

        Args:
            key: The key to retrieve

        Returns:
            The value

        Raises:
            KeyNotFoundError: If key not found or is tombstoned
            KVStoreError: If store is closed
        """
        if self._closed:
            raise KVStoreError("Store is closed")
        if not key:
            raise ValueError("Key cannot be empty")

        with self._lock:
            # Check memtable first
            try:
                return self.memtable.get(key)
            except KeyError:
                pass

            # Check SSTables from newest to oldest
            for level in range(self.manifest.max_level(), -1, -1):
                files = self.manifest.get_level_files(level)
                for filename in reversed(files):  # Newest first
                    file_path = self.data_dir / filename
                    if file_path.exists():
                        try:
                            sstable = SSTable(str(file_path))
                            return sstable.get(key)
                        except KeyError:
                            continue

            raise KeyNotFoundError(key)

    def contains(self, key: bytes) -> bool:
        """Check if a key exists.

        Args:
            key: The key to check

        Returns:
            True if key exists and is not tombstoned
        """
        if self._closed:
            return False
        if not key:
            return False

        try:
            self.get(key)
            return True
        except KeyNotFoundError:
            return False

    def scan(self, start_key: bytes | None = None, end_key: bytes | None = None) -> Iterator[tuple[bytes, bytes]]:
        """Scan a range of keys.

        Args:
            start_key: Start of range (inclusive)
            end_key: End of range (exclusive)

        Yields:
            (key, value) tuples in sorted order

        Raises:
            KVStoreError: If store is closed
        """
        if self._closed:
            raise KVStoreError("Store is closed")

        with self._lock:
            # Collect iterators from all sources
            iterators = []

            # Memtable
            iterators.append(
                ((k, v, 0) for k, v in self.memtable.range_query(start_key, end_key, include_tombstones=True))
            )

            # SSTables
            for level in range(self.manifest.max_level(), -1, -1):
                files = self.manifest.get_level_files(level)
                for filename in files:
                    file_path = self.data_dir / filename
                    if file_path.exists():
                        sstable = SSTable(str(file_path))
                        iterators.append(
                            (entry.key, entry.value, entry.sequence)
                            for entry in sstable.iter_entries()
                            if (start_key is None or entry.key >= start_key)
                            and (end_key is None or entry.key < end_key)
                        )

            # Merge iterators, skip tombstones
            merger = MergeIterator(iterators, skip_tombstones=True)
            for key, value in merger:
                if value is not None:
                    yield (key, value)

    def _flush_memtable(self) -> None:
        """Flush memtable to SSTable."""
        if self.memtable.is_empty():
            return

        try:
            # Create SSTable filename
            seq = self.manifest.next_sequence()
            filename = f"sstable_L0_{seq}.db"
            file_path = self.data_dir / filename

            # Write SSTable
            with SSTableWriter(
                str(file_path), self.config.sstable_block_size_bytes, self.config.bloom_filter_config
            ) as writer:
                for key, value in self.memtable.iter_all():
                    if value is not None:  # Skip tombstones in SSTable
                        writer.add(key, value)

            # Update manifest
            self.manifest.add_sstable(0, filename)

            # Clear memtable
            self.memtable.clear()

        except Exception as e:
            raise KVStoreError(f"Memtable flush failed: {e}")

    def compact(self) -> None:
        """Trigger manual compaction of all levels.

        Useful for offline optimization.
        """
        if self._closed:
            raise KVStoreError("Store is closed")

        with self._lock:
            self.compactor.compact_all()

    def stats(self) -> dict:
        """Get store statistics.

        Returns:
            Dictionary with stats
        """
        with self._lock:
            level_sizes = self.compactor.get_level_sizes()
            memtable_size = self.memtable.size_bytes()

            return {
                "memtable_size_bytes": memtable_size,
                "memtable_entries": self.memtable.entry_count(),
                "levels": {
                    f"L{level}": {"files": len(self.manifest.get_level_files(level)), "size_bytes": size}
                    for level, size in level_sizes.items()
                },
                "sequence": self._sequence,
                "compaction_estimate_mb": self.compactor.estimate_compaction_work(),
            }

    def close(self) -> None:
        """Close the store and clean up resources."""
        if self._closed:
            return

        with self._lock:
            # Stop compaction
            self._compaction_stop.set()
            if self._compaction_thread:
                self._compaction_thread.join(timeout=5.0)

            # Flush memtable
            if not self.memtable.is_empty():
                self._flush_memtable()

            # Close WAL
            self.wal.close()

            self._closed = True

    def __enter__(self) -> "KVStore":
        """Context manager entry."""
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self):
        """Ensure cleanup on garbage collection."""
        self.close()
