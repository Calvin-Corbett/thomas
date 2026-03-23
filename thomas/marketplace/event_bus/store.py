"""
Event store implementation with event sourcing support.

Provides append-only storage, stream-based retrieval, optimistic concurrency,
snapshots, and global event ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._exceptions import ConcurrencyError, EventStoreError
from ._types import Event, EventEnvelope


@dataclass
class StreamSnapshot:
    """
    Snapshot of aggregate state at a specific version.

    Attributes:
        stream_name: The stream this snapshot belongs to
        version: Stream version at snapshot time
        state: Serialized aggregate state
        timestamp: When snapshot was taken
        metadata: Additional snapshot metadata
    """

    stream_name: str
    version: int
    state: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamMetadata:
    """
    Metadata about an event stream.

    Attributes:
        stream_name: Unique stream identifier
        version: Current version (last event index)
        event_count: Total events in stream
        created_at: When stream was created
        last_event_at: When last event was appended
        custom_metadata: Application-specific metadata
    """

    stream_name: str
    version: int = 0
    event_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_event_at: datetime | None = None
    custom_metadata: dict[str, Any] = field(default_factory=dict)


class EventStore:
    """
    Append-only event store with stream support and optimistic concurrency.

    Events are stored in streams (aggregates) with version tracking.
    Supports snapshots for faster aggregate reconstruction and global
    event ordering for projections.
    """

    def __init__(self) -> None:
        self._streams: dict[str, list[EventEnvelope]] = {}
        self._stream_metadata: dict[str, StreamMetadata] = {}
        self._snapshots: dict[str, StreamSnapshot] = {}
        self._sequence_counter: int = 0
        self._event_index: dict[str, list[EventEnvelope]] = {}

    def append(
        self,
        stream_name: str,
        events: list[Event],
        expected_version: int | None = None,
    ) -> tuple[int, int]:
        """
        Append events to a stream with optimistic concurrency.

        Args:
            stream_name: Name of the stream
            events: Events to append
            expected_version: Expected current version (None = first append)

        Returns:
            Tuple of (new_stream_version, last_global_sequence)

        Raises:
            ConcurrencyError: If expected_version doesn't match actual
            EventStoreError: If append fails
        """
        if not events:
            raise EventStoreError("Cannot append empty event list")

        current_version = self._get_current_version(stream_name)

        if expected_version is not None and expected_version != current_version:
            raise ConcurrencyError(stream_name, expected_version, current_version)

        if stream_name not in self._streams:
            self._streams[stream_name] = []
            self._stream_metadata[stream_name] = StreamMetadata(stream_name=stream_name)
            self._event_index[stream_name] = []

        envelopes: list[EventEnvelope] = []
        for event in events:
            self._sequence_counter += 1
            version = current_version + len(envelopes) + 1

            envelope = EventEnvelope(
                event=event,
                sequence_number=self._sequence_counter,
                stream_name=stream_name,
                stream_version=version,
            )
            envelopes.append(envelope)
            self._streams[stream_name].append(envelope)
            self._event_index[stream_name].append(envelope)

        metadata = self._stream_metadata[stream_name]
        metadata.version = current_version + len(envelopes)
        metadata.event_count += len(envelopes)
        metadata.last_event_at = datetime.utcnow()

        return metadata.version, self._sequence_counter

    def read_stream_forward(
        self, stream_name: str, from_version: int = 1, count: int | None = None
    ) -> list[EventEnvelope]:
        """
        Read events from a stream in forward order.

        Args:
            stream_name: Name of the stream
            from_version: Starting version (inclusive)
            count: Maximum number of events to return

        Returns:
            List of event envelopes in order

        Raises:
            EventStoreError: If stream doesn't exist
        """
        if stream_name not in self._streams:
            raise EventStoreError(f"Stream not found: {stream_name}")

        events = self._streams[stream_name]
        filtered = [e for e in events if e.stream_version >= from_version]

        if count is not None:
            filtered = filtered[:count]

        return filtered

    def read_stream_backward(
        self, stream_name: str, from_version: int | None = None, count: int | None = None
    ) -> list[EventEnvelope]:
        """
        Read events from a stream in backward order.

        Args:
            stream_name: Name of the stream
            from_version: Starting version (inclusive, defaults to latest)
            count: Maximum number of events to return

        Returns:
            List of event envelopes in reverse order
        """
        if stream_name not in self._streams:
            return []

        events = self._streams[stream_name]
        if not events:
            return []

        if from_version is None:
            from_version = events[-1].stream_version

        filtered = [e for e in events if e.stream_version <= from_version]
        result = list(reversed(filtered))

        if count is not None:
            result = result[:count]

        return result

    def read_by_type(self, event_type: str, from_sequence: int = 0, count: int | None = None) -> list[EventEnvelope]:
        """
        Read all events of a specific type (globally ordered).

        Args:
            event_type: Type of events to read
            from_sequence: Starting global sequence number
            count: Maximum number of events

        Returns:
            List of matching event envelopes
        """
        events: list[EventEnvelope] = []

        for stream_events in self._streams.values():
            for envelope in stream_events:
                if envelope.event.type == event_type and envelope.sequence_number >= from_sequence:
                    events.append(envelope)

        events.sort(key=lambda e: e.sequence_number)

        if count is not None:
            events = events[:count]

        return events

    def get_metadata(self, stream_name: str) -> StreamMetadata | None:
        """
        Get metadata about a stream.

        Args:
            stream_name: The stream name

        Returns:
            Stream metadata or None if stream doesn't exist
        """
        return self._stream_metadata.get(stream_name)

    def update_metadata(self, stream_name: str, custom_metadata: dict[str, Any]) -> None:
        """
        Update custom metadata for a stream.

        Args:
            stream_name: The stream name
            custom_metadata: Metadata to set
        """
        if stream_name in self._stream_metadata:
            self._stream_metadata[stream_name].custom_metadata.update(custom_metadata)

    def save_snapshot(self, snapshot: StreamSnapshot) -> None:
        """
        Save a snapshot of aggregate state.

        Args:
            snapshot: The snapshot to save
        """
        self._snapshots[snapshot.stream_name] = snapshot

    def get_snapshot(self, stream_name: str) -> StreamSnapshot | None:
        """
        Get the latest snapshot for a stream.

        Args:
            stream_name: The stream name

        Returns:
            The snapshot or None if not found
        """
        return self._snapshots.get(stream_name)

    def delete_snapshot(self, stream_name: str) -> None:
        """Delete snapshot for a stream."""
        self._snapshots.pop(stream_name, None)

    def stream_exists(self, stream_name: str) -> bool:
        """Check if a stream exists."""
        return stream_name in self._streams

    def get_all_streams(self) -> list[str]:
        """Get all stream names."""
        return list(self._streams.keys())

    def get_stream_version(self, stream_name: str) -> int:
        """Get the current version of a stream."""
        return self._get_current_version(stream_name)

    def get_global_position(self) -> int:
        """Get the current global event sequence number."""
        return self._sequence_counter

    def read_all_forward(self, from_sequence: int = 0, count: int | None = None) -> list[EventEnvelope]:
        """
        Read all events in global order.

        Args:
            from_sequence: Starting sequence number
            count: Maximum events to return

        Returns:
            List of events in sequence order
        """
        all_events: list[EventEnvelope] = []

        for events in self._streams.values():
            all_events.extend(events)

        all_events.sort(key=lambda e: e.sequence_number)
        filtered = [e for e in all_events if e.sequence_number >= from_sequence]

        if count is not None:
            filtered = filtered[:count]

        return filtered

    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._streams.clear()
        self._stream_metadata.clear()
        self._snapshots.clear()
        self._sequence_counter = 0
        self._event_index.clear()

    def _get_current_version(self, stream_name: str) -> int:
        """Get current version of a stream (0 if doesn't exist)."""
        if stream_name not in self._stream_metadata:
            return 0
        return self._stream_metadata[stream_name].version
