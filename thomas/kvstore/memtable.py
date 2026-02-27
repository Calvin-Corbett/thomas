"""In-memory sorted table using skip list."""

from collections.abc import Iterator

from thomas.kvstore.skiplist import SkipList


class Memtable:
    """An in-memory sorted table for buffering writes before flushing to SSTable.

    Uses a skip list for O(log n) operations. Tracks approximate size and
    provides threshold-based flush triggers.
    """

    def __init__(self, max_size_bytes: int, skiplist_max_level: int = 16):
        """Initialize a memtable.

        Args:
            max_size_bytes: Soft size limit before flush is triggered
            skiplist_max_level: Max level for skip list
        """
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be positive")
        if skiplist_max_level < 1:
            raise ValueError("skiplist_max_level must be >= 1")

        self.max_size_bytes = max_size_bytes
        self.skiplist: SkipList = SkipList(max_level=skiplist_max_level)
        self._bytes_used = 0

    def put(self, key: bytes, value: bytes) -> None:
        """Insert or update a key-value pair.

        Args:
            key: The key
            value: The value

        Raises:
            ValueError: If key or value is empty
        """
        if not key:
            raise ValueError("Key cannot be empty")
        if not value:
            raise ValueError("Value cannot be empty")

        # Estimate size: overhead + key + value
        entry_overhead = 100  # Pointers, metadata
        estimated_size = entry_overhead + len(key) + len(value)

        # Check if key already exists to avoid double-counting
        try:
            old_value = self.skiplist.get(key)
            old_size = entry_overhead + len(key) + len(old_value)
            self._bytes_used -= old_size
        except KeyError:
            pass

        self.skiplist.insert(key, value)
        self._bytes_used += estimated_size

    def delete(self, key: bytes) -> None:
        """Mark a key for deletion (tombstone).

        Args:
            key: The key to delete
        """
        if not key:
            raise ValueError("Key cannot be empty")

        # If key exists, mark as tombstone
        if self.skiplist.contains_or_tombstone(key):
            self.skiplist.insert(key, None)
            # Tombstones take minimal space
            entry_overhead = 100
            self._bytes_used += entry_overhead

    def get(self, key: bytes) -> bytes | None:
        """Get a value by key.

        Args:
            key: The key to retrieve

        Returns:
            The value, or None if not found

        Raises:
            KeyError: If the key is not in the memtable
        """
        return self.skiplist.get(key)

    def contains(self, key: bytes) -> bool:
        """Check if a key exists and is not tombstoned.

        Args:
            key: The key to check

        Returns:
            True if key exists and is not tombstoned
        """
        return self.skiplist.contains(key)

    def contains_or_tombstone(self, key: bytes) -> bool:
        """Check if a key exists (including tombstones).

        Args:
            key: The key to check

        Returns:
            True if key exists (even if tombstoned)
        """
        return self.skiplist.contains_or_tombstone(key)

    def range_query(
        self, start_key: bytes | None = None, end_key: bytes | None = None, include_tombstones: bool = False
    ) -> Iterator[tuple[bytes, bytes | None]]:
        """Query a range of keys.

        Args:
            start_key: Start of range (inclusive, None for -inf)
            end_key: End of range (exclusive, None for +inf)
            include_tombstones: If True, include tombstoned entries

        Yields:
            (key, value) tuples in sorted order
        """
        return self.skiplist.range_query(start_key=start_key, end_key=end_key, include_tombstones=include_tombstones)

    def iter_all(self, include_tombstones: bool = False) -> Iterator[tuple[bytes, bytes | None]]:
        """Iterate all entries in sorted order.

        Args:
            include_tombstones: If True, include tombstoned entries

        Yields:
            (key, value) tuples
        """
        return self.skiplist.iter_all(include_tombstones=include_tombstones)

    def should_flush(self) -> bool:
        """Check if memtable has exceeded size threshold.

        Returns:
            True if the memtable should be flushed
        """
        return self._bytes_used >= self.max_size_bytes

    def size_bytes(self) -> int:
        """Get approximate size in bytes.

        Returns:
            Approximate size including overhead
        """
        return self._bytes_used

    def entry_count(self) -> int:
        """Get number of entries (including tombstones).

        Returns:
            Number of entries
        """
        return len(self.skiplist)

    def clear(self) -> None:
        """Clear all entries."""
        self.skiplist.clear()
        self._bytes_used = 0

    def is_empty(self) -> bool:
        """Check if memtable is empty.

        Returns:
            True if no entries
        """
        return len(self.skiplist) == 0

    def min_key(self) -> bytes | None:
        """Get minimum key, or None if empty.

        Returns:
            The minimum key
        """
        return self.skiplist.min_key()

    def max_key(self) -> bytes | None:
        """Get maximum key, or None if empty.

        Returns:
            The maximum key
        """
        return self.skiplist.max_key()
