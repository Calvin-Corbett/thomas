"""Merge iterators for combining multiple sorted sources."""

import heapq
from collections.abc import Iterator
from typing import Any, Protocol


class Comparable(Protocol):
    """Protocol for comparable items."""

    def __lt__(self, other: Any) -> bool: ...
    def __eq__(self, other: Any) -> bool: ...
    def __le__(self, other: Any) -> bool: ...


class MergeIterator:
    """Merges multiple sorted iterators into a single sorted stream.

    Handles deduplication (keeps latest version by sequence number) and
    tombstone cleanup. Uses a min-heap for efficient merging.
    """

    def __init__(self, iterators: list[Iterator[tuple[bytes, bytes | None, int]]], skip_tombstones: bool = False):
        """Initialize merge iterator.

        Each source iterator yields tuples of (key, value, sequence_number).
        Later iterators (higher indices) are assumed to be fresher data.

        Args:
            iterators: List of iterators over (key, value, sequence) tuples
            skip_tombstones: If True, don't yield tombstoned entries
        """
        self.skip_tombstones = skip_tombstones
        self.iterators = iterators
        self.heap: list[tuple[bytes, int, int, bytes | None, int]] = []
        self._current_key: bytes | None = None
        self._exhausted = set()

        # Initialize heap with first element from each iterator
        for iter_idx, it in enumerate(iterators):
            self._advance(iter_idx)

        heapq.heapify(self.heap)

    def _advance(self, iter_idx: int) -> None:
        """Get next element from iterator and add to heap.

        Args:
            iter_idx: Index of iterator to advance
        """
        try:
            key, value, sequence = next(self.iterators[iter_idx])
            # Heap item: (key, -iter_idx for reverse order, sequence, value, iter_idx)
            # Using -iter_idx ensures later iterators take precedence on tie
            heapq.heappush(self.heap, (key, -iter_idx, sequence, value, iter_idx))
        except StopIteration:
            self._exhausted.add(iter_idx)

    def __iter__(self) -> "MergeIterator":
        """Return iterator."""
        return self

    def __next__(self) -> tuple[bytes, bytes | None]:
        """Get next deduplicated entry.

        Returns:
            (key, value) tuple where value is None for tombstones

        Raises:
            StopIteration: When all sources exhausted
        """
        while self.heap:
            key, _, sequence, value, iter_idx = heapq.heappop(self.heap)

            # Advance this iterator
            self._advance(iter_idx)

            # Skip if we just saw this key (deduplication)
            if key == self._current_key:
                continue

            self._current_key = key

            # Skip tombstones if requested
            if self.skip_tombstones and value is None:
                continue

            return (key, value)

        raise StopIteration


class RangeMergeIterator:
    """Merge iterator with range support for compaction.

    Merges multiple sorted ranges and applies key filtering.
    """

    def __init__(
        self,
        sources: list[Iterator[tuple[bytes, bytes | None]]],
        start_key: bytes | None = None,
        end_key: bytes | None = None,
        skip_tombstones: bool = False,
    ):
        """Initialize range merge iterator.

        Args:
            sources: List of iterators over (key, value) tuples
            start_key: Start of range (inclusive)
            end_key: End of range (exclusive)
            skip_tombstones: If True, skip tombstoned entries
        """
        self.sources = sources
        self.start_key = start_key
        self.end_key = end_key
        self.skip_tombstones = skip_tombstones
        self.heap: list[tuple[bytes, int, bytes | None, int]] = []
        self._current_key: bytes | None = None
        self._exhausted = set()

        # Initialize heap
        for idx, source in enumerate(sources):
            self._advance(idx)

        heapq.heapify(self.heap)

    def _advance(self, source_idx: int) -> None:
        """Get next element from source."""
        try:
            key, value = next(self.sources[source_idx])

            # Check if in range
            if self.start_key is not None and key < self.start_key:
                # Skip and try next
                self._advance(source_idx)
                return

            if self.end_key is not None and key >= self.end_key:
                self._exhausted.add(source_idx)
                return

            heapq.heappush(self.heap, (key, source_idx, value, source_idx))
        except StopIteration:
            self._exhausted.add(source_idx)

    def __iter__(self) -> "RangeMergeIterator":
        return self

    def __next__(self) -> tuple[bytes, bytes | None]:
        """Get next deduplicated entry in range.

        Returns:
            (key, value) tuple

        Raises:
            StopIteration: When done
        """
        while self.heap:
            key, _, value, source_idx = heapq.heappop(self.heap)

            # Check end of range
            if self.end_key is not None and key >= self.end_key:
                raise StopIteration

            # Advance source
            self._advance(source_idx)

            # Deduplication
            if key == self._current_key:
                continue

            self._current_key = key

            # Skip tombstones
            if self.skip_tombstones and value is None:
                continue

            return (key, value)

        raise StopIteration


class ConcatenatingIterator:
    """Concatenate multiple iterators in sequence."""

    def __init__(self, iterators: list[Iterator]):
        """Initialize with iterators to concatenate.

        Args:
            iterators: Iterators to chain together
        """
        self.iterators = iterators
        self.current_iter_idx = 0

    def __iter__(self) -> "ConcatenatingIterator":
        return self

    def __next__(self):
        """Get next element from concatenated sequence.

        Raises:
            StopIteration: When all exhausted
        """
        while self.current_iter_idx < len(self.iterators):
            try:
                return next(self.iterators[self.current_iter_idx])
            except StopIteration:
                self.current_iter_idx += 1

        raise StopIteration
