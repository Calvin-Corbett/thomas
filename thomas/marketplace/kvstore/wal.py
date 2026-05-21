"""Write-ahead logging for durability."""

import os
import struct
import time
from collections.abc import Iterator
from pathlib import Path

from thomas.marketplace.kvstore._exceptions import CorruptionError, WALError
from thomas.marketplace.kvstore._types import WALEntry, WriteOp


class WAL:
    """Write-ahead log for crash recovery.

    Format per entry:
    - CRC32 checksum (4 bytes)
    - Timestamp (8 bytes, double)
    - Sequence number (8 bytes)
    - Operation type (1 byte): 0=PUT, 1=DELETE
    - Key length (4 bytes)
    - Value length (4 bytes, 0 if DELETE)
    - Key data
    - Value data (if PUT)
    """

    def __init__(
        self, dir_path: str, rotation_size_mb: int = 100, sync_mode: str = "periodic", sync_interval_ms: int = 100
    ):
        """Initialize WAL.

        Args:
            dir_path: Directory for WAL files
            rotation_size_mb: Size before rotating to new file
            sync_mode: "always", "periodic", or "os"
            sync_interval_ms: Sync interval for periodic mode

        Raises:
            ValueError: If parameters are invalid
        """
        if rotation_size_mb <= 0:
            raise ValueError("rotation_size_mb must be positive")
        if sync_mode not in ("always", "periodic", "os"):
            raise ValueError("sync_mode must be 'always', 'periodic', or 'os'")

        self.dir_path = Path(dir_path)
        self.dir_path.mkdir(parents=True, exist_ok=True)

        self.rotation_size_bytes = rotation_size_mb * 1024 * 1024
        self.sync_mode = sync_mode
        self.sync_interval_ms = sync_interval_ms
        self.last_sync = time.time()

        self.current_file_index = self._find_next_index()
        self.current_file: open | None = None
        self.current_file_size = 0
        self._open_current_file()

    def _find_next_index(self) -> int:
        """Find the next available WAL file index.

        Returns:
            The index for the next WAL file
        """
        existing = list(self.dir_path.glob("wal_*.log"))
        if not existing:
            return 0
        indices = [int(f.stem.split("_")[1]) for f in existing]
        return max(indices) + 1

    def _open_current_file(self) -> None:
        """Open the current WAL file for appending."""
        if self.current_file is not None:
            self.current_file.close()

        file_path = self.dir_path / f"wal_{self.current_file_index}.log"
        self.current_file = open(file_path, "ab")
        self.current_file_size = os.path.getsize(file_path)

    def _should_rotate(self) -> bool:
        """Check if WAL should rotate to new file.

        Returns:
            True if rotation needed
        """
        return self.current_file_size >= self.rotation_size_bytes

    def _sync(self) -> None:
        """Sync file based on sync mode."""
        if self.sync_mode == "always":
            self.current_file.flush()
            os.fsync(self.current_file.fileno())
        elif self.sync_mode == "periodic":
            now = time.time()
            if (now - self.last_sync) * 1000 >= self.sync_interval_ms:
                self.current_file.flush()
                os.fsync(self.current_file.fileno())
                self.last_sync = now
        # "os" mode: let OS handle it

    def append(self, sequence: int, op: WriteOp, key: bytes, value: bytes | None) -> None:
        """Append an entry to the WAL.

        Args:
            sequence: Sequence number
            op: PUT or DELETE
            key: The key
            value: The value (None for DELETE)

        Raises:
            WALError: If write fails
        """
        if not key:
            raise ValueError("Key cannot be empty")
        if op == WriteOp.PUT and value is None:
            raise ValueError("PUT operation requires value")

        # Rotate if needed
        if self._should_rotate():
            self.current_file_index += 1
            self._open_current_file()

        try:
            timestamp = time.time()
            op_byte = 0 if op == WriteOp.PUT else 1

            # Build entry
            entry_data = bytearray()
            entry_data.extend(struct.pack(">d", timestamp))
            entry_data.extend(struct.pack(">Q", sequence))
            entry_data.append(op_byte)
            entry_data.extend(struct.pack(">I", len(key)))

            if op == WriteOp.PUT:
                entry_data.extend(struct.pack(">I", len(value)))
            else:
                entry_data.extend(struct.pack(">I", 0))

            entry_data.extend(key)
            if op == WriteOp.PUT:
                entry_data.extend(value)

            # Calculate and prepend CRC32
            crc = self._crc32(bytes(entry_data))
            final_entry = struct.pack(">I", crc) + bytes(entry_data)

            # Write to file
            self.current_file.write(final_entry)
            self.current_file_size += len(final_entry)
            self._sync()

        except Exception as e:
            raise WALError(f"Failed to append WAL entry: {e}")

    @staticmethod
    def _crc32(data: bytes) -> int:
        """Calculate CRC32 checksum (simplified).

        A real implementation would use the crc32 module.
        This is a basic polynomial-based implementation.

        Args:
            data: Data to checksum

        Returns:
            CRC32 value
        """
        crc = 0xFFFFFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320
                else:
                    crc >>= 1
        return crc ^ 0xFFFFFFFF

    def iter_entries(self) -> Iterator[WALEntry]:
        """Iterate over all WAL entries in order.

        Entries are replayed in chronological order across all WAL files.

        Yields:
            WALEntry objects

        Raises:
            CorruptionError: If checksum validation fails
        """
        # Find all WAL files
        wal_files = sorted(self.dir_path.glob("wal_*.log"))

        for wal_file in wal_files:
            with open(wal_file, "rb") as f:
                while True:
                    # Read CRC and entry data
                    crc_data = f.read(4)
                    if not crc_data:
                        break

                    crc_expected = struct.unpack(">I", crc_data)[0]

                    # Read fixed header
                    header = f.read(21)
                    if len(header) < 21:
                        raise CorruptionError(f"Incomplete WAL entry in {wal_file}")

                    timestamp_bytes = header[0:8]
                    sequence = struct.unpack(">Q", header[8:16])[0]
                    op_byte = header[16]
                    key_len = struct.unpack(">I", header[17:21])[0]

                    if key_len == 0:
                        raise CorruptionError("Zero-length key in WAL")

                    # Read value length
                    value_len_data = f.read(4)
                    if len(value_len_data) < 4:
                        raise CorruptionError("Incomplete value length in WAL")
                    value_len = struct.unpack(">I", value_len_data)[0]

                    # Read key and value
                    key = f.read(key_len)
                    if len(key) < key_len:
                        raise CorruptionError("Incomplete key data in WAL")
                    value = None
                    if value_len > 0:
                        value = f.read(value_len)
                        if len(value) < value_len:
                            raise CorruptionError("Incomplete value data in WAL")

                    # Verify CRC
                    entry_data = header + value_len_data + key + (value or b"")
                    crc_calculated = WAL._crc32(entry_data)

                    if crc_calculated != crc_expected:
                        raise CorruptionError(
                            f"CRC mismatch in WAL {wal_file}: expected {crc_expected}, got {crc_calculated}"
                        )

                    timestamp = struct.unpack(">d", timestamp_bytes)[0]
                    op = WriteOp.PUT if op_byte == 0 else WriteOp.DELETE

                    yield WALEntry(sequence=sequence, op=op, key=key, value=value, timestamp=timestamp)

    def close(self) -> None:
        """Close the WAL file."""
        if self.current_file is not None:
            self.current_file.close()
            self.current_file = None

    def __enter__(self) -> "WAL":
        """Context manager entry."""
        return self

    def __exit__(self, *args) -> None:
        """Context manager exit."""
        self.close()
