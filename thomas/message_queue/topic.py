"""
Topic implementation with partitioned storage and offset tracking.

Topics are subdivided into partitions for parallel processing. Each partition
maintains an ordered log of messages and tracks offsets per consumer group.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from ._exceptions import OffsetError, PartitionError
from ._types import Message, TopicConfig


@dataclass
class PartitionOffset:
    """Tracks message offsets for a consumer group in a partition."""

    group: str
    partition: int
    committed_offset: int = -1
    pending_offsets: dict[int, bool] = field(default_factory=dict)  # offset -> acked

    def commit(self, offset: int) -> None:
        """Commit an offset for this partition."""
        if offset >= 0 and (self.committed_offset < 0 or offset > self.committed_offset):
            self.committed_offset = offset

    def mark_pending(self, offset: int) -> None:
        """Mark an offset as pending acknowledgment."""
        self.pending_offsets[offset] = False

    def ack(self, offset: int) -> bool:
        """Mark an offset as acknowledged. Returns True if all prior offsets acked."""
        if offset in self.pending_offsets:
            self.pending_offsets[offset] = True
            # Check if we can commit up to this offset
            if offset == self.committed_offset + 1:
                next_offset = offset + 1
                while next_offset in self.pending_offsets and self.pending_offsets[next_offset]:
                    next_offset += 1
                self.committed_offset = next_offset - 1
                # Cleanup committed offsets
                for off in list(self.pending_offsets.keys()):
                    if off <= self.committed_offset:
                        del self.pending_offsets[off]
                return True
        return False

    def get_next_offset(self) -> int:
        """Get the next offset to fetch."""
        return self.committed_offset + 1


@dataclass
class SegmentMetadata:
    """Metadata for a message segment."""

    id: int
    start_offset: int
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0

    def add_message(self, msg: Message) -> int:
        """Add message to segment and return its offset."""
        offset = self.start_offset + len(self.messages)
        self.messages.append(msg)
        self.size_bytes += len(str(msg.payload).encode("utf-8"))
        self.last_accessed = datetime.utcnow()
        return offset

    def is_expired(self, retention_ms: int) -> bool:
        """Check if segment is past retention period."""
        if retention_ms < 0:
            return False
        age_ms = (datetime.utcnow() - self.created_at).total_seconds() * 1000
        return age_ms > retention_ms

    def exceeds_size(self, limit_bytes: int) -> bool:
        """Check if segment exceeds size limit."""
        if limit_bytes < 0:
            return False
        return self.size_bytes > limit_bytes


class Partition:
    """
    A partition is a sequential log of messages within a topic.

    Messages within a partition are ordered and each has a monotonically
    increasing offset. Consumer groups track their progress per partition.
    """

    def __init__(self, topic: str, partition_id: int, config: TopicConfig) -> None:
        """
        Initialize a partition.

        Args:
            topic: Topic name
            partition_id: Partition number
            config: Topic configuration
        """
        self.topic = topic
        self.id = partition_id
        self.config = config
        self.lock = asyncio.Lock()

        # Message count and size tracking
        self.message_count = 0
        self.total_bytes = 0

        # Segments (time-based and size-based batches)
        self.segments: list[SegmentMetadata] = []
        self.current_segment: SegmentMetadata | None = None
        self.next_segment_id = 0
        self._create_segment()

        # Consumer group offset tracking
        self.group_offsets: dict[str, PartitionOffset] = {}

    def _create_segment(self) -> None:
        """Create a new segment."""
        segment = SegmentMetadata(
            id=self.next_segment_id,
            start_offset=self.message_count,
        )
        self.segments.append(segment)
        self.current_segment = segment
        self.next_segment_id += 1

    async def append(self, message: Message) -> int:
        """
        Append a message to this partition.

        Args:
            message: Message to append
            message: Message to append

        Returns:
            The offset of the appended message

        Raises:
            PartitionError: If append fails
        """
        async with self.lock:
            try:
                if self.current_segment is None:
                    self._create_segment()

                # Check if current segment needs rotation
                should_rotate = False
                if self.config.segment_bytes > 0:
                    if self.current_segment.exceeds_size(self.config.segment_bytes):
                        should_rotate = True

                if should_rotate:
                    self._create_segment()

                # Add message to current segment
                offset = self.current_segment.add_message(message)
                self.message_count += 1
                self.total_bytes += len(str(message.payload).encode("utf-8"))

                return offset

            except Exception as e:
                raise PartitionError(self.id, self.topic, f"Failed to append message: {str(e)}")

    async def fetch(
        self,
        offset: int,
        max_records: int,
        group: str,
    ) -> list[Message]:
        """
        Fetch messages from a partition.

        Args:
            offset: Starting offset
            max_records: Maximum messages to return
            group: Consumer group name

        Returns:
            List of messages

        Raises:
            OffsetError: If offset is invalid
        """
        async with self.lock:
            if offset < 0 or offset >= self.message_count:
                raise OffsetError(offset, f"Offset out of range [0, {self.message_count})")

            messages = []
            current_offset = offset

            for segment in self.segments:
                if segment.start_offset > current_offset:
                    break

                segment_end = segment.start_offset + len(segment.messages)
                if current_offset < segment_end:
                    # Found the segment containing our offset
                    local_offset = current_offset - segment.start_offset
                    for i in range(local_offset, len(segment.messages)):
                        if len(messages) >= max_records:
                            break
                        msg = segment.messages[i]
                        messages.append(msg)
                        current_offset += 1

                        # Mark offset as pending for this group
                        if group:
                            if group not in self.group_offsets:
                                self.group_offsets[group] = PartitionOffset(group, self.id)
                            self.group_offsets[group].mark_pending(current_offset - 1)

                    if len(messages) >= max_records:
                        break

            return messages

    async def commit_offset(self, group: str, offset: int) -> None:
        """
        Commit an offset for a consumer group.

        Args:
            group: Consumer group name
            offset: Offset to commit
        """
        async with self.lock:
            if group not in self.group_offsets:
                self.group_offsets[group] = PartitionOffset(group, self.id)
            self.group_offsets[group].commit(offset)

    async def ack_offset(self, group: str, offset: int) -> bool:
        """
        Acknowledge an offset for a consumer group.

        Args:
            group: Consumer group name
            offset: Offset to acknowledge

        Returns:
            True if offset was committed
        """
        async with self.lock:
            if group not in self.group_offsets:
                self.group_offsets[group] = PartitionOffset(group, self.id)
            return self.group_offsets[group].ack(offset)

    async def seek(self, group: str, offset: int) -> None:
        """
        Seek to an offset for a consumer group.

        Args:
            group: Consumer group name
            offset: Target offset

        Raises:
            OffsetError: If offset is invalid
        """
        async with self.lock:
            if offset < -1:
                raise OffsetError(offset, "Offset out of range [-1, inf)")
            if group not in self.group_offsets:
                self.group_offsets[group] = PartitionOffset(group, self.id)
            self.group_offsets[group].committed_offset = offset

    async def cleanup_retention(self) -> int:
        """
        Clean up segments that exceed retention policy.

        Returns:
            Number of messages deleted
        """
        async with self.lock:
            deleted_count = 0
            segments_to_remove = []

            for segment in self.segments:
                # Check time-based retention
                if segment.is_expired(self.config.retention_ms):
                    segments_to_remove.append(segment)
                    deleted_count += len(segment.messages)

            # Check size-based retention (keep latest segments)
            if self.config.retention_bytes > 0:
                total_bytes = sum(s.size_bytes for s in self.segments)
                for segment in self.segments[:-1]:  # Never delete current segment
                    if total_bytes > self.config.retention_bytes:
                        segments_to_remove.append(segment)
                        total_bytes -= segment.size_bytes
                        deleted_count += len(segment.messages)

            # Remove segments and update offsets
            for segment in segments_to_remove:
                self.segments.remove(segment)

            return deleted_count

    async def get_offset_for_group(self, group: str) -> int:
        """
        Get the committed offset for a consumer group.

        Args:
            group: Consumer group name

        Returns:
            Last committed offset (-1 if none)
        """
        async with self.lock:
            if group in self.group_offsets:
                return self.group_offsets[group].committed_offset
            return -1

    async def get_stats(self) -> dict[str, int]:
        """
        Get partition statistics.

        Returns:
            Dictionary with message count, total bytes, etc.
        """
        async with self.lock:
            return {
                "message_count": self.message_count,
                "total_bytes": self.total_bytes,
                "segments": len(self.segments),
                "consumer_groups": len(self.group_offsets),
            }


class Topic:
    """
    A topic is a logical stream of messages with multiple partitions.

    Topics are partitioned to enable parallel consumption. Each partition
    is an ordered sequence of messages.
    """

    def __init__(self, config: TopicConfig) -> None:
        """
        Initialize a topic.

        Args:
            config: Topic configuration
        """
        self.config = config
        self.partitions: list[Partition] = []
        self.lock = asyncio.Lock()

        # Create partitions
        for i in range(config.num_partitions):
            self.partitions.append(Partition(config.name, i, config))

        self._next_partition_idx = 0
        self.created_at = datetime.utcnow()

    def _select_partition(self, key: str | None) -> Partition:
        """
        Select a partition using partitioner strategy.

        Args:
            key: Optional partition key

        Returns:
            Selected partition
        """
        if key is None:
            # Round-robin
            idx = self._next_partition_idx
            self._next_partition_idx = (self._next_partition_idx + 1) % len(self.partitions)
        else:
            # Key-based hash
            idx = hash(key) % len(self.partitions)

        return self.partitions[idx]

    async def append(self, message: Message) -> tuple[int, int]:
        """
        Append a message to an appropriate partition.

        Args:
            message: Message to append

        Returns:
            Tuple of (partition_id, offset)
        """
        message.topic = self.config.name
        partition = self._select_partition(message.partition_key)
        offset = await partition.append(message)
        return (partition.id, offset)

    async def fetch(self, partition_id: int, offset: int, max_records: int, group: str) -> list[Message]:
        """
        Fetch messages from a partition.

        Args:
            partition_id: Partition to fetch from
            offset: Starting offset
            max_records: Maximum messages
            group: Consumer group name

        Returns:
            List of messages
        """
        if partition_id < 0 or partition_id >= len(self.partitions):
            raise PartitionError(partition_id, self.config.name, "Invalid partition")

        return await self.partitions[partition_id].fetch(offset, max_records, group)

    async def commit_offset(self, partition_id: int, group: str, offset: int) -> None:
        """Commit offset for a consumer group in a partition."""
        if partition_id < 0 or partition_id >= len(self.partitions):
            raise PartitionError(partition_id, self.config.name, "Invalid partition")

        await self.partitions[partition_id].commit_offset(group, offset)

    async def ack_offset(self, partition_id: int, group: str, offset: int) -> bool:
        """Acknowledge offset for a consumer group in a partition."""
        if partition_id < 0 or partition_id >= len(self.partitions):
            raise PartitionError(partition_id, self.config.name, "Invalid partition")

        return await self.partitions[partition_id].ack_offset(group, offset)

    async def seek(self, partition_id: int, group: str, offset: int) -> None:
        """Seek to offset for a consumer group in a partition."""
        if partition_id < 0 or partition_id >= len(self.partitions):
            raise PartitionError(partition_id, self.config.name, "Invalid partition")

        await self.partitions[partition_id].seek(group, offset)

    async def cleanup_retention(self) -> int:
        """Clean up all partitions based on retention policy."""
        total_deleted = 0
        for partition in self.partitions:
            total_deleted += await partition.cleanup_retention()
        return total_deleted

    async def get_stats(self) -> dict[str, any]:
        """Get topic-wide statistics."""
        stats = {
            "name": self.config.name,
            "partitions": len(self.partitions),
            "total_messages": 0,
            "total_bytes": 0,
        }

        for partition in self.partitions:
            partition_stats = await partition.get_stats()
            stats["total_messages"] += partition_stats["message_count"]
            stats["total_bytes"] += partition_stats["total_bytes"]

        return stats
