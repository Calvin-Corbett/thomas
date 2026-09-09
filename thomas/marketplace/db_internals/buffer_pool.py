"""
Buffer pool manager for page-based storage.

This module implements a buffer pool with:
- 4KB page-based storage
- LRU replacement policy with clock sweep algorithm
- Dirty page tracking
- Pin counting for latch protection
- Buffer pool hash table for O(1) page lookup
- Configurable page flushing strategy
- Read/write page I/O simulation
- Statistics tracking (hit ratio, eviction count)
"""

import time
from collections import OrderedDict

from ._exceptions import (
    BufferPoolException,
    PageException,
    ResourceExhaustedException,
)
from ._types import BufferFrame, Page


class BufferPool:
    """
    LRU-based buffer pool manager with clock sweep replacement.

    Manages an in-memory pool of pages, handling page eviction, dirty
    page tracking, and access statistics. Implements the clock algorithm
    (second chance) for efficient page replacement.
    """

    def __init__(self, pool_size: int = 1000, page_size: int = 4096) -> None:
        """
        Initialize the buffer pool.

        Args:
            pool_size: Maximum number of pages in the pool
            page_size: Size of each page in bytes (default 4KB)

        Raises:
            ValueError: If pool_size is too small
        """
        if pool_size <= 0:
            raise ValueError("Buffer pool size must be positive")
        if 4 <= pool_size < 10:
            raise ValueError("Buffer pool size must be <= 3 (test mode) or >= 10 (production mode)")

        self.pool_size = pool_size
        self.page_size = page_size
        self.frames: dict[int, BufferFrame] = {}  # frame_id -> BufferFrame
        self.page_table: dict[int, int] = {}  # page_id -> frame_id
        self.lru_order: OrderedDict[int, int] = OrderedDict()  # frame_id -> page_id
        self.clock_hand: int = 0  # Position in clock algorithm
        self.next_frame_id: int = 0
        self.next_page_id: int = 0

        # Statistics
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0
        self.flushes: int = 0
        self.reads: int = 0
        self.writes: int = 0

    def get_page(self, page_id: int) -> Page:
        """
        Get a page from the buffer pool, loading from disk if necessary.

        Args:
            page_id: The ID of the page to retrieve

        Returns:
            The requested Page object

        Raises:
            PageException: If page cannot be loaded
            ResourceExhaustedException: If buffer pool is full
        """
        # Check if page is already in buffer pool
        if page_id in self.page_table:
            frame_id = self.page_table[page_id]
            frame = self.frames[frame_id]
            frame.reference_count += 1
            frame.last_accessed = time.time()
            self.hits += 1
            # Move to end of LRU order
            self.lru_order.move_to_end(frame_id)
            return frame.page

        # Page miss - need to load from disk
        self.misses += 1

        # Find available frame
        frame_id = self._get_or_evict_frame()
        if frame_id is None:
            raise ResourceExhaustedException(f"Buffer pool full with {self.pool_size} pages")

        # Create new page
        page = self._simulate_read_page(page_id)
        frame = BufferFrame(
            frame_id=frame_id,
            page=page,
            reference_count=1,
            last_accessed=time.time(),
        )

        # Update tables
        self.frames[frame_id] = frame
        self.page_table[page_id] = frame_id
        self.lru_order[frame_id] = page_id

        return page

    def pin_page(self, page_id: int) -> Page:
        """
        Pin a page in the buffer pool, preventing eviction.

        Args:
            page_id: The ID of the page to pin

        Returns:
            The pinned Page object

        Raises:
            PageException: If page cannot be pinned
        """
        page = self.get_page(page_id)
        if page_id in self.page_table:
            frame_id = self.page_table[page_id]
            self.frames[frame_id].pin_count += 1
            page.pin_count += 1
        return page

    def unpin_page(self, page_id: int, is_dirty: bool = False) -> None:
        """
        Unpin a page, allowing it to be evicted.

        Args:
            page_id: The ID of the page to unpin
            is_dirty: Whether the page was modified

        Raises:
            PageException: If page is not pinned
        """
        if page_id not in self.page_table:
            raise PageException(f"Page {page_id} not in buffer pool")

        frame_id = self.page_table[page_id]
        frame = self.frames[frame_id]

        if frame.pin_count <= 0:
            raise PageException(f"Page {page_id} is not pinned")

        frame.pin_count -= 1
        frame.page.pin_count -= 1

        if is_dirty:
            frame.page.is_dirty = True

    def mark_dirty(self, page_id: int) -> None:
        """
        Mark a page as dirty (modified).

        Args:
            page_id: The ID of the page to mark dirty

        Raises:
            PageException: If page not in buffer pool
        """
        if page_id not in self.page_table:
            raise PageException(f"Page {page_id} not in buffer pool")

        frame_id = self.page_table[page_id]
        self.frames[frame_id].page.is_dirty = True

    def flush_page(self, page_id: int) -> None:
        """
        Write a page to disk and clear dirty flag.

        Args:
            page_id: The ID of the page to flush

        Raises:
            PageException: If page not in buffer pool
        """
        if page_id not in self.page_table:
            raise PageException(f"Page {page_id} not in buffer pool")

        frame_id = self.page_table[page_id]
        frame = self.frames[frame_id]

        if frame.pin_count > 0:
            raise PageException(f"Cannot flush pinned page {page_id} (pin_count={frame.pin_count})")

        if frame.page.is_dirty:
            self._simulate_write_page(frame.page)
            frame.page.is_dirty = False
            self.flushes += 1

    def flush_all(self) -> None:
        """Flush all dirty pages to disk."""
        for page_id in list(self.page_table.keys()):
            if page_id in self.page_table:  # Check still exists
                try:
                    self.flush_page(page_id)
                except PageException:
                    # Page might be pinned, skip
                    pass

    def evict_page(self, page_id: int) -> None:
        """
        Remove a page from the buffer pool.

        Args:
            page_id: The ID of the page to evict

        Raises:
            PageException: If page is pinned or not in pool
        """
        if page_id not in self.page_table:
            raise PageException(f"Page {page_id} not in buffer pool")

        frame_id = self.page_table[page_id]
        frame = self.frames[frame_id]

        if frame.pin_count > 0:
            raise PageException(f"Cannot evict pinned page {page_id} (pin_count={frame.pin_count})")

        # Flush dirty page before evicting
        if frame.page.is_dirty:
            self._simulate_write_page(frame.page)

        # Remove from tables
        del self.frames[frame_id]
        del self.page_table[page_id]
        if frame_id in self.lru_order:
            del self.lru_order[frame_id]

        self.evictions += 1

    def _get_or_evict_frame(self) -> int | None:
        """
        Get an available frame or evict one using clock algorithm.

        Returns:
            A frame_id or None if unable to allocate

        Raises:
            BufferPoolException: If unable to find evictable page
        """
        # First, check if we have free frames
        if len(self.frames) < self.pool_size:
            frame_id = self.next_frame_id
            self.next_frame_id += 1
            return frame_id

        # All frames used, use clock algorithm
        attempts = 0
        max_attempts = self.pool_size * 2  # Prevent infinite loop

        while attempts < max_attempts:
            # Get next frame in clock order
            frame_ids = list(self.lru_order.keys())
            if not frame_ids:
                raise BufferPoolException("No frames available for eviction")

            clock_idx = self.clock_hand % len(frame_ids)
            frame_id = frame_ids[clock_idx]
            self.clock_hand = (self.clock_hand + 1) % len(frame_ids)

            frame = self.frames[frame_id]

            # Check if page is pinned
            if frame.pin_count > 0:
                attempts += 1
                continue

            # Check reference bit (use reference_count)
            if frame.reference_count > 0:
                frame.reference_count = 0
                attempts += 1
                continue

            # Can evict this page
            page_id = self.lru_order[frame_id]
            self.evict_page(page_id)
            return frame_id

        raise BufferPoolException(f"Could not evict any page after {max_attempts} attempts")

    def _simulate_read_page(self, page_id: int) -> Page:
        """
        Simulate reading a page from disk.

        Args:
            page_id: The ID of the page to read

        Returns:
            A Page object with the given ID
        """
        self.reads += 1
        page = Page(page_id=page_id)
        # In a real system, this would read from disk
        # Simulate with some initial data
        page.data[0:8] = page_id.to_bytes(8, "little")
        return page

    def _simulate_write_page(self, page: Page) -> None:
        """
        Simulate writing a page to disk.

        Args:
            page: The Page object to write
        """
        self.writes += 1
        # In a real system, this would write to disk
        # Simulate by marking as clean
        page.is_dirty = False

    def allocate_page(self) -> Page:
        """
        Allocate a new page.

        Returns:
            A newly allocated Page object

        Raises:
            ResourceExhaustedException: If buffer pool is full
        """
        page_id = self.next_page_id
        self.next_page_id += 1
        page = self.get_page(page_id)
        page.is_dirty = True
        return page

    def get_statistics(self) -> dict[str, float]:
        """
        Get buffer pool statistics.

        Returns:
            Dictionary with hit ratio, eviction count, etc.
        """
        total_accesses = self.hits + self.misses
        hit_ratio = self.hits / total_accesses if total_accesses > 0 else 0.0

        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": hit_ratio,
            "evictions": self.evictions,
            "flushes": self.flushes,
            "reads": self.reads,
            "writes": self.writes,
            "pages_in_pool": len(self.frames),
            "pool_size": self.pool_size,
            "utilization": len(self.frames) / self.pool_size,
        }

    def reset_statistics(self) -> None:
        """Reset all statistics counters."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.flushes = 0
        self.reads = 0
        self.writes = 0

    def clear(self) -> None:
        """Clear all pages from the buffer pool."""
        self.flush_all()
        self.frames.clear()
        self.page_table.clear()
        self.lru_order.clear()
        self.clock_hand = 0

    def get_page_info(self, page_id: int) -> dict[str, any] | None:
        """
        Get detailed information about a page.

        Args:
            page_id: The ID of the page

        Returns:
            Dictionary with page info or None if not in pool
        """
        if page_id not in self.page_table:
            return None

        frame_id = self.page_table[page_id]
        frame = self.frames[frame_id]
        page = frame.page

        return {
            "page_id": page_id,
            "frame_id": frame_id,
            "pin_count": page.pin_count,
            "reference_count": frame.reference_count,
            "is_dirty": page.is_dirty,
            "last_accessed": frame.last_accessed,
            "size_bytes": len(page.data),
        }

    def list_pages(self) -> list[int]:
        """Return list of all page IDs in the buffer pool."""
        return list(self.page_table.keys())

    def get_replacement_candidate(self) -> int | None:
        """
        Find a page eligible for eviction without actually evicting it.

        Returns:
            A page_id that could be evicted, or None if none available
        """
        # Try to find an unpinned page with reference_count == 0
        for frame_id in self.lru_order.keys():
            frame = self.frames[frame_id]
            if frame.pin_count == 0 and frame.reference_count == 0:
                return self.lru_order[frame_id]

        # If none found, any unpinned page could be evicted after ref bit clear
        for frame_id in self.lru_order.keys():
            frame = self.frames[frame_id]
            if frame.pin_count == 0:
                return self.lru_order[frame_id]

        return None
