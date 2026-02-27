"""
Event store implementation with optimistic concurrency control.

Provides event persistence, retrieval, snapshots, and global position tracking
for event sourcing patterns.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._exceptions import (
    ConcurrencyException,
)
from ._types import AggregateId, Event, EventEnvelope, Metadata, SnapshotData


@dataclass
class StoredEvent:
    """Event stored in the event store."""

    event: Event
    aggregate_id: AggregateId
    aggregate_version: int
    global_position: int
    metadata: Metadata
    event_type: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


class EventStore:
    """
    Persistent store for domain events.

    Manages event storage with optimistic concurrency control,
    snapshot support, and global position tracking.
    """

    def __init__(self) -> None:
        """Initialize event store."""
        self._events: dict[str, list[StoredEvent]] = {}
        self._global_position: int = 0
        self._snapshots: dict[str, SnapshotData] = {}
        self._lock = asyncio.Lock()
        self._subscriber_lock = asyncio.Lock()
        self._subscribers: list[callable] = []

    async def append(
        self,
        aggregate_id: AggregateId,
        events: list[Event],
        expected_version: int,
        metadata: Metadata,
    ) -> None:
        """
        Append events to store with optimistic concurrency.

        Args:
            aggregate_id: ID of aggregate
            events: Events to append
            expected_version: Expected current aggregate version
            metadata: Event metadata

        Raises:
            ConcurrencyException: If version mismatch
            EventStoreException: If store operation fails
        """
        async with self._lock:
            agg_key = self._aggregate_key(aggregate_id)

            # Check optimistic concurrency
            current_version = self._get_current_version(agg_key)
            if current_version != expected_version:
                raise ConcurrencyException(
                    agg_key,
                    expected_version,
                    current_version,
                )

            # Append events
            if agg_key not in self._events:
                self._events[agg_key] = []

            stored_events = []
            for i, event in enumerate(events):
                version = expected_version + i + 1
                envelope = EventEnvelope(
                    event=event,
                    aggregate_id=aggregate_id,
                    aggregate_version=version,
                    global_position=self._global_position + i,
                    metadata=metadata,
                    event_type=event.__class__.__name__,
                )

                stored = StoredEvent(
                    event=envelope.event,
                    aggregate_id=envelope.aggregate_id,
                    aggregate_version=envelope.aggregate_version,
                    global_position=envelope.global_position,
                    metadata=envelope.metadata,
                    event_type=envelope.event_type,
                )

                self._events[agg_key].append(stored)
                stored_events.append(stored)

            self._global_position += len(events)

            # Notify subscribers
            await self._notify_subscribers(stored_events)

    async def get_events(
        self,
        aggregate_id: AggregateId,
        from_version: int = 0,
    ) -> list[EventEnvelope]:
        """
        Retrieve events for aggregate.

        Args:
            aggregate_id: Aggregate to retrieve
            from_version: Start from version (inclusive)

        Returns:
            List of event envelopes
        """
        async with self._lock:
            agg_key = self._aggregate_key(aggregate_id)
            stored = self._events.get(agg_key, [])

            return [
                EventEnvelope(
                    event=s.event,
                    aggregate_id=s.aggregate_id,
                    aggregate_version=s.aggregate_version,
                    global_position=s.global_position,
                    metadata=s.metadata,
                    event_type=s.event_type,
                )
                for s in stored
                if s.aggregate_version > from_version
            ]

    async def get_events_by_type(
        self,
        event_type: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        """
        Retrieve events by type from global position.

        Args:
            event_type: Type of event to retrieve
            from_position: Start from global position

        Returns:
            List of matching event envelopes
        """
        async with self._lock:
            results = []
            for events_list in self._events.values():
                for stored in events_list:
                    if stored.event_type == event_type and stored.global_position >= from_position:
                        results.append(
                            EventEnvelope(
                                event=stored.event,
                                aggregate_id=stored.aggregate_id,
                                aggregate_version=stored.aggregate_version,
                                global_position=stored.global_position,
                                metadata=stored.metadata,
                                event_type=stored.event_type,
                            )
                        )

            # Sort by global position
            return sorted(results, key=lambda e: e.global_position)

    async def get_events_from_position(
        self,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """
        Retrieve events from global position.

        Args:
            from_position: Start from position (inclusive)
            limit: Maximum events to retrieve

        Returns:
            List of event envelopes
        """
        async with self._lock:
            results = []
            for events_list in self._events.values():
                for stored in events_list:
                    if stored.global_position >= from_position:
                        results.append(
                            EventEnvelope(
                                event=stored.event,
                                aggregate_id=stored.aggregate_id,
                                aggregate_version=stored.aggregate_version,
                                global_position=stored.global_position,
                                metadata=stored.metadata,
                                event_type=stored.event_type,
                            )
                        )

            # Sort and limit
            sorted_results = sorted(results, key=lambda e: e.global_position)
            if limit:
                return sorted_results[:limit]
            return sorted_results

    async def get_current_version(self, aggregate_id: AggregateId) -> int:
        """
        Get current version of aggregate.

        Args:
            aggregate_id: Aggregate to check

        Returns:
            Current version (0 if not found)
        """
        async with self._lock:
            return self._get_current_version(self._aggregate_key(aggregate_id))

    def _get_current_version(self, agg_key: str) -> int:
        """Get current version without locking."""
        events = self._events.get(agg_key, [])
        if not events:
            return 0
        return events[-1].aggregate_version

    async def save_snapshot(
        self,
        aggregate_id: AggregateId,
        version: int,
        state: dict[str, Any],
    ) -> None:
        """
        Save aggregate snapshot.

        Args:
            aggregate_id: Aggregate to snapshot
            version: Version of snapshot
            state: Serialized state

        Raises:
            SnapshotException: If snapshot save fails
        """
        async with self._lock:
            key = self._snapshot_key(aggregate_id, version)
            self._snapshots[key] = SnapshotData(
                aggregate_id=aggregate_id,
                aggregate_version=version,
                state=state,
                event_count=len(self._events.get(self._aggregate_key(aggregate_id), [])),
            )

    async def get_snapshot(
        self,
        aggregate_id: AggregateId,
    ) -> SnapshotData | None:
        """
        Get latest snapshot for aggregate.

        Args:
            aggregate_id: Aggregate to retrieve

        Returns:
            SnapshotData or None
        """
        async with self._lock:
            agg_key = self._aggregate_key(aggregate_id)
            # Find latest snapshot
            candidates = [snap for key, snap in self._snapshots.items() if snap.aggregate_id == aggregate_id]
            if candidates:
                return max(candidates, key=lambda s: s.aggregate_version)
            return None

    async def get_global_position(self) -> int:
        """
        Get current global position.

        Returns:
            Global position
        """
        async with self._lock:
            return self._global_position

    async def subscribe(self, callback: callable) -> None:
        """
        Subscribe to new events.

        Args:
            callback: Function to call with new events
        """
        async with self._subscriber_lock:
            self._subscribers.append(callback)

    async def _notify_subscribers(self, events: list[StoredEvent]) -> None:
        """Notify subscribers of new events."""
        async with self._subscriber_lock:
            for callback in self._subscribers:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(events)
                    else:
                        callback(events)
                except Exception:  # REVIEWED: async context
                    pass

    def _aggregate_key(self, aggregate_id: AggregateId) -> str:
        """Generate key for aggregate."""
        return f"{aggregate_id.aggregate_type}#{aggregate_id.value}"

    def _snapshot_key(self, aggregate_id: AggregateId, version: int) -> str:
        """Generate key for snapshot."""
        return f"{self._aggregate_key(aggregate_id)}@{version}"

    async def clear(self) -> None:
        """Clear all events (for testing)."""
        async with self._lock:
            self._events.clear()
            self._snapshots.clear()
            self._global_position = 0

    async def event_count(self) -> int:
        """
        Get total number of events in store.

        Returns:
            Event count
        """
        async with self._lock:
            return sum(len(events) for events in self._events.values())
