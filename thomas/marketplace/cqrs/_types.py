"""
Core type definitions for CQRS pattern.

Provides foundational types for commands, queries, events, and associated metadata.
Implements aggregate identifiers, event envelopes, and result types.
"""

from __future__ import annotations

import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

# Type variables for generic constraints
T = TypeVar("T")
TCommand = TypeVar("TCommand", bound="Command")
TQuery = TypeVar("TQuery", bound="Query")
TEvent = TypeVar("TEvent", bound="Event")


class Command(ABC):
    """
    Base class for all commands.

    Commands represent intent to change state. Each command should be a concrete
    subclass implementing a specific business operation.
    """

    def __init__(self) -> None:
        """Initialize command with timestamp."""
        self.timestamp: datetime = datetime.utcnow()
        self.command_id: str = str(uuid.uuid4())


class Query(ABC):
    """
    Base class for all queries.

    Queries represent requests to read state without changing it.
    """

    def __init__(self) -> None:
        """Initialize query with timestamp."""
        self.timestamp: datetime = datetime.utcnow()
        self.query_id: str = str(uuid.uuid4())


class Event(ABC):
    """
    Base class for all domain events.

    Events represent facts about state changes that have occurred in the system.
    """

    def __init__(self) -> None:
        """Initialize event with timestamp."""
        self.timestamp: datetime = datetime.utcnow()
        self.event_id: str = str(uuid.uuid4())


class AggregateId:
    """
    Type-safe wrapper for aggregate identifiers.

    Ensures aggregate identity is properly typed and distinguishable
    from other identifiers in the system.
    """

    def __init__(self, value: str, aggregate_type: str) -> None:
        """
        Initialize aggregate identifier.

        Args:
            value: The identifier value (usually UUID string)
            aggregate_type: The type of aggregate (e.g., "Account", "Order")
        """
        self.value: str = value
        self.aggregate_type: str = aggregate_type

    def __eq__(self, other: object) -> bool:
        """Check equality with another AggregateId."""
        if not isinstance(other, AggregateId):
            return False
        return self.value == other.value and self.aggregate_type == other.aggregate_type

    def __hash__(self) -> int:
        """Generate hash for use in collections."""
        return hash((self.value, self.aggregate_type))

    def __str__(self) -> str:
        """String representation."""
        return f"{self.aggregate_type}({self.value})"

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"AggregateId(value={self.value!r}, aggregate_type={self.aggregate_type!r})"


@dataclass
class Metadata:
    """
    Metadata associated with commands, queries, or events.

    Stores contextual information like user identity, correlation IDs,
    causation chains, and custom application data.
    """

    user_id: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    causation_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str | None = None
    custom_data: dict[str, Any] = field(default_factory=dict)

    def with_causation(self, causation_id: str) -> Metadata:
        """Create new metadata with updated causation ID."""
        return Metadata(
            user_id=self.user_id,
            correlation_id=self.correlation_id,
            causation_id=causation_id,
            timestamp=self.timestamp,
            source=self.source,
            custom_data=self.custom_data.copy(),
        )

    def with_user(self, user_id: str) -> Metadata:
        """Create new metadata with updated user ID."""
        return Metadata(
            user_id=user_id,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            timestamp=self.timestamp,
            source=self.source,
            custom_data=self.custom_data.copy(),
        )


@dataclass
class EventEnvelope:
    """
    Wrapper for an event with its metadata and position information.

    Encapsulates an event with all contextual information needed for
    processing and persistence.
    """

    event: Event
    aggregate_id: AggregateId
    aggregate_version: int
    global_position: int
    metadata: Metadata
    event_type: str = field(default="")

    def __post_init__(self) -> None:
        """Set event_type if not provided."""
        if not self.event_type:
            self.event_type = self.event.__class__.__name__


@dataclass
class CommandResult(Generic[T]):
    """
    Result of command execution.

    Encapsulates whether command succeeded, any resulting events,
    and optional aggregate state or error information.
    """

    success: bool
    events: list[Event] = field(default_factory=list)
    aggregate_id: AggregateId | None = None
    error: str | None = None
    error_code: str | None = None
    data: T | None = None

    @classmethod
    def ok(
        cls, events: list[Event] | None = None, aggregate_id: AggregateId | None = None, data: T | None = None
    ) -> CommandResult[T]:
        """
        Create a successful command result.

        Args:
            events: Events produced by command
            aggregate_id: ID of affected aggregate
            data: Additional data to return

        Returns:
            CommandResult instance
        """
        return cls(
            success=True,
            events=events or [],
            aggregate_id=aggregate_id,
            data=data,
        )

    @classmethod
    def fail(cls, error: str, error_code: str | None = None) -> CommandResult[T]:
        """
        Create a failed command result.

        Args:
            error: Error message
            error_code: Optional error code for categorization

        Returns:
            CommandResult instance
        """
        return cls(
            success=False,
            error=error,
            error_code=error_code,
        )


@dataclass
class QueryResult(Generic[T]):
    """
    Result of query execution.

    Encapsulates query result data with pagination and metadata.
    """

    data: T
    total_count: int | None = None
    offset: int = 0
    limit: int | None = None
    cached: bool = False

    def __post_init__(self) -> None:
        """Validate result state."""
        if self.limit is not None and self.limit < 0:
            raise ValueError("limit must be non-negative")
        if self.offset < 0:
            raise ValueError("offset must be non-negative")


class EventPriority(Enum):
    """Priority levels for event processing."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class SnapshotData:
    """
    Snapshot of aggregate state at a specific version.

    Used to optimize aggregate reconstruction from event store.
    """

    aggregate_id: AggregateId
    aggregate_version: int
    state: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_count: int = 0
