"""Sorted String Table (SSTable) with block-based format."""

import struct
from collections.abc import Iterator
from pathlib import Path

from thomas.kvstore._exceptions import CorruptionError, SSTableError
from thomas.kvstore._types import SSTableEntry
from thomas.kvstore.bloom_filter import BloomFilter


class SSTable:
    """An immutable sorted string table for persistent storage.

    Format:
    - Block 0 (4KB+): Key-value pairs
    - Block 1 (4KB+): Key-value pairs
    - ...
    - Index Block: Offsets and first key of each block
    - Bloom Filter: Serialized bloom filter
    - Footer: Metadata and offsets
    """

    def __init__(self, file_path: str, block_size_bytes: int = 4096):
        """Initialize SSTable for reading.

        Args:
            file_path: Path to SSTable file
            block_size_bytes: Block size

        Raises:
            SSTableError: If file is corrupt
        """
        self.file_path = Path(file_path)
        self.block_size_bytes = block_size_bytes

        if not self.file_path.exists():
            raise SSTableError(f"SSTable file not found: {file_path}")

        self.file_size = self.file_path.stat().st_size
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load metadata from SSTable footer."""
        with open(self.file_path, "rb") as f:
            # Read footer (last 256 bytes)
            if self.file_size < 256:
                raise CorruptionError("SSTable file too small")

            f.seek(self.file_size - 256)
            footer = f.read(256)

            # Parse footer
            magic = footer[0:4]
            if magic != b"SSTB":
                raise CorruptionError(f"Invalid SSTable magic: {magic}")

            version = struct.unpack(">H", footer[4:6])[0]
            if version != 1:
                raise CorruptionError(f"Unsupported SSTable version: {version}")

            # Offsets stored in footer
            self.index_offset = struct.unpack(">Q", footer[6:14])[0]
            self.bloom_filter_offset = struct.unpack(">Q", footer[14:22])[0]
            self.bloom_filter_size = struct.unpack(">I", footer[22:26])[0]
            self.num_blocks = struct.unpack(">I", footer[26:30])[0]
            self.num_entries = struct.unpack(">I", footer[30:34])[0]

            # Load bloom filter
            f.seek(self.bloom_filter_offset)
            bf_data = f.read(self.bloom_filter_size)
            self.bloom_filter = BloomFilter.deserialize(bf_data)

            # Load block index
            self.block_index: list[tuple[int, bytes]] = []
            f.seek(self.index_offset)
            for _ in range(self.num_blocks):
                block_offset = struct.unpack(">Q", f.read(8))[0]
                first_key_len = struct.unpack(">I", f.read(4))[0]
                first_key = f.read(first_key_len)
                self.block_index.append((block_offset, first_key))

    def get(self, key: bytes) -> bytes | None:
        """Get a value by key.

        Args:
            key: The key to retrieve

        Returns:
            The value, or None if not found or tombstoned

        Raises:
            KeyError: If key not found
        """
        # Check bloom filter first (fast negative test)
        if not self.bloom_filter.might_contain(key):
            raise KeyError(key)

        # Find relevant block using binary search on first keys
        block_idx = self._find_block(key)
        if block_idx is None:
            raise KeyError(key)

        # Read block and search
        with open(self.file_path, "rb") as f:
            block_offset, _ = self.block_index[block_idx]

            # Determine block end
            if block_idx + 1 < len(self.block_index):
                block_end = self.block_index[block_idx + 1][0]
            else:
                block_end = self.index_offset

            f.seek(block_offset)
            block_data = f.read(block_end - block_offset)

        # Parse block: key_len(4) + key + value_len(4) + value
        pos = 0
        while pos < len(block_data):
            if pos + 4 > len(block_data):
                break

            key_len = struct.unpack(">I", block_data[pos : pos + 4])[0]
            pos += 4

            if pos + key_len > len(block_data):
                break

            stored_key = block_data[pos : pos + key_len]
            pos += key_len

            if pos + 4 > len(block_data):
                break

            value_len = struct.unpack(">I", block_data[pos : pos + 4])[0]
            pos += 4

            if stored_key == key:
                if value_len == 0:
                    raise KeyError(key)  # Tombstone
                value = block_data[pos : pos + value_len]
                return value

            if value_len > 0:
                pos += value_len

        raise KeyError(key)

    def _find_block(self, key: bytes) -> int | None:
        """Find block containing key using binary search.

        Returns:
            Block index, or None if key is before all blocks
        """
        for i, (_, first_key) in enumerate(self.block_index):
            if key < first_key:
                return i - 1 if i > 0 else None
        return len(self.block_index) - 1

    def iter_entries(self) -> Iterator[SSTableEntry]:
        """Iterate over all entries in sorted order.

        Yields:
            SSTableEntry objects
        """
        with open(self.file_path, "rb") as f:
            for block_idx, (block_offset, _) in enumerate(self.block_index):
                # Determine block end
                if block_idx + 1 < len(self.block_index):
                    block_end = self.block_index[block_idx + 1][0]
                else:
                    block_end = self.index_offset

                f.seek(block_offset)
                block_data = f.read(block_end - block_offset)

                pos = 0
                while pos < len(block_data):
                    if pos + 4 > len(block_data):
                        break

                    key_len = struct.unpack(">I", block_data[pos : pos + 4])[0]
                    pos += 4

                    if pos + key_len > len(block_data):
                        break

                    key = block_data[pos : pos + key_len]
                    pos += key_len

                    if pos + 4 > len(block_data):
                        break

                    value_len = struct.unpack(">I", block_data[pos : pos + 4])[0]
                    pos += 4

                    value = None
                    if value_len > 0:
                        value = block_data[pos : pos + value_len]
                        pos += value_len

                    yield SSTableEntry(
                        key=key,
                        value=value,
                        sequence=0,  # Not tracked in footer
                    )

    def contains(self, key: bytes) -> bool:
        """Check if key might be in table (bloom filter test).

        Args:
            key: The key to check

        Returns:
            True if key might be present
        """
        return self.bloom_filter.might_contain(key)


class SSTableWriter:
    """Write an SSTable from sorted entries."""

    def __init__(self, file_path: str, block_size_bytes: int = 4096, bloom_config=None):
        """Initialize SSTable writer.

        Args:
            file_path: Output file path
            block_size_bytes: Block size for data blocks
            bloom_config: BloomFilterConfig instance
        """
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.block_size_bytes = block_size_bytes
        self.bloom_config = bloom_config

        self.file = open(self.file_path, "wb")
        self.current_block = bytearray()
        self.blocks: list[bytes] = []
        self.block_first_keys: list[bytes] = []
        self.num_entries = 0
        self.current_block_first_key: bytes | None = None
        self._pending_entries: list[tuple[bytes, bytes | None]] = []

        self.bloom_filter = BloomFilter(
            bloom_config.expected_items if bloom_config else 10000,
            bloom_config.false_positive_rate if bloom_config else 0.01,
        )

    def add(self, key: bytes, value: bytes | None) -> None:
        """Add an entry to the SSTable.

        Args:
            key: The key
            value: The value (None for tombstone)
        """
        if not key:
            raise ValueError("Key cannot be empty")

        self._pending_entries.append((key, value))
        self.num_entries += 1

    def _flush_block(self) -> None:
        """Flush current block to list."""
        if self.current_block:
            self.blocks.append(bytes(self.current_block))
            if self.current_block_first_key is not None:
                self.block_first_keys.append(self.current_block_first_key)
            self.current_block = bytearray()
            self.current_block_first_key = None

    def finish(self) -> None:
        """Finalize and write SSTable to disk."""
        # Build deterministic sorted blocks from buffered entries.
        entries = sorted(self._pending_entries, key=lambda item: item[0])
        self.current_block = bytearray()
        self.blocks = []
        self.block_first_keys = []
        self.current_block_first_key = None

        for key, value in entries:
            self.bloom_filter.add(key)
            entry = bytearray()
            entry.extend(struct.pack(">I", len(key)))
            entry.extend(key)
            entry.extend(struct.pack(">I", len(value) if value else 0))
            if value:
                entry.extend(value)

            if len(self.current_block) + len(entry) > self.block_size_bytes and self.current_block:
                self._flush_block()

            if not self.current_block:
                self.current_block_first_key = key

            self.current_block.extend(entry)

        # Flush last block
        self._flush_block()

        # Write data blocks
        block_offsets = []
        current_offset = 0
        for block in self.blocks:
            block_offsets.append(current_offset)
            self.file.write(block)
            current_offset += len(block)

        # Write index
        index_offset = current_offset
        for offset, first_key in zip(block_offsets, self.block_first_keys):
            self.file.write(struct.pack(">Q", offset))
            self.file.write(struct.pack(">I", len(first_key)))
            self.file.write(first_key)
        current_offset += sum(8 + 4 + len(fk) for fk in self.block_first_keys)

        # Write bloom filter
        bloom_data = self.bloom_filter.serialize()
        bloom_offset = current_offset
        self.file.write(bloom_data)

        # Write footer
        footer = bytearray(256)
        footer[0:4] = b"SSTB"
        struct.pack_into(">H", footer, 4, 1)  # version
        struct.pack_into(">Q", footer, 6, index_offset)
        struct.pack_into(">Q", footer, 14, bloom_offset)
        struct.pack_into(">I", footer, 22, len(bloom_data))
        struct.pack_into(">I", footer, 26, len(self.blocks))
        struct.pack_into(">I", footer, 30, self.num_entries)

        self.file.write(bytes(footer))
        self.file.close()

    def __enter__(self) -> "SSTableWriter":
        return self

    def __exit__(self, *args):
        if self.file and not self.file.closed:
            self.finish()
