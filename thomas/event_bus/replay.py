"""
Event replay engine for rebuilding state or testing scenarios.

Supports filtering by type, time, and stream with progress tracking,
pause/resume capability, and dry run mode.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ._exceptions import ReplayError
from ._types import Event, EventFilter, EventHandler
from .store import EventStore


class ReplayMode(Enum):
    """Replay execution mode."""

    NORMAL = "normal"  # Execute handlers normally
    DRY_RUN = "dry_run"  # Skip handler execution, report what would happen


class ReplayStatus(Enum):
    """Replay execution status."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReplayProgress:
    """
    Tracks progress of a replay operation.

    Attributes:
        status: Current replay status
        events_processed: Number of events processed
        events_failed: Number of events that failed
        start_time: When replay started
        end_time: When replay completed
        current_position: Position in stream (for pause/resume)
        error_message: Last error message if failed
    """

    status: ReplayStatus = ReplayStatus.NOT_STARTED
    events_processed: int = 0
    events_failed: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    current_position: int = 0
    error_message: str | None = None

    def is_complete(self) -> bool:
        """Check if replay has completed."""
        return self.status in (ReplayStatus.COMPLETED, ReplayStatus.FAILED)

    def percent_complete(self, total_events: int) -> float:
        """Get percentage complete."""
        if total_events == 0:
            return 100.0
        return (self.events_processed / total_events) * 100.0


class EventReplayer:
    """
    Replays events from an event store with flexible filtering and control.

    Supports:
    - Filtering by event type, time range, or stream
    - Speed control with delays between events
    - Pause/resume capability
    - Dry run mode for testing
    - Multiple replay strategies
    """

    def __init__(self, store: EventStore) -> None:
        self.store = store
        self._progress = ReplayProgress()
        self._speed_factor = 1.0

    async def replay_stream(
        self,
        stream_name: str,
        handler: EventHandler,
        from_version: int = 1,
        to_version: int | None = None,
        mode: ReplayMode = ReplayMode.NORMAL,
        speed_factor: float = 1.0,
    ) -> ReplayProgress:
        """
        Replay a specific stream to a handler.

        Args:
            stream_name: The stream to replay
            handler: Handler to process events
            from_version: Starting version (inclusive)
            to_version: Ending version (inclusive), None = to end
            mode: Normal or dry run mode
            speed_factor: Replay speed multiplier (1.0 = real time)

        Returns:
            Progress report of the replay
        """
        self._progress = ReplayProgress(
            status=ReplayStatus.RUNNING,
            start_time=datetime.utcnow(),
        )
        self._speed_factor = speed_factor

        try:
            events = self.store.read_stream_forward(stream_name, from_version)

            if to_version:
                events = [e for e in events if e.stream_version <= to_version]

            for envelope in events:
                if self._progress.status == ReplayStatus.PAUSED:
                    await self._wait_for_resume()

                await self._process_event(envelope.event, handler, mode)
                self._progress.current_position = envelope.stream_version

            self._progress.status = ReplayStatus.COMPLETED
            self._progress.end_time = datetime.utcnow()

        except Exception as e:
            self._progress.status = ReplayStatus.FAILED
            self._progress.error_message = str(e)
            self._progress.end_time = datetime.utcnow()
            raise ReplayError(stream_name, self._progress.current_position, e)

        return self._progress

    async def replay_by_type(
        self,
        event_type: str,
        handler: EventHandler,
        from_sequence: int = 0,
        max_count: int | None = None,
        mode: ReplayMode = ReplayMode.NORMAL,
        speed_factor: float = 1.0,
    ) -> ReplayProgress:
        """
        Replay all events of a specific type.

        Args:
            event_type: Type of events to replay
            handler: Handler to process events
            from_sequence: Starting global sequence number
            max_count: Maximum events to process
            mode: Normal or dry run mode
            speed_factor: Replay speed multiplier

        Returns:
            Progress report
        """
        self._progress = ReplayProgress(
            status=ReplayStatus.RUNNING,
            start_time=datetime.utcnow(),
        )
        self._speed_factor = speed_factor

        try:
            events = self.store.read_by_type(event_type, from_sequence, max_count)

            for envelope in events:
                if self._progress.status == ReplayStatus.PAUSED:
                    await self._wait_for_resume()

                await self._process_event(envelope.event, handler, mode)
                self._progress.current_position = envelope.sequence_number

            self._progress.status = ReplayStatus.COMPLETED
            self._progress.end_time = datetime.utcnow()

        except Exception as e:
            self._progress.status = ReplayStatus.FAILED
            self._progress.error_message = str(e)
            self._progress.end_time = datetime.utcnow()

        return self._progress

    async def replay_filtered(
        self,
        event_filter: EventFilter,
        handler: EventHandler,
        mode: ReplayMode = ReplayMode.NORMAL,
        speed_factor: float = 1.0,
    ) -> ReplayProgress:
        """
        Replay events matching a filter.

        Args:
            event_filter: Filter criteria
            handler: Handler to process events
            mode: Normal or dry run mode
            speed_factor: Replay speed multiplier

        Returns:
            Progress report
        """
        self._progress = ReplayProgress(
            status=ReplayStatus.RUNNING,
            start_time=datetime.utcnow(),
        )
        self._speed_factor = speed_factor

        try:
            all_events = self.store.read_all_forward()
            matching = [e for e in all_events if event_filter.matches(e.event)]

            for envelope in matching:
                if self._progress.status == ReplayStatus.PAUSED:
                    await self._wait_for_resume()

                await self._process_event(envelope.event, handler, mode)
                self._progress.current_position = envelope.sequence_number

            self._progress.status = ReplayStatus.COMPLETED
            self._progress.end_time = datetime.utcnow()

        except Exception as e:
            self._progress.status = ReplayStatus.FAILED
            self._progress.error_message = str(e)
            self._progress.end_time = datetime.utcnow()

        return self._progress

    def pause(self) -> None:
        """Pause replay execution."""
        if self._progress.status == ReplayStatus.RUNNING:
            self._progress.status = ReplayStatus.PAUSED

    def resume(self) -> None:
        """Resume paused replay."""
        if self._progress.status == ReplayStatus.PAUSED:
            self._progress.status = ReplayStatus.RUNNING

    def get_progress(self) -> ReplayProgress:
        """Get current progress."""
        return self._progress

    async def _process_event(self, event: Event, handler: EventHandler, mode: ReplayMode) -> None:
        """
        Process a single event.

        Args:
            event: Event to process
            handler: Handler to call
            mode: Replay mode
        """
        try:
            if mode == ReplayMode.NORMAL:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    await asyncio.to_thread(handler, event)

            self._progress.events_processed += 1

            if self._speed_factor < 1.0:
                await asyncio.sleep((1.0 - self._speed_factor) * 0.01)

        except Exception as e:
            self._progress.events_failed += 1
            self._progress.error_message = str(e)

    async def _wait_for_resume(self) -> None:
        """Wait until replay is resumed."""
        while self._progress.status == ReplayStatus.PAUSED:
            await asyncio.sleep(0.1)


class ReplayFilter:
    """
    Builder for creating replay filters with fluent API.

    Example:
        filter = (ReplayFilter()
                  .with_types(['UserCreated', 'UserDeleted'])
                  .with_sources(['user-service'])
                  .with_time_range(start, end)
                  .build())
    """

    def __init__(self) -> None:
        self._event_types: set[str] = set()
        self._sources: set[str] = set()
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None

    def with_types(self, event_types: list[str]) -> ReplayFilter:
        """Add event types to filter."""
        self._event_types.update(event_types)
        return self

    def with_type(self, event_type: str) -> ReplayFilter:
        """Add single event type."""
        self._event_types.add(event_type)
        return self

    def with_sources(self, sources: list[str]) -> ReplayFilter:
        """Add sources to filter."""
        self._sources.update(sources)
        return self

    def with_source(self, source: str) -> ReplayFilter:
        """Add single source."""
        self._sources.add(source)
        return self

    def with_time_range(self, start: datetime, end: datetime | None = None) -> ReplayFilter:
        """Set time range for filtering."""
        self._start_time = start
        self._end_time = end
        return self

    def build(self) -> EventFilter:
        """Build the filter."""
        return EventFilter(
            event_types=self._event_types or None,
            sources=self._sources or None,
            start_time=self._start_time,
            end_time=self._end_time,
        )
