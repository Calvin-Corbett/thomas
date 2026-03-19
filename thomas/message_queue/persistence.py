"""
Message persistence to disk with segment-based log storage.

Implements segment files with index for offset lookup,
log compaction/deletion cleanup, and crash recovery.
"""

import asyncio
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from thomas.core.safe_pickle import safe_pickle_loads

from ._exceptions import PersistenceError
from ._types import DeliveryMode, Message


@dataclass
class SegmentInfo:
    """Metadata about a persisted segment."""

    segment_id: int
    topic: str
    partition: int
    start_offset: int
    end_offset: int
    file_size: int
    created_at: datetime
    message_count: int


class SegmentWriter:
    """Writes messages to a segment file."""

    def __init__(self, path: Path, segment_id: int) -> None:
        """
        Initialize segment writer.

        Args:
            path: Path to segment file
            segment_id: Segment identifier
        """
        self.path = path
        self.segment_id = segment_id
        self.messages: list[Message] = []
        self.offsets: list[int] = []
        self.lock = asyncio.Lock()

    async def append(self, message: Message, offset: int) -> None:
        """
        Append message to segment.

        Args:
            message: Message to append
            offset: Message offset
        """
        async with self.lock:
            self.messages.append(message)
            self.offsets.append(offset)

    async def flush(self) -> int:
        """
        Flush messages to disk.

        Returns:
            Number of bytes written

        Raises:
            PersistenceError: If write fails
        """
        async with self.lock:
            if not self.messages:
                return 0

            try:
                with open(self.path, "wb") as f:
                    # Write interleaved records:
                    # [offset(8 bytes)][message_length(4 bytes)][pickle(message)]
                    for offset, message in zip(self.offsets, self.messages):
                        f.write(offset.to_bytes(8, "big"))
                        data = pickle.dumps(message)
                        f.write(len(data).to_bytes(4, "big"))
                        f.write(data)

                return self.path.stat().st_size

            except Exception as e:
                raise PersistenceError(f"Failed to flush segment {self.segment_id}", e)


class SegmentReader:
    """Reads messages from a segment file."""

    def __init__(self, path: Path) -> None:
        """
        Initialize segment reader.

        Args:
            path: Path to segment file
        """
        self.path = path
        self.messages: list[Message] | None = None
        self.offsets: list[int] | None = None
        self.lock = asyncio.Lock()

    async def load(self) -> None:
        """
        Load segment from disk.

        Raises:
            PersistenceError: If read fails
        """
        async with self.lock:
            if self.messages is not None:
                return

            try:
                self.messages = []
                self.offsets = []

                if not self.path.exists():
                    return

                with open(self.path, "rb") as f:
                    data = f.read()

                if len(data) == 0:
                    return

                offset = 0
                msg_count = 0

                # Read offset index first
                while offset < len(data):
                    if offset + 8 > len(data):
                        break

                    msg_offset = int.from_bytes(data[offset : offset + 8], "big")
                    self.offsets.append(msg_offset)
                    offset += 8
                    msg_count += 1

                    # Read message
                    if offset + 4 > len(data):
                        break

                    msg_len = int.from_bytes(data[offset : offset + 4], "big")
                    offset += 4

                    if offset + msg_len > len(data):
                        break

                    msg_data = data[offset : offset + msg_len]
                    offset += msg_len

                    message = safe_pickle_loads(
                        msg_data,
                        allowed_globals={
                            ("thomas.message_queue._types", "DeliveryMode"): DeliveryMode,
                            ("thomas.message_queue._types", "Message"): Message,
                        },
                    )
                    self.messages.append(message)

            except Exception as e:
                raise PersistenceError(f"Failed to load segment {self.path}", e)

    async def get_message(self, index: int) -> Message | None:
        """
        Get message by index.

        Args:
            index: Message index in segment

        Returns:
            Message or None
        """
        async with self.lock:
            if self.messages is None:
                await self.load()

            if self.messages and 0 <= index < len(self.messages):
                return self.messages[index]

            return None

    async def get_offset(self, index: int) -> int | None:
        """
        Get offset for message index.

        Args:
            index: Message index

        Returns:
            Offset or None
        """
        async with self.lock:
            if self.offsets is None:
                await self.load()

            if self.offsets and 0 <= index < len(self.offsets):
                return self.offsets[index]

            return None


class PersistenceManager:
    """
    Manages message persistence to disk.

    Handles segment file creation/rotation, cleanup policies,
    and recovery from persistent storage.
    """

    def __init__(self, base_path: str) -> None:
        """
        Initialize persistence manager.

        Args:
            base_path: Base directory for segment files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

        self.segments: dict[tuple[str, int], SegmentWriter] = {}
        self.readers: dict[tuple[str, int], SegmentReader] = {}
        self.lock = asyncio.Lock()

    async def append_message(
        self,
        topic: str,
        partition: int,
        message: Message,
        offset: int,
    ) -> None:
        """
        Append message to persistent segment.

        Args:
            topic: Topic name
            partition: Partition number
            message: Message to persist
            offset: Message offset
        """
        key = (topic, partition)

        async with self.lock:
            if key not in self.segments:
                # Create new segment
                segment_id = int(datetime.utcnow().timestamp() * 1000)
                path = self.base_path / f"{topic}_{partition}_{segment_id}.seg"
                self.segments[key] = SegmentWriter(path, segment_id)

            writer = self.segments[key]

        await writer.append(message, offset)

    async def flush_segment(self, topic: str, partition: int) -> int:
        """
        Flush a segment to disk.

        Args:
            topic: Topic name
            partition: Partition number

        Returns:
            Bytes written
        """
        key = (topic, partition)

        async with self.lock:
            if key in self.segments:
                writer = self.segments[key]
                return await writer.flush()

        return 0

    async def load_segment(
        self,
        topic: str,
        partition: int,
        segment_id: int,
    ) -> SegmentReader | None:
        """
        Load a segment from disk.

        Args:
            topic: Topic name
            partition: Partition number
            segment_id: Segment identifier

        Returns:
            SegmentReader or None if not found
        """
        key = (topic, partition)

        async with self.lock:
            if key not in self.readers:
                path = self.base_path / f"{topic}_{partition}_{segment_id}.seg"
                if path.exists():
                    reader = SegmentReader(path)
                    await reader.load()
                    self.readers[key] = reader
                    return reader

            return self.readers.get(key)

    async def get_message(
        self,
        topic: str,
        partition: int,
        offset: int,
    ) -> Message | None:
        """
        Retrieve a message by offset.

        Args:
            topic: Topic name
            partition: Partition number
            offset: Message offset

        Returns:
            Message or None
        """
        # Find segment containing offset
        segment_files = sorted(self.base_path.glob(f"{topic}_{partition}_*.seg"))

        for segment_file in segment_files:
            reader = SegmentReader(segment_file)
            await reader.load()

            if reader.offsets and offset in reader.offsets:
                index = reader.offsets.index(offset)
                return await reader.get_message(index)

        return None

    async def cleanup_segments(
        self,
        topic: str,
        partition: int,
        retention_ms: int,
    ) -> int:
        """
        Clean up old segments based on retention.

        Args:
            topic: Topic name
            partition: Partition number
            retention_ms: Retention period in milliseconds

        Returns:
            Number of messages deleted
        """
        if retention_ms < 0:
            return 0

        deleted_count = 0
        now = datetime.utcnow()
        cutoff = now.timestamp() - (retention_ms / 1000.0)

        segment_files = list(self.base_path.glob(f"{topic}_{partition}_*.seg"))

        # Keep at least one segment
        if len(segment_files) <= 1:
            return 0

        for segment_file in segment_files[:-1]:  # Never delete latest
            # Check age
            ctime = segment_file.stat().st_ctime
            if ctime < cutoff:
                try:
                    # Count messages before deletion
                    reader = SegmentReader(segment_file)
                    await reader.load()
                    deleted_count += len(reader.messages or [])

                    # Remove file
                    segment_file.unlink()

                    # Clear from cache
                    async with self.lock:
                        key = (topic, partition)
                        self.readers.pop(key, None)

                except (OSError, FileNotFoundError):
                    pass

        return deleted_count

    async def get_stats(self) -> dict[str, any]:
        """
        Get persistence statistics.

        Returns:
            Dictionary of metrics
        """
        total_size = sum(f.stat().st_size for f in self.base_path.glob("*.seg"))
        segment_count = len(list(self.base_path.glob("*.seg")))

        return {
            "total_segments": segment_count,
            "total_size_bytes": total_size,
            "cached_readers": len(self.readers),
            "active_writers": len(self.segments),
        }
