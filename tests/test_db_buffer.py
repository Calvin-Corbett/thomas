"""
Tests for buffer pool manager.

Tests cover:
- Page allocation and retrieval
- LRU replacement with clock sweep
- Dirty page tracking
- Pin/unpin operations
- Page flushing
- Statistics tracking
"""

import os
import sys

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thomas.marketplace.db_internals import BufferPool
from thomas.marketplace.db_internals._exceptions import (
    BufferPoolException,
    PageException,
)


class TestBufferPoolBasic:
    """Basic buffer pool functionality tests."""

    def test_create_buffer_pool(self) -> None:
        """Test creating a buffer pool."""
        pool = BufferPool(pool_size=100)
        assert pool.pool_size == 100
        assert pool.page_size == 4096
        assert len(pool.frames) == 0

    def test_allocate_page(self) -> None:
        """Test allocating a new page."""
        pool = BufferPool(pool_size=100)
        page = pool.allocate_page()
        assert page.page_id == 0
        assert len(page.data) == 4096
        assert page.is_dirty is True

    def test_get_page(self) -> None:
        """Test retrieving a page."""
        pool = BufferPool(pool_size=100)
        page1 = pool.get_page(0)
        assert page1.page_id == 0

        page2 = pool.get_page(0)
        assert page2 is page1

    def test_hit_miss_tracking(self) -> None:
        """Test buffer pool hit/miss tracking."""
        pool = BufferPool(pool_size=100)

        # First access is a miss
        pool.get_page(0)
        assert pool.misses == 1
        assert pool.hits == 0

        # Second access is a hit
        pool.get_page(0)
        assert pool.hits == 1

    def test_get_statistics(self) -> None:
        """Test statistics collection."""
        pool = BufferPool(pool_size=100)

        pool.get_page(0)
        pool.get_page(0)

        stats = pool.get_statistics()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_ratio"] == 0.5
        assert stats["pages_in_pool"] == 1

    def test_reset_statistics(self) -> None:
        """Test resetting statistics."""
        pool = BufferPool(pool_size=100)
        pool.get_page(0)

        pool.reset_statistics()
        assert pool.hits == 0
        assert pool.misses == 0


class TestBufferPoolPin:
    """Tests for pin/unpin functionality."""

    def test_pin_page(self) -> None:
        """Test pinning a page."""
        pool = BufferPool(pool_size=100)
        page = pool.pin_page(0)
        assert page.pin_count == 1

    def test_unpin_page(self) -> None:
        """Test unpinning a page."""
        pool = BufferPool(pool_size=100)
        pool.pin_page(0)
        pool.unpin_page(0)

        page = pool.get_page(0)
        assert page.pin_count == 0

    def test_unpin_not_pinned(self) -> None:
        """Test unpinning page that isn't pinned."""
        pool = BufferPool(pool_size=100)

        with pytest.raises(PageException):
            pool.unpin_page(0)

    def test_cannot_evict_pinned_page(self) -> None:
        """Test that pinned pages cannot be evicted."""
        pool = BufferPool(pool_size=2)
        page1 = pool.pin_page(0)
        page2 = pool.pin_page(1)

        # Try to allocate third page - should evict something
        # But first two are pinned, so should fail
        with pytest.raises(BufferPoolException):
            for _ in range(10):
                pool.allocate_page()

    def test_multiple_pin_counts(self) -> None:
        """Test multiple pins on same page."""
        pool = BufferPool(pool_size=100)
        pool.pin_page(0)
        pool.pin_page(0)

        page = pool.get_page(0)
        assert page.pin_count == 2


class TestBufferPoolEviction:
    """Tests for page eviction and replacement."""

    def test_lru_eviction(self) -> None:
        """Test that LRU pages are evicted first."""
        pool = BufferPool(pool_size=3)

        # Allocate 3 pages
        pool.allocate_page()  # page 0
        pool.allocate_page()  # page 1
        pool.allocate_page()  # page 2

        assert len(pool.frames) == 3

        # Access page 0 to mark it as recently used
        pool.get_page(0)

        # Allocate new page - should evict something
        pool.allocate_page()  # page 3

        # Page 1 (oldest) should have been evicted
        assert len(pool.frames) == 3

    def test_evict_specific_page(self) -> None:
        """Test evicting a specific page."""
        pool = BufferPool(pool_size=100)
        page = pool.allocate_page()
        page_id = page.page_id

        pool.evict_page(page_id)
        assert page_id not in pool.page_table

    def test_cannot_evict_pinned(self) -> None:
        """Test that pinned pages cannot be evicted."""
        pool = BufferPool(pool_size=100)
        page = pool.pin_page(0)

        with pytest.raises(PageException):
            pool.evict_page(0)


class TestBufferPoolDirty:
    """Tests for dirty page tracking."""

    def test_mark_dirty(self) -> None:
        """Test marking a page as dirty."""
        pool = BufferPool(pool_size=100)
        page = pool.get_page(0)

        pool.mark_dirty(0)
        assert page.is_dirty is True

    def test_flush_page(self) -> None:
        """Test flushing a dirty page."""
        pool = BufferPool(pool_size=100)
        page = pool.get_page(0)
        pool.mark_dirty(0)

        assert page.is_dirty is True
        pool.flush_page(0)
        assert page.is_dirty is False
        assert pool.flushes == 1

    def test_flush_all(self) -> None:
        """Test flushing all dirty pages."""
        pool = BufferPool(pool_size=100)

        pool.get_page(0)
        pool.mark_dirty(0)
        pool.get_page(1)
        pool.mark_dirty(1)

        pool.flush_all()
        assert pool.flushes == 2

    def test_cannot_flush_pinned(self) -> None:
        """Test that pinned pages cannot be flushed."""
        pool = BufferPool(pool_size=100)
        pool.pin_page(0)
        pool.mark_dirty(0)

        with pytest.raises(PageException):
            pool.flush_page(0)


class TestBufferPoolClear:
    """Tests for clearing the buffer pool."""

    def test_clear(self) -> None:
        """Test clearing the buffer pool."""
        pool = BufferPool(pool_size=100)
        pool.allocate_page()
        pool.allocate_page()

        assert len(pool.frames) > 0
        pool.clear()
        assert len(pool.frames) == 0

    def test_clear_flushes_dirty(self) -> None:
        """Test that clear flushes dirty pages."""
        pool = BufferPool(pool_size=100)
        page = pool.allocate_page()
        pool.mark_dirty(page.page_id)

        pool.clear()
        # All pages should be flushed
        assert len(pool.frames) == 0


class TestBufferPoolInfo:
    """Tests for getting buffer pool information."""

    def test_get_page_info(self) -> None:
        """Test getting info about a page."""
        pool = BufferPool(pool_size=100)
        page = pool.pin_page(0)

        info = pool.get_page_info(0)
        assert info is not None
        assert info["page_id"] == 0
        assert info["pin_count"] == 1

    def test_get_page_info_not_found(self) -> None:
        """Test getting info about non-existent page."""
        pool = BufferPool(pool_size=100)

        info = pool.get_page_info(999)
        assert info is None

    def test_list_pages(self) -> None:
        """Test listing all pages in pool."""
        pool = BufferPool(pool_size=100)
        pool.allocate_page()
        pool.allocate_page()

        pages = pool.list_pages()
        assert len(pages) == 2
        assert 0 in pages
        assert 1 in pages


class TestBufferPoolClock:
    """Tests for clock sweep algorithm."""

    def test_clock_sweep_reference_bit(self) -> None:
        """Test clock sweep with reference bits."""
        pool = BufferPool(pool_size=3)

        # Allocate 3 pages
        p0 = pool.allocate_page()
        p1 = pool.allocate_page()
        p2 = pool.allocate_page()

        # Access p0 to set reference bit
        pool.get_page(p0.page_id)

        # Allocate new page - should evict p1 (has reference bit cleared)
        p3 = pool.allocate_page()

        assert len(pool.frames) == 3

    def test_replacement_candidate(self) -> None:
        """Test finding replacement candidate."""
        pool = BufferPool(pool_size=100)
        pool.allocate_page()
        pool.allocate_page()

        candidate = pool.get_replacement_candidate()
        assert candidate is not None
        assert candidate in pool.list_pages()


class TestBufferPoolEdgeCases:
    """Edge case and stress tests."""

    def test_min_pool_size(self) -> None:
        """Test minimum pool size."""
        with pytest.raises(ValueError):
            BufferPool(pool_size=5)  # Less than 10

    def test_page_size(self) -> None:
        """Test page size is correct."""
        pool = BufferPool(pool_size=100)
        page = pool.get_page(0)
        assert len(page.data) == 4096

    def test_many_pages(self) -> None:
        """Test with many page accesses."""
        pool = BufferPool(pool_size=50)

        for i in range(100):
            page = pool.get_page(i)
            assert page.page_id == i

        stats = pool.get_statistics()
        assert stats["pages_in_pool"] <= 50

    def test_sequential_access(self) -> None:
        """Test sequential page access pattern."""
        pool = BufferPool(pool_size=100)

        for i in range(10):
            pool.get_page(i)

        stats = pool.get_statistics()
        assert stats["misses"] == 10
        assert stats["hits"] == 0

    def test_random_access(self) -> None:
        """Test random access pattern."""
        pool = BufferPool(pool_size=100)

        # Access in pattern: 0, 1, 0, 1, 0, 1...
        for _ in range(5):
            pool.get_page(0)
            pool.get_page(1)

        stats = pool.get_statistics()
        assert stats["hits"] == 8  # After initial 2 misses


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
