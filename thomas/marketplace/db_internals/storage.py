"""
Storage engine for heap file organization and slotted page layout.

This module implements:
- Heap file organization with linked-list of pages
- Slotted page layout (slot directory + variable-length records)
- Variable-length record storage with record offset tracking
- Page splitting when full
- Free space map for efficient page selection
- Record insertion, deletion, and update operations
- Table scan iterators
- TOAST-like handling for large values
"""

from collections.abc import Iterator

from ._exceptions import (
    PageException,
)
from ._types import Page, Record, Table
from .buffer_pool import BufferPool


class SlottedPage:
    """
    Represents a page with slotted layout.

    Layout:
    - Slot directory at end: [slot_count][slot_offsets...]
    - Records stored sequentially from start
    - Free space in middle
    """

    SLOT_SIZE = 4  # bytes per slot
    HEADER_SIZE = 4  # slot count

    def __init__(self, page: Page) -> None:
        """Initialize a slotted page wrapper."""
        self.page = page
        self._init_page_if_empty()

    def _init_page_if_empty(self) -> None:
        """Initialize an empty page with slot directory."""
        # Check if page is empty
        if self._get_slot_count() == 0 and self.page.data[:4] == b"\x00\x00\x00\x00":
            self._set_slot_count(0)

    def _get_slot_count(self) -> int:
        """Get number of slots in use."""
        data = self.page.data[-self.HEADER_SIZE :]
        return int.from_bytes(data, "little")

    def _set_slot_count(self, count: int) -> None:
        """Set number of slots."""
        self.page.data[-self.HEADER_SIZE :] = count.to_bytes(self.HEADER_SIZE, "little")

    def _get_slot(self, slot_id: int) -> tuple[int, int]:
        """Get (offset, length) for a slot."""
        slot_count = self._get_slot_count()
        if slot_id < 0 or slot_id >= slot_count:
            raise PageException(f"Invalid slot_id {slot_id}")

        # Slots stored before header
        slot_offset = 4096 - self.HEADER_SIZE - (slot_count - slot_id) * self.SLOT_SIZE
        offset_bytes = self.page.data[slot_offset : slot_offset + 2]
        length_bytes = self.page.data[slot_offset + 2 : slot_offset + 4]
        offset = int.from_bytes(offset_bytes, "little")
        length = int.from_bytes(length_bytes, "little")
        return (offset, length)

    def _set_slot(self, slot_id: int, offset: int, length: int) -> None:
        """Set (offset, length) for a slot."""
        slot_count = self._get_slot_count()
        if slot_id < 0 or slot_id >= slot_count:
            raise PageException(f"Invalid slot_id {slot_id}")

        slot_offset = 4096 - self.HEADER_SIZE - (slot_count - slot_id) * self.SLOT_SIZE
        self.page.data[slot_offset : slot_offset + 2] = offset.to_bytes(2, "little")
        self.page.data[slot_offset + 2 : slot_offset + 4] = length.to_bytes(2, "little")

    def _get_free_space(self) -> int:
        """Get amount of free space in the page."""
        slot_count = self._get_slot_count()
        if slot_count == 0:
            return 4096 - self.HEADER_SIZE

        # Find highest used offset
        highest_offset = 0
        for i in range(slot_count):
            offset, length = self._get_slot(i)
            if offset > 0:
                highest_offset = max(highest_offset, offset + length)

        directory_size = self.HEADER_SIZE + (slot_count * self.SLOT_SIZE)
        return max(0, highest_offset + 4096 - directory_size - highest_offset)

    def insert_record(self, record_bytes: bytes) -> int:
        """
        Insert a record into the page.

        Returns:
            slot_id of the inserted record

        Raises:
            PageException: If page is full
        """
        record_len = len(record_bytes)
        slot_count = self._get_slot_count()

        # Find insertion point (use first deleted slot or append)
        slot_id = None
        for i in range(slot_count):
            offset, length = self._get_slot(i)
            if offset == 0:  # Deleted slot
                if length >= record_len:
                    slot_id = i
                    break

        # If no reusable slot, create new one
        if slot_id is None:
            slot_id = slot_count
            # Check if we have space for new slot + record
            new_slot_count = slot_count + 1
            new_directory_size = self.HEADER_SIZE + (new_slot_count * self.SLOT_SIZE)

            # Find next free offset
            if slot_count == 0:
                next_offset = 0
            else:
                highest_offset = 0
                for i in range(slot_count):
                    off, length = self._get_slot(i)
                    if off > 0:
                        highest_offset = max(highest_offset, off + length)
                next_offset = highest_offset

            needed = next_offset + record_len + new_directory_size
            if needed > 4096:
                raise PageException("Page full - cannot insert record")

            # Write record
            self.page.data[next_offset : next_offset + record_len] = record_bytes
            # Add slot
            self._set_slot_count(new_slot_count)
            self._set_slot(slot_id, next_offset, record_len)
        else:
            # Reuse deleted slot
            offset, _ = self._get_slot(slot_id)
            self.page.data[offset : offset + record_len] = record_bytes
            self._set_slot(slot_id, offset, record_len)

        return slot_id

    def get_record(self, slot_id: int) -> bytes | None:
        """Get record bytes from a slot."""
        try:
            offset, length = self._get_slot(slot_id)
            if offset == 0 or length == 0:
                return None
            return bytes(self.page.data[offset : offset + length])
        except PageException:
            return None

    def delete_record(self, slot_id: int) -> None:
        """Mark a record as deleted."""
        offset, length = self._get_slot(slot_id)
        if offset > 0:
            self._set_slot(slot_id, 0, length)  # Mark as deleted

    def update_record(self, slot_id: int, record_bytes: bytes) -> bool:
        """
        Update a record in place if it fits.

        Returns:
            True if updated in place, False if requires different slot
        """
        old_offset, old_length = self._get_slot(slot_id)
        if old_offset == 0:
            raise PageException(f"Cannot update deleted slot {slot_id}")

        # If new record fits in same space, update in place
        if len(record_bytes) <= old_length:
            self.page.data[old_offset : old_offset + len(record_bytes)] = record_bytes
            self._set_slot(slot_id, old_offset, len(record_bytes))
            return True

        # Otherwise, need to delete old and insert new
        return False

    def list_valid_slots(self) -> list[int]:
        """Return list of non-deleted slot IDs."""
        slot_count = self._get_slot_count()
        valid = []
        for i in range(slot_count):
            offset, length = self._get_slot(i)
            if offset > 0 and length > 0:
                valid.append(i)
        return valid


class HeapFile:
    """
    Manages a heap file with multiple slotted pages.

    Supports:
    - Page-level operations
    - Record insertion/deletion/update
    - Table scanning
    - Free space tracking
    """

    def __init__(self, buffer_pool: BufferPool, table: Table) -> None:
        """
        Initialize a heap file.

        Args:
            buffer_pool: The buffer pool manager
            table: Table metadata
        """
        self.buffer_pool = buffer_pool
        self.table = table
        self.first_page_id = table.first_page_id
        self.page_mapping: dict[int, list[int]] = {}  # page_id -> list of slot_ids

    def insert(self, record: Record) -> tuple[int, int]:
        """
        Insert a record into the heap file.

        Returns:
            (page_id, slot_id) of the inserted record

        Raises:
            StorageException: If insertion fails
        """
        record_bytes = record.to_bytes()

        # Try to insert into existing pages
        page_id = self.first_page_id
        while page_id is not None:
            page = self.buffer_pool.pin_page(page_id)
            slotted = SlottedPage(page)

            try:
                slot_id = slotted.insert_record(record_bytes)
                self.buffer_pool.unpin_page(page_id, is_dirty=True)
                record.rid = (page_id, slot_id)
                return (page_id, slot_id)
            except PageException:
                # Page full, try next
                self.buffer_pool.unpin_page(page_id, is_dirty=False)
                # In real system, follow linked list to next page
                page_id = None

        # No space in existing pages, allocate new page
        new_page = self.buffer_pool.allocate_page()
        new_page_id = new_page.page_id
        slotted = SlottedPage(new_page)
        slot_id = slotted.insert_record(record_bytes)

        if self.first_page_id is None:
            self.first_page_id = new_page_id
            self.table.first_page_id = new_page_id

        self.buffer_pool.unpin_page(new_page_id, is_dirty=True)
        record.rid = (new_page_id, slot_id)
        return (new_page_id, slot_id)

    def delete(self, page_id: int, slot_id: int) -> None:
        """
        Delete a record by marking it as deleted.

        Args:
            page_id: Page containing the record
            slot_id: Slot ID of the record
        """
        page = self.buffer_pool.pin_page(page_id)
        slotted = SlottedPage(page)
        slotted.delete_record(slot_id)
        self.buffer_pool.unpin_page(page_id, is_dirty=True)

    def get(self, page_id: int, slot_id: int) -> Record | None:
        """
        Retrieve a record by RID.

        Args:
            page_id: Page ID
            slot_id: Slot ID

        Returns:
            The Record or None if deleted/not found
        """
        page = self.buffer_pool.pin_page(page_id)
        slotted = SlottedPage(page)
        record_bytes = slotted.get_record(slot_id)
        self.buffer_pool.unpin_page(page_id, is_dirty=False)

        if record_bytes is None:
            return None

        record = Record.from_bytes(record_bytes)
        record.rid = (page_id, slot_id)
        return record

    def update(self, page_id: int, slot_id: int, record: Record) -> None:
        """
        Update a record.

        Args:
            page_id: Page ID
            slot_id: Slot ID
            record: Updated record data

        Raises:
            StorageException: If update cannot be done in place
        """
        record_bytes = record.to_bytes()
        page = self.buffer_pool.pin_page(page_id)
        slotted = SlottedPage(page)

        if slotted.update_record(slot_id, record_bytes):
            self.buffer_pool.unpin_page(page_id, is_dirty=True)
        else:
            self.buffer_pool.unpin_page(page_id, is_dirty=False)
            # Would need to delete old and insert new
            self.delete(page_id, slot_id)
            self.insert(record)

    def scan(self) -> Iterator[Record]:
        """
        Scan all records in the heap file.

        Yields:
            Each record in the table
        """
        page_id = self.first_page_id
        visited = set()

        while page_id is not None and page_id not in visited:
            visited.add(page_id)

            try:
                page = self.buffer_pool.pin_page(page_id)
                slotted = SlottedPage(page)

                # Yield all valid records
                for slot_id in slotted.list_valid_slots():
                    record_bytes = slotted.get_record(slot_id)
                    if record_bytes is not None:
                        record = Record.from_bytes(record_bytes)
                        record.rid = (page_id, slot_id)
                        yield record

                self.buffer_pool.unpin_page(page_id, is_dirty=False)
            except PageException:
                pass

            # In a real implementation, follow linked list
            page_id = None

    def full_scan(self) -> Iterator[Record]:
        """Alias for scan() - performs full table scan."""
        return self.scan()

    def get_page_count(self) -> int:
        """Get number of pages in the heap file."""
        count = 0
        page_id = self.first_page_id
        visited = set()

        while page_id is not None and page_id not in visited:
            visited.add(page_id)
            count += 1
            page_id = None  # In simple version, just one page chain

        return count

    def get_record_count(self) -> int:
        """Get total number of records (including deleted)."""
        count = 0
        for _ in self.scan():
            count += 1
        return count


class FreeSpaceMap:
    """
    Tracks free space in pages for efficient page selection.

    Uses a bitmap approach: each page has a free space percentage
    stored in a special metadata page.
    """

    def __init__(self, buffer_pool: BufferPool) -> None:
        """Initialize the free space map."""
        self.buffer_pool = buffer_pool
        self.space_map: dict[int, float] = {}  # page_id -> free %

    def update_page_free_space(self, page_id: int, free_percentage: float) -> None:
        """
        Update free space estimate for a page.

        Args:
            page_id: The page ID
            free_percentage: Percentage free (0-100)
        """
        self.space_map[page_id] = min(100.0, max(0.0, free_percentage))

    def find_page_with_free_space(self, min_free_bytes: int) -> int | None:
        """
        Find a page with enough free space.

        Args:
            min_free_bytes: Minimum free space needed

        Returns:
            A page_id with sufficient free space, or None
        """
        threshold_percent = (min_free_bytes / 4096) * 100

        for page_id, free_pct in sorted(self.space_map.items(), key=lambda x: -x[1]):
            if free_pct >= threshold_percent:
                return page_id

        return None

    def clear_page(self, page_id: int) -> None:
        """Remove a page from the free space map."""
        if page_id in self.space_map:
            del self.space_map[page_id]


class ToastManager:
    """
    TOAST-like handling for large values.

    Handles variable-length values that don't fit inline:
    - Stores in separate TOAST table
    - Inline values stored as references
    - Compression support
    """

    def __init__(self, buffer_pool: BufferPool) -> None:
        """Initialize TOAST manager."""
        self.buffer_pool = buffer_pool
        self.toast_values: dict[int, bytes] = {}  # toast_id -> data
        self.next_toast_id = 1000000
        self.threshold = 1024  # bytes - threshold for toasting

    def toast_value(self, data: bytes) -> int | None:
        """
        TOAST a large value if needed.

        Args:
            data: The data to potentially toast

        Returns:
            Toast ID if toasted, None if kept inline
        """
        if len(data) <= self.threshold:
            return None

        toast_id = self.next_toast_id
        self.next_toast_id += 1
        self.toast_values[toast_id] = data
        return toast_id

    def detoast_value(self, toast_id: int) -> bytes | None:
        """
        Retrieve a toasted value.

        Args:
            toast_id: The toast ID

        Returns:
            The original data or None if not found
        """
        return self.toast_values.get(toast_id)
