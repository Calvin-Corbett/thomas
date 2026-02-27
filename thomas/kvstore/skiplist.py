"""Skip list implementation for sorted in-memory storage."""

import random
from collections.abc import Iterator


class SkipListNode:
    """A node in the skip list."""

    def __init__(self, key: bytes, value: bytes | None, level: int):
        """Initialize a skip list node.

        Args:
            key: The key stored in this node
            value: The value (or None for tombstones)
            level: The level of this node (0-indexed)
        """
        self.key = key
        self.value = value
        self.level = level
        self.forward: list[SkipListNode | None] = [None] * (level + 1)


class SkipList:
    """A probabilistic skip list for O(log n) sorted operations.

    This is the core data structure for memtable storage. Supports:
    - O(log n) insert, search, delete
    - O(log n) range queries
    - Iteration in sorted order
    """

    def __init__(self, max_level: int = 16, probability: float = 0.5):
        """Initialize an empty skip list.

        Args:
            max_level: Maximum level (must be >= 0)
            probability: Probability for level increases (typically 0.5)
        """
        if max_level < 0:
            raise ValueError("max_level must be >= 0")
        if not 0 < probability <= 1:
            raise ValueError("probability must be in (0, 1]")

        self.max_level = max_level
        self.probability = probability
        self.level = 0
        self.header = SkipListNode(b"", None, max_level)
        self.size = 0

    def _random_level(self) -> int:
        """Generate a random level for a new node.

        Returns:
            A level between 0 and max_level
        """
        lvl = 0
        while random.random() < self.probability and lvl < self.max_level:
            lvl += 1
        return lvl

    def insert(self, key: bytes, value: bytes | None) -> None:
        """Insert or update a key-value pair.

        Args:
            key: The key to insert
            value: The value (None indicates a tombstone)
        """
        if not key:
            raise ValueError("Key cannot be empty")

        new_level = self._random_level()
        if new_level > self.level:
            # Extend header with new levels
            for _ in range(self.level + 1, new_level + 1):
                self.header.forward.append(None)
            self.level = new_level

        # Find insertion point
        update = [None] * (self.level + 1)
        x = self.header

        for i in range(self.level, -1, -1):
            while x.forward[i] is not None and x.forward[i].key < key:
                x = x.forward[i]
            update[i] = x

        # Check if key already exists
        if x.forward[0] is not None and x.forward[0].key == key:
            x.forward[0].value = value
            return

        # Create new node and link it
        new_node = SkipListNode(key, value, new_level)
        self.size += 1

        for i in range(min(new_level + 1, self.level + 1)):
            new_node.forward[i] = update[i].forward[i]
            update[i].forward[i] = new_node

    def get(self, key: bytes) -> bytes | None:
        """Get a value by key.

        Args:
            key: The key to search for

        Returns:
            The value, or None if not found (or if tombstoned)

        Raises:
            KeyError: If the key is not in the skip list
        """
        x = self.header
        for i in range(self.level, -1, -1):
            while x.forward[i] is not None and x.forward[i].key < key:
                x = x.forward[i]

        x = x.forward[0]
        if x is not None and x.key == key:
            if x.value is None:
                raise KeyError(key)
            return x.value

        raise KeyError(key)

    def contains(self, key: bytes) -> bool:
        """Check if a key exists and is not tombstoned.

        Args:
            key: The key to check

        Returns:
            True if the key exists and is not tombstoned
        """
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    def contains_or_tombstone(self, key: bytes) -> bool:
        """Check if a key exists (including as a tombstone).

        Args:
            key: The key to check

        Returns:
            True if the key exists (even if tombstoned)
        """
        x = self.header
        for i in range(self.level, -1, -1):
            while x.forward[i] is not None and x.forward[i].key < key:
                x = x.forward[i]

        x = x.forward[0]
        return x is not None and x.key == key

    def delete(self, key: bytes) -> bool:
        """Delete a key (marks as tombstone, doesn't remove).

        Args:
            key: The key to delete

        Returns:
            True if the key was found and marked for deletion
        """
        x = self.header
        update = [None] * (self.level + 1)

        for i in range(self.level, -1, -1):
            while x.forward[i] is not None and x.forward[i].key < key:
                x = x.forward[i]
            update[i] = x

        x = x.forward[0]
        if x is None or x.key != key:
            return False

        # Mark as tombstone
        x.value = None
        return True

    def range_query(
        self, start_key: bytes | None = None, end_key: bytes | None = None, include_tombstones: bool = False
    ) -> Iterator[tuple[bytes, bytes | None]]:
        """Iterate over keys in range [start_key, end_key).

        Args:
            start_key: Start of range (inclusive, None for -inf)
            end_key: End of range (exclusive, None for +inf)
            include_tombstones: If True, yield tombstoned entries

        Yields:
            (key, value) tuples in sorted order
        """
        # Find starting position
        x = self.header
        if start_key is None:
            x = x.forward[0]
        else:
            for i in range(self.level, -1, -1):
                while x.forward[i] is not None and x.forward[i].key < start_key:
                    x = x.forward[i]
            x = x.forward[0]
            if x is not None and x.key == start_key:
                pass  # x is at start_key
            elif x is not None and x.key > start_key:
                pass  # x is at first key > start_key
            else:
                return  # Nothing in range

        # Iterate until end_key
        while x is not None:
            if end_key is not None and x.key >= end_key:
                break

            if include_tombstones or x.value is not None:
                yield (x.key, x.value)

            x = x.forward[0]

    def iter_all(self, include_tombstones: bool = False) -> Iterator[tuple[bytes, bytes | None]]:
        """Iterate all entries in sorted order.

        Args:
            include_tombstones: If True, yield tombstoned entries

        Yields:
            (key, value) tuples in sorted order
        """
        x = self.header.forward[0]
        while x is not None:
            if include_tombstones or x.value is not None:
                yield (x.key, x.value)
            x = x.forward[0]

    def __len__(self) -> int:
        """Return approximate size (includes tombstones)."""
        return self.size

    def __bool__(self) -> bool:
        """Return True if not empty."""
        return self.size > 0

    def __contains__(self, key: object) -> bool:
        """Support `key in skiplist` membership checks."""
        if not isinstance(key, (bytes, bytearray)):
            return False
        return self.contains(bytes(key))

    def __iter__(self) -> Iterator[bytes]:
        """Iterate keys in sorted order (excluding tombstones)."""
        for key, _ in self.iter_all(include_tombstones=False):
            yield key

    def clear(self) -> None:
        """Clear all entries."""
        self.level = 0
        self.size = 0
        self.header.forward = [None] * (self.max_level + 1)

    def min_key(self) -> bytes | None:
        """Get the minimum key, or None if empty."""
        node = self.header.forward[0]
        return node.key if node is not None else None

    def max_key(self) -> bytes | None:
        """Get the maximum key by traversing to the end."""
        x = self.header
        for i in range(self.level, -1, -1):
            while x.forward[i] is not None:
                x = x.forward[i]
        return x.key if x != self.header else None
