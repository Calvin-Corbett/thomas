"""
Central message broker coordinating producers, consumers, and topics.

The broker manages topic lifecycle, producer/consumer registration,
message routing, consumer group coordination, and metrics collection.
"""

import asyncio
import time
from typing import Any

from ._exceptions import TopicAlreadyExistsError, TopicNotFoundError
from ._types import Message, QueueConfig, TopicConfig
from .topic import Topic


class Broker:
    """
    Central message broker managing topics, producers, and consumers.

    Coordinates message routing, consumer group rebalancing, and
    metrics collection for the entire queue system.
    """

    def __init__(self, config: QueueConfig | None = None) -> None:
        """
        Initialize the broker.

        Args:
            config: Broker configuration
        """
        self.config = config or QueueConfig()
        self.topics: dict[str, Topic] = {}
        self.producers: dict[str, Any] = {}
        self.consumer_groups: dict[str, dict[str, set[str]]] = {}
        self.consumer_members: dict[tuple, str] = {}  # (group, consumer_id) -> topics
        self.last_heartbeat: dict[tuple, float] = {}
        self.lock = asyncio.Lock()
        self._running = False
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the broker and background maintenance tasks."""
        async with self.lock:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        """Stop the broker and cleanup resources."""
        async with self.lock:
            self._running = False

        if self._cleanup_task:
            try:
                self._cleanup_task.cancel()
                await asyncio.wait_for(self._cleanup_task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def create_topic(self, config: TopicConfig) -> None:
        """
        Create a new topic.

        Args:
            config: Topic configuration

        Raises:
            TopicAlreadyExistsError: If topic already exists
        """
        async with self.lock:
            if config.name in self.topics:
                raise TopicAlreadyExistsError(config.name)

            if len(self.topics) >= self.config.max_topics:
                raise RuntimeError(f"Max topics ({self.config.max_topics}) reached")

            self.topics[config.name] = Topic(config)

    async def delete_topic(self, topic: str) -> None:
        """
        Delete a topic.

        Args:
            topic: Topic name

        Raises:
            TopicNotFoundError: If topic does not exist
        """
        async with self.lock:
            if topic not in self.topics:
                raise TopicNotFoundError(topic)

            del self.topics[topic]

            # Cleanup consumer groups for this topic
            if topic in self.consumer_groups:
                del self.consumer_groups[topic]

    async def list_topics(self) -> list[str]:
        """
        List all topics.

        Returns:
            List of topic names
        """
        async with self.lock:
            return list(self.topics.keys())

    async def publish(self, message: Message) -> tuple:
        """
        Publish a message to a topic.

        Args:
            message: Message to publish

        Returns:
            Tuple of (partition_id, offset)

        Raises:
            TopicNotFoundError: If topic does not exist
        """
        async with self.lock:
            if message.topic not in self.topics:
                raise TopicNotFoundError(message.topic)

            topic = self.topics[message.topic]

        partition_id, offset = await topic.append(message)
        return (partition_id, offset)

    async def fetch(
        self,
        topic: str,
        partition_id: int,
        offset: int,
        max_records: int,
        group: str,
    ) -> list[Message]:
        """
        Fetch messages from a topic partition.

        Args:
            topic: Topic name
            partition_id: Partition number
            offset: Starting offset
            max_records: Maximum messages
            group: Consumer group name

        Returns:
            List of messages

        Raises:
            TopicNotFoundError: If topic does not exist
        """
        async with self.lock:
            if topic not in self.topics:
                raise TopicNotFoundError(topic)

            topic_obj = self.topics[topic]

        return await topic_obj.fetch(partition_id, offset, max_records, group)

    async def commit_offset(self, group: str, topic: str, partition: int, offset: int) -> None:
        """
        Commit offset for a consumer group.

        Args:
            group: Consumer group name
            topic: Topic name
            partition: Partition number
            offset: Offset to commit
        """
        async with self.lock:
            if topic not in self.topics:
                return

            topic_obj = self.topics[topic]

        await topic_obj.commit_offset(partition, group, offset)

    async def seek(self, group: str, topic: str, partition: int, offset: int) -> None:
        """
        Seek to an offset for a consumer group.

        Args:
            group: Consumer group name
            topic: Topic name
            partition: Partition number
            offset: Target offset
        """
        async with self.lock:
            if topic not in self.topics:
                return

            topic_obj = self.topics[topic]

        await topic_obj.seek(partition, group, offset)

    async def register_consumer(self, group: str, consumer_id: str, topics: set[str]) -> None:
        """
        Register a consumer with a group.

        Args:
            group: Consumer group name
            consumer_id: Consumer identifier
            topics: Topics to subscribe to
        """
        async with self.lock:
            if group not in self.consumer_groups:
                self.consumer_groups[group] = {}

            for topic in topics:
                if topic not in self.consumer_groups[group]:
                    self.consumer_groups[group][topic] = set()
                self.consumer_groups[group][topic].add(consumer_id)

            self.consumer_members[(group, consumer_id)] = topics
            self.last_heartbeat[(group, consumer_id)] = time.time()

    async def deregister_consumer(self, group: str, consumer_id: str) -> None:
        """
        Deregister a consumer from a group.

        Args:
            group: Consumer group name
            consumer_id: Consumer identifier
        """
        async with self.lock:
            if group in self.consumer_groups:
                for topic in list(self.consumer_groups[group].keys()):
                    self.consumer_groups[group][topic].discard(consumer_id)

            self.consumer_members.pop((group, consumer_id), None)
            self.last_heartbeat.pop((group, consumer_id), None)

    async def heartbeat(self, group: str, consumer_id: str) -> None:
        """
        Record a heartbeat from a consumer.

        Args:
            group: Consumer group name
            consumer_id: Consumer identifier
        """
        async with self.lock:
            self.last_heartbeat[(group, consumer_id)] = time.time()

    async def get_partition_assignment(self, group: str, consumer_id: str, topics: set[str]) -> dict[str, list[int]]:
        """
        Get partition assignment for a consumer.

        Uses range-based or round-robin assignment strategy.

        Args:
            group: Consumer group name
            consumer_id: Consumer identifier
            topics: Topics to get assignment for

        Returns:
            Dictionary mapping topic name to partition list
        """
        async with self.lock:
            assignment: dict[str, list[int]] = {}

            for topic in topics:
                if topic not in self.topics:
                    continue

                topic_obj = self.topics[topic]
                num_partitions = topic_obj.config.num_partitions

                # Get all consumers for this topic in the group
                consumers = sorted(self.consumer_groups.get(group, {}).get(topic, []))

                if not consumers:
                    assignment[topic] = []
                    continue

                # Range-based assignment
                partitions_per_consumer = num_partitions // len(consumers)
                extra = num_partitions % len(consumers)
                consumer_index = consumers.index(consumer_id)

                start = consumer_index * partitions_per_consumer + min(consumer_index, extra)
                end = start + partitions_per_consumer + (1 if consumer_index < extra else 0)

                assignment[topic] = list(range(start, end))

            return assignment

    async def _maintenance_loop(self) -> None:
        """Periodically cleanup and enforce retention policies."""
        while self._running:
            try:
                await asyncio.sleep(60)  # 1 minute

                if self._running:
                    await self._cleanup_dead_consumers()
                    await self._apply_retention_policies()

            except asyncio.CancelledError:
                break
            except (ValueError, TypeError):
                pass

    async def _cleanup_dead_consumers(self) -> None:
        """Remove consumers that haven't heartbeated."""
        async with self.lock:
            current_time = time.time()
            timeout_ms = 30000  # 30 seconds

            dead_consumers = []
            for (group, consumer_id), last_hb in self.last_heartbeat.items():
                age_ms = (current_time - last_hb) * 1000
                if age_ms > timeout_ms:
                    dead_consumers.append((group, consumer_id))

            for group, consumer_id in dead_consumers:
                # Cleanup
                if group in self.consumer_groups:
                    for topic in list(self.consumer_groups[group].keys()):
                        self.consumer_groups[group][topic].discard(consumer_id)

                self.consumer_members.pop((group, consumer_id), None)
                self.last_heartbeat.pop((group, consumer_id), None)

    async def _apply_retention_policies(self) -> None:
        """Apply retention policy to all topics."""
        async with self.lock:
            for topic in list(self.topics.values()):
                try:
                    await topic.cleanup_retention()
                except (ValueError, TypeError):
                    pass

    async def get_broker_stats(self) -> dict[str, any]:
        """
        Get overall broker statistics.

        Returns:
            Dictionary of broker metrics
        """
        async with self.lock:
            total_messages = 0
            total_bytes = 0

            for topic_obj in self.topics.values():
                stats = await topic_obj.get_stats()
                total_messages += stats["total_messages"]
                total_bytes += stats["total_bytes"]

            return {
                "topics": len(self.topics),
                "consumer_groups": len(self.consumer_groups),
                "active_consumers": len(self.consumer_members),
                "total_messages": total_messages,
                "total_bytes": total_bytes,
            }

    async def get_topic_stats(self, topic: str) -> dict[str, any]:
        """
        Get statistics for a specific topic.

        Args:
            topic: Topic name

        Returns:
            Topic statistics

        Raises:
            TopicNotFoundError: If topic does not exist
        """
        async with self.lock:
            if topic not in self.topics:
                raise TopicNotFoundError(topic)

            topic_obj = self.topics[topic]

        return await topic_obj.get_stats()
