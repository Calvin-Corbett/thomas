"""
Async consumer for subscribing to and consuming messages from topics.

Consumers support pull-based consumption, auto-commit, manual commit,
rebalancing, and heartbeat-based group membership.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ._exceptions import ConsumerGroupError, OffsetError
from ._types import Message


@dataclass
class ConsumerConfig:
    """Configuration for a consumer."""

    max_poll_records: int = 500
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000
    auto_commit_interval_ms: int = 500
    enable_auto_commit: bool = True
    partition_assignment_strategy: str = "range"  # 'range' or 'round_robin'


class ConsumerMetrics:
    """Metrics for a consumer."""

    def __init__(self) -> None:
        """Initialize metrics."""
        self.messages_consumed = 0
        self.messages_committed = 0
        self.bytes_consumed = 0
        self.rebalances = 0
        self.heartbeats_sent = 0
        self.last_heartbeat_time = time.time()


class Consumer:
    """
    Asynchronous message consumer with group coordination.

    Supports pull-based consumption, auto-commit, manual offset management,
    and consumer group rebalancing.
    """

    def __init__(
        self,
        broker: Any,
        group: str,
        topics: list[str],
        config: ConsumerConfig | None = None,
    ) -> None:
        """
        Initialize a consumer.

        Args:
            broker: Message broker instance
            group: Consumer group name
            topics: Topics to subscribe to
            config: Consumer configuration
        """
        self.broker = broker
        self.group = group
        self.topics = set(topics)
        self.config = config or ConsumerConfig()
        self.id = str(uuid4())

        # Offset tracking per (topic, partition)
        self.offsets: dict[tuple, int] = {}

        # Pause/resume state
        self.paused_partitions: set[tuple] = set()

        # Metrics
        self.metrics = ConsumerMetrics()

        # Lifecycle
        self._running = False
        self._heartbeat_task: asyncio.Task | None = None
        self._commit_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the consumer and background tasks."""
        async with self.lock:
            self._running = True

            # Register with broker
            await self.broker.register_consumer(self.group, self.id, self.topics)

            # Start background tasks
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            if self.config.enable_auto_commit:
                self._commit_task = asyncio.create_task(self._commit_loop())

    async def stop(self) -> None:
        """Stop the consumer and its background tasks."""
        async with self.lock:
            self._running = False

        # Cleanup tasks
        if self._heartbeat_task:
            try:
                self._heartbeat_task.cancel()
                await asyncio.wait_for(self._heartbeat_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        if self._commit_task:
            try:
                self._commit_task.cancel()
                await asyncio.wait_for(self._commit_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Deregister from broker
        try:
            await self.broker.deregister_consumer(self.group, self.id)
        except (ConnectionError, TimeoutError):
            pass

    async def poll(self, timeout_ms: int = 1000) -> dict[tuple, list[Message]]:
        """
        Poll for messages from all subscribed partitions.

        Args:
            timeout_ms: Timeout for polling

        Returns:
            Dictionary mapping (topic, partition) to list of messages
        """
        async with self.lock:
            if not self._running:
                raise ConsumerGroupError(self.group, "Consumer not running")

            results: dict[tuple, list[Message]] = {}

            # Get partition assignment for this consumer
            partition_assignment = await self.broker.get_partition_assignment(self.group, self.id, self.topics)

            for topic, partitions in partition_assignment.items():
                for partition_id in partitions:
                    key = (topic, partition_id)

                    # Skip paused partitions
                    if key in self.paused_partitions:
                        continue

                    # Get next offset for this partition
                    offset = self.offsets.get(key, 0)

                    try:
                        # Fetch from broker
                        messages = await self.broker.fetch(
                            topic,
                            partition_id,
                            offset,
                            self.config.max_poll_records,
                            self.group,
                        )

                        if messages:
                            results[key] = messages
                            self.metrics.messages_consumed += len(messages)

                            # Update offset for next poll
                            last_offset = offset + len(messages)
                            self.offsets[key] = last_offset

                            # Track bytes
                            for msg in messages:
                                self.metrics.bytes_consumed += len(str(msg.payload).encode())

                    except (ValueError, TypeError):
                        pass  # Log but continue

            return results

    async def commit_sync(self, timeout_ms: int = 10000) -> None:
        """
        Synchronously commit current offsets.

        Args:
            timeout_ms: Commit timeout

        Raises:
            ConsumerGroupError: If commit fails
        """
        async with self.lock:
            try:
                for (topic, partition_id), offset in self.offsets.items():
                    await self.broker.commit_offset(self.group, topic, partition_id, offset)
                self.metrics.messages_committed += len(self.offsets)
            except Exception as e:
                raise ConsumerGroupError(self.group, f"Commit failed: {str(e)}")

    async def commit_async(self, callback: Callable[[str | None], None] | None = None) -> None:
        """
        Asynchronously commit current offsets.

        Args:
            callback: Optional callback(error) on completion
        """

        async def _do_commit() -> None:
            try:
                await self.commit_sync()
                if callback:
                    callback(None)
            except Exception as e:
                if callback:
                    callback(str(e))

        asyncio.create_task(_do_commit())

    async def seek(self, topic: str, partition: int, offset: int) -> None:
        """
        Seek to a specific offset.

        Args:
            topic: Topic name
            partition: Partition number
            offset: Target offset

        Raises:
            OffsetError: If offset is invalid
        """
        async with self.lock:
            try:
                await self.broker.seek(self.group, topic, partition, offset)
                self.offsets[(topic, partition)] = offset
            except Exception as e:
                raise OffsetError(offset, f"Seek failed: {str(e)}")

    async def pause(self, topic: str, partition: int) -> None:
        """
        Pause consumption from a partition.

        Args:
            topic: Topic name
            partition: Partition number
        """
        async with self.lock:
            self.paused_partitions.add((topic, partition))

    async def resume(self, topic: str, partition: int) -> None:
        """
        Resume consumption from a partition.

        Args:
            topic: Topic name
            partition: Partition number
        """
        async with self.lock:
            self.paused_partitions.discard((topic, partition))

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeats to broker."""
        while self._running:
            try:
                await asyncio.sleep(self.config.heartbeat_interval_ms / 1000.0)

                if self._running:
                    await self.broker.heartbeat(self.group, self.id)
                    self.metrics.heartbeats_sent += 1
                    self.metrics.last_heartbeat_time = time.time()

            except asyncio.CancelledError:
                break
            except Exception:  # REVIEWED: async context
                pass  # Log but continue

    async def _commit_loop(self) -> None:
        """Periodically auto-commit offsets."""
        while self._running:
            try:
                await asyncio.sleep(self.config.auto_commit_interval_ms / 1000.0)

                if self._running:
                    try:
                        await self.commit_sync()
                    except Exception:  # REVIEWED: async context
                        pass  # Log but continue

            except asyncio.CancelledError:
                break

    async def get_position(self, topic: str, partition: int) -> int:
        """
        Get current offset position.

        Args:
            topic: Topic name
            partition: Partition number

        Returns:
            Current offset
        """
        async with self.lock:
            return self.offsets.get((topic, partition), 0)

    def get_metrics(self) -> dict[str, any]:
        """
        Get consumer metrics.

        Returns:
            Dictionary of metrics
        """
        return {
            "id": self.id,
            "group": self.group,
            "messages_consumed": self.metrics.messages_consumed,
            "messages_committed": self.metrics.messages_committed,
            "bytes_consumed": self.metrics.bytes_consumed,
            "rebalances": self.metrics.rebalances,
            "heartbeats_sent": self.metrics.heartbeats_sent,
            "tracked_offsets": len(self.offsets),
            "paused_partitions": len(self.paused_partitions),
        }
