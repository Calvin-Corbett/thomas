"""
Aggregate root and aggregate repository.

Implements the base aggregate root class with event sourcing support,
uncommitted event tracking, version management, and rehydration.
"""

from __future__ import annotations

from abc import ABC
from typing import Any

from ._exceptions import AggregateNotFoundException
from ._types import AggregateId, Event, EventEnvelope, Metadata
from .events import EventStore


class AggregateRoot(ABC):
    """
    Base class for domain aggregates.

    Aggregates are the primary unit of consistency and encapsulate
    related entities and value objects. They apply events to change state
    and produce new events as results of commands.
    """

    def __init__(self, aggregate_id: AggregateId) -> None:
        """
        Initialize aggregate root.

        Args:
            aggregate_id: Unique identifier for this aggregate
        """
        self.aggregate_id = aggregate_id
        self.version = 0
        self._uncommitted_events: list[Event] = []

    def apply_event(self, event: Event) -> None:
        """
        Apply an event to aggregate state.

        Should be implemented by subclasses to update state
        based on event type.

        Args:
            event: Event to apply
        """
        method_name = f"on_{event.__class__.__name__}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            method(event)

    def raise_event(self, event: Event) -> None:
        """
        Record an event as having occurred.

        Event will be stored in uncommitted events and applied
        to aggregate state.

        Args:
            event: Event to raise
        """
        self.apply_event(event)
        self._uncommitted_events.append(event)
        self.version += 1

    def get_uncommitted_events(self) -> list[Event]:
        """
        Get events that have not been persisted.

        Returns:
            List of uncommitted events
        """
        return self._uncommitted_events.copy()

    def clear_uncommitted_events(self) -> None:
        """Clear uncommitted events after persistence."""
        self._uncommitted_events.clear()

    def get_version(self) -> int:
        """
        Get current aggregate version.

        Returns:
            Version number
        """
        return self.version

    def has_uncommitted_events(self) -> bool:
        """
        Check if there are uncommitted events.

        Returns:
            True if uncommitted events exist
        """
        return len(self._uncommitted_events) > 0

    def load_from_history(self, events: list[EventEnvelope]) -> None:
        """
        Rehydrate aggregate from event history.

        Applies all historical events to restore state.

        Args:
            events: Events to apply
        """
        for envelope in events:
            self.apply_event(envelope.event)
            self.version = envelope.aggregate_version
        self._uncommitted_events.clear()

    def to_snapshot_state(self) -> dict[str, Any]:
        """
        Serialize aggregate state for snapshots.

        Should be implemented by subclasses to capture
        all necessary state.

        Returns:
            Dictionary representing state
        """
        return {"version": self.version}

    def restore_from_snapshot(self, state: dict[str, Any]) -> None:
        """
        Restore aggregate from snapshot.

        Should be implemented by subclasses to restore
        state from snapshot data.

        Args:
            state: Snapshot state dictionary
        """
        self.version = state.get("version", 0)


class AggregateRepository:
    """
    Repository for aggregate persistence.

    Manages loading aggregates from event store and saving
    uncommitted events back to store.
    """

    def __init__(self, event_store: EventStore) -> None:
        """
        Initialize repository.

        Args:
            event_store: Event store for persistence
        """
        self.event_store = event_store

    async def save(
        self,
        aggregate: AggregateRoot,
        metadata: Metadata,
    ) -> None:
        """
        Save aggregate to event store.

        Persists all uncommitted events and clears the list.

        Args:
            aggregate: Aggregate to save
            metadata: Metadata for events

        Raises:
            ConcurrencyException: If version conflict
        """
        uncommitted = aggregate.get_uncommitted_events()
        if not uncommitted:
            return

        await self.event_store.append(
            aggregate_id=aggregate.aggregate_id,
            events=uncommitted,
            expected_version=aggregate.version - len(uncommitted),
            metadata=metadata,
        )

        aggregate.clear_uncommitted_events()

    async def get_by_id(
        self,
        aggregate_id: AggregateId,
        aggregate_type: type[AggregateRoot],
    ) -> AggregateRoot:
        """
        Load aggregate from event store.

        Reconstructs aggregate state from event history and
        optionally from latest snapshot.

        Args:
            aggregate_id: ID of aggregate to load
            aggregate_type: Type of aggregate

        Returns:
            Rehydrated aggregate instance

        Raises:
            AggregateNotFoundException: If not found
        """
        # Try to load from snapshot first
        snapshot = await self.event_store.get_snapshot(aggregate_id)

        aggregate = aggregate_type(aggregate_id)

        if snapshot:
            aggregate.restore_from_snapshot(snapshot.state)
            from_version = snapshot.aggregate_version
        else:
            from_version = 0

        # Load events after snapshot
        events = await self.event_store.get_events(
            aggregate_id,
            from_version=from_version,
        )

        if not events and from_version == 0:
            raise AggregateNotFoundException(
                aggregate_id.value,
                aggregate_id.aggregate_type,
            )

        if events:
            aggregate.load_from_history(events)

        return aggregate

    async def exists(self, aggregate_id: AggregateId) -> bool:
        """
        Check if aggregate exists.

        Args:
            aggregate_id: ID to check

        Returns:
            True if aggregate exists
        """
        try:
            version = await self.event_store.get_current_version(aggregate_id)
            return version > 0
        except Exception:  # REVIEWED: async context
            return False

    async def save_snapshot(
        self,
        aggregate: AggregateRoot,
        frequency: int = 10,
    ) -> None:
        """
        Save aggregate snapshot if event count exceeds frequency.

        Args:
            aggregate: Aggregate to snapshot
            frequency: Save snapshot every N events
        """
        events = await self.event_store.get_events(aggregate.aggregate_id)
        if len(events) >= frequency:
            await self.event_store.save_snapshot(
                aggregate_id=aggregate.aggregate_id,
                version=aggregate.version,
                state=aggregate.to_snapshot_state(),
            )
