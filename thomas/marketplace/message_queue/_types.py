"""
Message queue type definitions and dataclasses.

This module defines the core data structures used throughout the message queue system,
including messages, delivery modes, acknowledgment modes, consumer groups, and configuration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class DeliveryMode(Enum):
    """Message delivery semantics."""

    AT_MOST_ONCE = "at_most_once"  # Message may be lost, delivered 0 or 1 times
    AT_LEAST_ONCE = "at_least_once"  # Message may be duplicated, delivered 1+ times
    EXACTLY_ONCE = "exactly_once"  # Message delivered exactly once (transactional)


class AckMode(Enum):
    """Consumer acknowledgment behavior."""

    AUTO = "auto"  # Automatically acknowledge after consumption
    MANUAL = "manual"  # Explicit acknowledgment required
    NACK = "nack"  # Explicit negative acknowledgment for retry


@dataclass
class Message:
    """
    A message in the queue system.

    Attributes:
        id: Unique message identifier
        topic: Topic name this message is sent to
        payload: Message content (bytes or serializable object)
        headers: Optional metadata key-value pairs
        timestamp: Creation time
        retry_count: Number of times this message has been retried
        priority: Priority level (0=lowest, 255=highest)
        partition_key: Optional key for partition assignment
        delivery_mode: Delivery semantics (default: AT_LEAST_ONCE)
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    topic: str = ""
    payload: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0
    priority: int = 128  # Medium priority (0-255)
    partition_key: str | None = None
    delivery_mode: DeliveryMode = DeliveryMode.AT_LEAST_ONCE

    def __post_init__(self) -> None:
        """Validate message fields."""
        if not self.topic:
            raise ValueError("Message topic cannot be empty")
        if not 0 <= self.priority <= 255:
            raise ValueError("Priority must be between 0 and 255")
        if self.retry_count < 0:
            raise ValueError("Retry count cannot be negative")

    def get_header(self, key: str, default: str | None = None) -> str | None:
        """
        Get a message header by key.

        Args:
            key: Header key
            default: Default value if key not found

        Returns:
            Header value or default
        """
        return self.headers.get(key, default)

    def set_header(self, key: str, value: str) -> None:
        """
        Set a message header.

        Args:
            key: Header key
            value: Header value
        """
        self.headers[key] = value


@dataclass
class ConsumerGroup:
    """
    A consumer group for coordinated message consumption.

    Attributes:
        name: Unique group identifier
        topic: Topic this group consumes from
        members: Set of consumer member IDs
        ack_mode: Acknowledgment strategy
        session_timeout_ms: Timeout for membership heartbeat
        max_poll_records: Maximum messages per fetch
        enable_auto_commit: Whether to auto-commit offsets
        auto_commit_interval_ms: Interval for auto-commit
    """

    name: str
    topic: str
    members: set = field(default_factory=set)
    ack_mode: AckMode = AckMode.AUTO
    session_timeout_ms: int = 30000
    max_poll_records: int = 500
    enable_auto_commit: bool = True
    auto_commit_interval_ms: int = 5000

    def __post_init__(self) -> None:
        """Validate consumer group fields."""
        if not self.name:
            raise ValueError("Consumer group name cannot be empty")
        if not self.topic:
            raise ValueError("Consumer group topic cannot be empty")
        if self.session_timeout_ms <= 0:
            raise ValueError("Session timeout must be positive")
        if self.max_poll_records <= 0:
            raise ValueError("Max poll records must be positive")

    def add_member(self, member_id: str) -> None:
        """
        Add a consumer to the group.

        Args:
            member_id: Consumer identifier
        """
        self.members.add(member_id)

    def remove_member(self, member_id: str) -> None:
        """
        Remove a consumer from the group.

        Args:
            member_id: Consumer identifier
        """
        self.members.discard(member_id)

    def has_member(self, member_id: str) -> bool:
        """
        Check if a member exists in the group.

        Args:
            member_id: Consumer identifier

        Returns:
            True if member is in group
        """
        return member_id in self.members


@dataclass
class TopicConfig:
    """
    Configuration for a topic.

    Attributes:
        name: Topic identifier
        num_partitions: Number of partitions for parallel processing
        replication_factor: Replica count (for distributed systems)
        retention_ms: Message retention time in milliseconds (-1 = infinite)
        retention_bytes: Max topic size in bytes (-1 = infinite)
        segment_ms: Time-based segment rotation interval (ms)
        segment_bytes: Size-based segment rotation threshold (bytes)
        compression: Compression algorithm ('gzip', 'snappy', 'lz4', 'none')
        cleanup_policy: 'delete' or 'compact'
        min_insync_replicas: Minimum replicas for acks=all
    """

    name: str
    num_partitions: int = 1
    replication_factor: int = 1
    retention_ms: int = 86400000  # 24 hours
    retention_bytes: int = -1  # Unlimited
    segment_ms: int = 3600000  # 1 hour
    segment_bytes: int = 1073741824  # 1GB
    compression: str = "gzip"
    cleanup_policy: str = "delete"
    min_insync_replicas: int = 1

    def __post_init__(self) -> None:
        """Validate topic configuration."""
        if not self.name:
            raise ValueError("Topic name cannot be empty")
        if self.num_partitions <= 0:
            raise ValueError("Number of partitions must be positive")
        if self.replication_factor <= 0:
            raise ValueError("Replication factor must be positive")
        if self.compression not in ("gzip", "snappy", "lz4", "none"):
            raise ValueError(f"Invalid compression: {self.compression}")
        if self.cleanup_policy not in ("delete", "compact"):
            raise ValueError(f"Invalid cleanup policy: {self.cleanup_policy}")
        if self.min_insync_replicas > self.replication_factor:
            raise ValueError("min_insync_replicas cannot exceed replication_factor")


@dataclass
class QueueConfig:
    """
    Global message queue configuration.

    Attributes:
        max_topics: Maximum number of topics
        max_consumer_groups: Maximum number of consumer groups
        default_retention_ms: Default message retention time
        enable_persistence: Store messages to disk
        persistence_dir: Directory for persisted messages
        enable_monitoring: Collect metrics
        monitoring_interval_ms: Metrics collection interval
        backpressure_enabled: Enable producer throttling
        max_queue_size: Maximum total messages in memory
        worker_threads: Number of async workers
    """

    max_topics: int = 10000
    max_consumer_groups: int = 5000
    default_retention_ms: int = 86400000  # 24 hours
    enable_persistence: bool = True
    persistence_dir: str = "./queue_data"
    enable_monitoring: bool = True
    monitoring_interval_ms: int = 60000  # 1 minute
    backpressure_enabled: bool = True
    max_queue_size: int = 1000000
    worker_threads: int = 4

    def __post_init__(self) -> None:
        """Validate queue configuration."""
        if self.max_topics <= 0:
            raise ValueError("max_topics must be positive")
        if self.max_consumer_groups <= 0:
            raise ValueError("max_consumer_groups must be positive")
        if self.default_retention_ms <= 0:
            raise ValueError("default_retention_ms must be positive")
        if self.monitoring_interval_ms <= 0:
            raise ValueError("monitoring_interval_ms must be positive")
        if self.max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        if self.worker_threads <= 0:
            raise ValueError("worker_threads must be positive")
