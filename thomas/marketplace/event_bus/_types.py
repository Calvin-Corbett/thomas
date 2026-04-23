"""
Type definitions for the event bus system.

Provides the core data structures and protocols for the typed pub/sub event system
with event sourcing support.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, TypeVar

T = TypeVar("T")
E = TypeVar("E", bound="Event")


class Event:
    """
    Base class for all events in the system.

    Events are immutable messages that represent facts about state changes in the domain.
    They include metadata for tracking, correlation, and replay purposes.

    Attributes:
        id: Unique identifier for this event instance
        type: Domain-specific event type name (e.g., 'UserCreated')
        timestamp: When the event occurred (UTC)
        source: The aggregate/entity that originated the event
        correlation_id: Links related events across system boundaries
        causation_id: ID of the event that caused this event
        metadata: Additional context (user, version, etc.)
    """

    def __init__(
        self,
        event_type: str,
        source: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
        event_id: str | None = None,
    ) -> None:
        self.id: str = event_id or str(uuid.uuid4())
        self.type: str = event_type
        self.timestamp: datetime = timestamp or datetime.utcnow()
        self.source: str = source
        self.correlation_id: str = correlation_id or self.id
        self.causation_id: str | None = causation_id
        self.metadata: dict[str, Any] = metadata or {}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"type={self.type!r}, source={self.source!r}, "
            f"timestamp={self.timestamp.isoformat()!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Event):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class EventHandler(Protocol):
    """
    Protocol for event handlers.

    Handlers can be synchronous or asynchronous and receive events
    for processing.
    """

    async def __call__(self, event: Event) -> None:
        """
        Handle an event.

        Args:
            event: The event to handle

        Raises:
            Any exception to indicate handler failure
        """
        ...


class DeliveryGuarantee(Enum):
    """Delivery guarantee semantics for event handlers."""

    AT_LEAST_ONCE = "at_least_once"  # May be called multiple times
    AT_MOST_ONCE = "at_most_once"  # May be skipped on failure
    EXACTLY_ONCE = "exactly_once"  # Called exactly once (best effort)


class HandlerPriority(Enum):
    """Priority levels for event handler execution order."""

    CRITICAL = 10
    HIGH = 5
    NORMAL = 0
    LOW = -5
    BACKGROUND = -10


@dataclass
class EventFilter:
    """
    Filter criteria for selecting events.

    Attributes:
        event_types: Specific event types to match (None = all types)
        sources: Specific sources to match (None = all sources)
        start_time: Include events from this time onwards
        end_time: Include events up to this time
        correlation_id: Match events with specific correlation ID
        include_metadata_keys: Only match if metadata contains these keys
    """

    event_types: set[str] | None = None
    sources: set[str] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    correlation_id: str | None = None
    include_metadata_keys: set[str] | None = None

    def matches(self, event: Event) -> bool:
        """
        Check if an event matches this filter.

        Args:
            event: The event to check

        Returns:
            True if the event matches all filter criteria
        """
        if self.event_types and event.type not in self.event_types:
            return False
        if self.sources and event.source not in self.sources:
            return False
        if self.start_time and event.timestamp < self.start_time:
            return False
        if self.end_time and event.timestamp > self.end_time:
            return False
        if self.correlation_id and event.correlation_id != self.correlation_id:
            return False
        if self.include_metadata_keys:
            if not all(key in event.metadata for key in self.include_metadata_keys):
                return False
        return True


@dataclass
class EventEnvelope:
    """
    Wrapper for an event with additional processing metadata.

    Attributes:
        event: The actual domain event
        sequence_number: Global ordering in event store
        stream_name: Stream this event belongs to
        stream_version: Version within its stream
        attempts: Number of delivery attempts
        last_error: Last error encountered, if any
        metadata: Additional envelope-level metadata
    """

    event: Event
    sequence_number: int = 0
    stream_name: str = ""
    stream_version: int = 0
    attempts: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"EventEnvelope(event={self.event.type!r}, "
            f"sequence={self.sequence_number}, version={self.stream_version})"
        )


@dataclass
class Subscription:
    """
    Represents an active subscription to events.

    Attributes:
        id: Unique subscription identifier
        handler: The event handler function
        event_types: Event types this handler subscribes to (None = all)
        priority: Handler execution priority
        delivery_guarantee: Delivery semantics
        max_retries: Maximum retry attempts on failure
        timeout_seconds: Handler timeout in seconds
    """

    id: str
    handler: EventHandler
    event_types: set[str] | None = None
    priority: HandlerPriority = HandlerPriority.NORMAL
    delivery_guarantee: DeliveryGuarantee = DeliveryGuarantee.AT_LEAST_ONCE
    max_retries: int = 3
    timeout_seconds: float = 30.0

    def matches_event_type(self, event_type: str) -> bool:
        """
        Check if this subscription handles a specific event type.

        Args:
            event_type: The event type to check

        Returns:
            True if this subscription handles the event type
        """
        if self.event_types is None:
            return True
        if "*" in self.event_types:
            return True
        return event_type in self.event_types

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Subscription):
            return NotImplemented
        return self.id == other.id
