"""
Event-sourced aggregate root base class.

Aggregates apply events to build state, track uncommitted events,
and support loading from the event store with snapshots.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._types import Event
from .store import EventStore, StreamSnapshot


class AggregateRoot:
    """
    Base class for event-sourced aggregates.

    Aggregates apply events to their state and track uncommitted events
    for persistence. They can be loaded from the store via replay and
    support snapshots for performance optimization.

    Attributes:
        id: Unique identifier for this aggregate
        version: Current version (number of applied events)
        uncommitted_events: Events not yet persisted
        _state: Application-specific state dictionary
    """

    def __init__(self, aggregate_id: str) -> None:
        self.id = aggregate_id
        self.version = 0
        self.uncommitted_events: list[Event] = []
        self._state: dict[str, Any] = {}

    def apply_event(self, event: Event) -> None:
        """
        Apply an event to the aggregate state.

        This method dispatches to a specific handler based on event type.
        Subclasses should override specific handlers like _on_user_created().

        Args:
            event: Event to apply
        """
        method_name = self._get_handler_name(event.type)

        if hasattr(self, method_name):
            handler = getattr(self, method_name)
            handler(event)
            self.version += 1

    def record_event(self, event: Event) -> None:
        """
        Record an uncommitted event.

        Events should be recorded after being applied to state.
        The event will be persisted by the repository.

        Args:
            event: Event to record
        """
        self.apply_event(event)
        self.uncommitted_events.append(event)

    def get_uncommitted_events(self) -> list[Event]:
        """Get all uncommitted events."""
        return self.uncommitted_events[:]

    def clear_uncommitted_events(self) -> None:
        """Clear uncommitted events after persistence."""
        self.uncommitted_events.clear()

    def get_state(self) -> dict[str, Any]:
        """Get current aggregate state."""
        return self._state.copy()

    def get_state_value(self, key: str, default: Any = None) -> Any:
        """Get a specific state value."""
        return self._state.get(key, default)

    def set_state_value(self, key: str, value: Any) -> None:
        """Set a state value."""
        self._state[key] = value

    @staticmethod
    def _get_handler_name(event_type: str) -> str:
        """
        Generate handler method name from event type.

        Converts PascalCase event type to snake_case method.
        Example: 'UserCreated' -> '_on_user_created'
        """
        name = "".join(["_" + c.lower() if c.isupper() else c for c in event_type]).lstrip("_")
        return f"_on_{name}"


class AggregateRepository:
    """
    Repository for persisting and loading aggregates.

    Handles loading aggregates from the event store with optional
    snapshot support for performance optimization.
    """

    def __init__(self, store: EventStore) -> None:
        self.store = store

    def save(
        self,
        aggregate: AggregateRoot,
        expected_version: int | None = None,
    ) -> None:
        """
        Save uncommitted events from an aggregate.

        Args:
            aggregate: Aggregate to save
            expected_version: Expected version for concurrency check

        Raises:
            ConcurrencyError: If version check fails
            EventStoreError: If save fails
        """
        events = aggregate.get_uncommitted_events()

        if not events:
            return

        stream_name = self._get_stream_name(aggregate)
        self.store.append(stream_name, events, expected_version)
        aggregate.clear_uncommitted_events()

    def load(self, aggregate_class: type, aggregate_id: str) -> AggregateRoot | None:
        """
        Load an aggregate from the event store.

        Uses snapshots when available for performance optimization.

        Args:
            aggregate_class: The aggregate class to instantiate
            aggregate_id: The aggregate ID

        Returns:
            Loaded aggregate or None if not found

        Raises:
            EventStoreError: If load fails
        """
        stream_name = f"{aggregate_class.__name__}-{aggregate_id}"

        if not self.store.stream_exists(stream_name):
            return None

        aggregate = aggregate_class(aggregate_id)

        snapshot = self.store.get_snapshot(stream_name)

        if snapshot:
            aggregate._state = snapshot.state.copy()
            aggregate.version = snapshot.version
            from_version = snapshot.version + 1
        else:
            from_version = 1

        events = self.store.read_stream_forward(stream_name, from_version)

        for envelope in events:
            aggregate.apply_event(envelope.event)

        return aggregate

    def load_at_version(self, aggregate_class: type, aggregate_id: str, version: int) -> AggregateRoot | None:
        """
        Load an aggregate at a specific version.

        Args:
            aggregate_class: The aggregate class
            aggregate_id: The aggregate ID
            version: Target version to load

        Returns:
            Aggregate at the specified version or None
        """
        stream_name = f"{aggregate_class.__name__}-{aggregate_id}"

        if not self.store.stream_exists(stream_name):
            return None

        aggregate = aggregate_class(aggregate_id)

        events = self.store.read_stream_forward(stream_name, 1, version)

        for envelope in events:
            aggregate.apply_event(envelope.event)

        return aggregate

    def save_snapshot(
        self,
        aggregate: AggregateRoot,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Save a snapshot of the current aggregate state.

        Snapshots allow faster load times by avoiding full event replay.

        Args:
            aggregate: The aggregate to snapshot
            metadata: Optional snapshot metadata
        """
        stream_name = self._get_stream_name(aggregate)

        snapshot = StreamSnapshot(
            stream_name=stream_name,
            version=aggregate.version,
            state=aggregate.get_state(),
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
        )

        self.store.save_snapshot(snapshot)

    def delete_snapshot(self, aggregate_class: type, aggregate_id: str) -> None:
        """Delete snapshot for an aggregate."""
        stream_name = f"{aggregate_class.__name__}-{aggregate_id}"
        self.store.delete_snapshot(stream_name)

    def get_aggregate_version(self, aggregate_class: type, aggregate_id: str) -> int:
        """Get the current version of an aggregate without loading it."""
        stream_name = f"{aggregate_class.__name__}-{aggregate_id}"
        return self.store.get_stream_version(stream_name)

    @staticmethod
    def _get_stream_name(aggregate: AggregateRoot) -> str:
        """Generate stream name from aggregate."""
        return f"{aggregate.__class__.__name__}-{aggregate.id}"


class AggregateCommand:
    """
    Base class for commands that modify aggregates.

    Commands are the primary way to interact with aggregates,
    following the CQRS pattern.
    """

    def __init__(self, aggregate_id: str) -> None:
        self.aggregate_id = aggregate_id
        self.timestamp = datetime.utcnow()

    def execute(self, aggregate: AggregateRoot) -> None:
        """
        Execute the command against an aggregate.

        Subclasses must implement this to apply their specific logic.

        Args:
            aggregate: The aggregate to command
        """
        raise NotImplementedError


class CommandHandler:
    """
    Generic handler for executing commands against aggregates.

    Loads aggregates, executes commands, and persists changes.
    """

    def __init__(
        self,
        repository: AggregateRepository,
        aggregate_class: type,
    ) -> None:
        self.repository = repository
        self.aggregate_class = aggregate_class

    def execute(self, command: AggregateCommand) -> AggregateRoot:
        """
        Execute a command and persist results.

        Args:
            command: The command to execute

        Returns:
            Updated aggregate

        Raises:
            EventStoreError: If execution fails
        """
        aggregate = self.repository.load(self.aggregate_class, command.aggregate_id) or self.aggregate_class(
            command.aggregate_id
        )

        command.execute(aggregate)

        self.repository.save(aggregate)

        return aggregate

    def execute_with_concurrency_check(self, command: AggregateCommand, expected_version: int) -> AggregateRoot:
        """
        Execute a command with optimistic concurrency check.

        Args:
            command: The command to execute
            expected_version: Expected current version

        Returns:
            Updated aggregate

        Raises:
            ConcurrencyError: If version check fails
        """
        aggregate = self.repository.load(self.aggregate_class, command.aggregate_id) or self.aggregate_class(
            command.aggregate_id
        )

        command.execute(aggregate)

        self.repository.save(aggregate, expected_version)

        return aggregate
