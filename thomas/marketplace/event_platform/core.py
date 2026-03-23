"""Event platform with producers, consumers, topics, and partitions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    """Event message."""

    event_id: str
    topic: str
    partition: int
    offset: int
    timestamp: datetime
    key: str | None = None
    value: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "partition": self.partition,
            "offset": self.offset,
            "timestamp": self.timestamp.isoformat(),
            "key": self.key,
            "value": self.value,
            "headers": self.headers,
        }


class Partition:
    """Topic partition with events."""

    def __init__(self, partition_id: int):
        self.partition_id = partition_id
        self.events: list[Event] = []
        self.offset = 0

    def append(self, event: Event) -> int:
        """Append event and return offset."""
        event.offset = self.offset
        self.events.append(event)
        self.offset += 1
        return event.offset

    def get_events(self, start_offset: int = 0, max_count: int = 100) -> list[Event]:
        """Get events from offset."""
        return self.events[start_offset : start_offset + max_count]

    def get_event(self, offset: int) -> Event | None:
        """Get event by offset."""
        if 0 <= offset < len(self.events):
            return self.events[offset]
        return None

    def get_latest_offset(self) -> int:
        """Get latest offset."""
        return self.offset - 1 if self.offset > 0 else -1


class Topic:
    """Event topic with multiple partitions."""

    def __init__(self, name: str, num_partitions: int = 1):
        self.name = name
        self.num_partitions = num_partitions
        self.partitions = {i: Partition(i) for i in range(num_partitions)}
        self.retention_events = 1000
        self.created_at = datetime.now()
        self._event_counter = 0

    def publish(
        self,
        key: str | None,
        value: dict[str, Any],
        headers: dict[str, str] | None = None,
        partition: int | None = None,
    ) -> str:
        """Publish event to topic."""
        self._event_counter += 1

        if partition is None:
            # Simple hash-based partition assignment
            if key:
                partition = hash(key) % self.num_partitions
            else:
                partition = self._event_counter % self.num_partitions

        partition = partition % self.num_partitions

        event = Event(
            event_id=f"{self.name}_{self._event_counter}",
            topic=self.name,
            partition=partition,
            offset=0,
            timestamp=datetime.now(),
            key=key,
            value=value,
            headers=headers or {},
        )

        self.partitions[partition].append(event)
        self._enforce_retention()
        return event.event_id

    def consume(self, partition: int, start_offset: int = 0, max_count: int = 100) -> list[Event]:
        """Consume events from partition."""
        if partition not in self.partitions:
            return []
        return self.partitions[partition].get_events(start_offset, max_count)

    def get_stats(self) -> dict[str, Any]:
        """Get topic statistics."""
        total_events = sum(len(p.events) for p in self.partitions.values())
        return {
            "name": self.name,
            "partitions": self.num_partitions,
            "total_events": total_events,
            "created_at": self.created_at.isoformat(),
            "partition_offsets": {pid: p.get_latest_offset() + 1 for pid, p in self.partitions.items()},
        }

    def _enforce_retention(self) -> None:
        """Enforce retention policy."""
        for partition in self.partitions.values():
            if len(partition.events) > self.retention_events:
                partition.events = partition.events[-self.retention_events :]


class ConsumerGroup:
    """Consumer group tracking offsets."""

    def __init__(self, group_id: str):
        self.group_id = group_id
        self.offsets: dict[tuple, int] = defaultdict(int)  # (topic, partition) -> offset
        self.members: list[str] = []

    def add_member(self, member_id: str) -> None:
        """Add consumer to group."""
        if member_id not in self.members:
            self.members.append(member_id)

    def remove_member(self, member_id: str) -> None:
        """Remove consumer from group."""
        if member_id in self.members:
            self.members.remove(member_id)

    def commit_offset(self, topic: str, partition: int, offset: int) -> None:
        """Commit offset."""
        self.offsets[(topic, partition)] = offset

    def get_offset(self, topic: str, partition: int) -> int:
        """Get current offset."""
        return self.offsets.get((topic, partition), 0)


class EventBroker:
    """Main event broker managing topics and consumers."""

    def __init__(self):
        self.topics: dict[str, Topic] = {}
        self.consumer_groups: dict[str, ConsumerGroup] = {}
        self.event_log: list[Event] = []

    def create_topic(self, name: str, num_partitions: int = 1) -> Topic:
        """Create a topic."""
        if name in self.topics:
            raise ValueError(f"Topic {name} already exists")
        topic = Topic(name, num_partitions)
        self.topics[name] = topic
        return topic

    def get_topic(self, name: str) -> Topic | None:
        """Get topic by name."""
        return self.topics.get(name)

    def delete_topic(self, name: str) -> bool:
        """Delete a topic."""
        if name in self.topics:
            del self.topics[name]
            return True
        return False

    def publish(
        self, topic_name: str, key: str | None, value: dict[str, Any], headers: dict[str, str] | None = None
    ) -> str | None:
        """Publish to topic."""
        topic = self.get_topic(topic_name)
        if not topic:
            return None
        event_id = topic.publish(key, value, headers)
        # Find published event and log it
        for partition in topic.partitions.values():
            for event in partition.events:
                if event.event_id == event_id:
                    self.event_log.append(event)
                    return event_id
        return event_id

    def create_consumer_group(self, group_id: str) -> ConsumerGroup:
        """Create consumer group."""
        if group_id in self.consumer_groups:
            raise ValueError(f"Consumer group {group_id} already exists")
        group = ConsumerGroup(group_id)
        self.consumer_groups[group_id] = group
        return group

    def get_consumer_group(self, group_id: str) -> ConsumerGroup | None:
        """Get consumer group."""
        return self.consumer_groups.get(group_id)

    def replay_events(self, topic_name: str, from_offset: int = 0) -> list[Event]:
        """Replay events from offset."""
        topic = self.get_topic(topic_name)
        if not topic:
            return []

        events = []
        for partition in topic.partitions.values():
            events.extend(partition.get_events(from_offset))
        return sorted(events, key=lambda e: e.timestamp)

    def get_broker_stats(self) -> dict[str, Any]:
        """Get broker statistics."""
        return {
            "topics": len(self.topics),
            "consumer_groups": len(self.consumer_groups),
            "total_events": len(self.event_log),
            "topic_stats": {name: topic.get_stats() for name, topic in self.topics.items()},
        }
