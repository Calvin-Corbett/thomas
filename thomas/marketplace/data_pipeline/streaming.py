"""
Stream processing framework for the pipeline.

Implements windowing, watermark tracking, late data handling, triggers,
stateful processing, and exactly-once semantics.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.data_pipeline._types import (
    Record,
    TriggerType,
    Watermark,
    WindowSpec,
)


@dataclass
class WindowedRecord:
    """Record with window assignment."""

    record: Record
    window_start: datetime
    window_end: datetime
    window_id: str
    is_late: bool = False


@dataclass
class TimerContext:
    """Context for processing timer callbacks."""

    timestamp: datetime
    state_key: str
    timer_type: str  # "event_time", "processing_time"


class Window:
    """Represents a time window."""

    def __init__(self, start: datetime, end: datetime) -> None:
        """
        Initialize window.

        Args:
            start: Window start time (inclusive)
            end: Window end time (exclusive)
        """
        self.start = start
        self.end = end

    def contains(self, timestamp: datetime) -> bool:
        """Check if timestamp falls in window."""
        return self.start <= timestamp < self.end

    def __repr__(self) -> str:
        return f"Window({self.start}, {self.end})"

    def __hash__(self) -> int:
        return hash((self.start, self.end))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Window):
            return False
        return self.start == other.start and self.end == other.end


class WindowAssigner:
    """Assigns records to windows."""

    def __init__(self, window_spec: WindowSpec) -> None:
        """
        Initialize window assigner.

        Args:
            window_spec: Window specification
        """
        self.window_spec = window_spec

    def assign_windows(self, record: Record, event_time: datetime) -> list[Window]:
        """
        Assign windows to a record.

        Args:
            record: Record to assign
            event_time: Event time of record

        Returns:
            List of windows record belongs to
        """
        if self.window_spec.is_tumbling:
            return self._assign_tumbling(event_time)
        elif self.window_spec.is_sliding:
            return self._assign_sliding(event_time)
        else:
            return self._assign_session(event_time)

    def _assign_tumbling(self, event_time: datetime) -> list[Window]:
        """Assign to tumbling window."""
        duration_seconds = self.window_spec.window_duration.total_seconds()
        epoch = datetime(1970, 1, 1)
        elapsed = (event_time - epoch).total_seconds()
        window_index = int(elapsed / duration_seconds)
        window_start = epoch + timedelta(seconds=window_index * duration_seconds)
        window_end = window_start + self.window_spec.window_duration
        return [Window(window_start, window_end)]

    def _assign_sliding(self, event_time: datetime) -> list[Window]:
        """Assign to sliding windows."""
        windows = []
        slide_seconds = self.window_spec.slide_duration.total_seconds()
        window_seconds = self.window_spec.window_duration.total_seconds()
        epoch = datetime(1970, 1, 1)
        elapsed = (event_time - epoch).total_seconds()

        window_index = int((elapsed - window_seconds) / slide_seconds)
        while True:
            window_start = epoch + timedelta(seconds=window_index * slide_seconds)
            window_end = window_start + self.window_spec.window_duration

            if window_start > event_time:
                break

            if window_end > event_time:
                windows.append(Window(window_start, window_end))

            window_index += 1

        return windows

    def _assign_session(self, event_time: datetime) -> list[Window]:
        """Assign to session window (placeholder)."""
        # Session windows are more complex and stateful
        # Simplified version: create a single session window
        session_timeout = self.window_spec.timeout or timedelta(minutes=10)
        return [Window(event_time, event_time + session_timeout)]


class WatermarkTracker:
    """Tracks watermark for event time progression."""

    def __init__(self, allowed_lateness: timedelta = None) -> None:
        """
        Initialize watermark tracker.

        Args:
            allowed_lateness: How long to accept late data
        """
        self.allowed_lateness = allowed_lateness or timedelta(seconds=0)
        self.watermark = Watermark(
            event_time=datetime(1970, 1, 1),
            allowed_lateness=self.allowed_lateness,
        )

    def update(self, event_time: datetime) -> None:
        """Update watermark with new event time."""
        if event_time > self.watermark.event_time:
            self.watermark.advance(event_time)

    def is_late(self, event_time: datetime) -> bool:
        """Check if record is late."""
        return self.watermark.is_late(event_time)

    def get_watermark(self) -> Watermark:
        """Get current watermark."""
        return self.watermark


class TriggerPolicy:
    """Determines when to emit window results."""

    def __init__(
        self,
        trigger_type: TriggerType,
        trigger_params: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize trigger policy.

        Args:
            trigger_type: Type of trigger
            trigger_params: Trigger-specific parameters
        """
        self.trigger_type = trigger_type
        self.trigger_params = trigger_params or {}
        self._element_count = 0
        self._last_processing_time = datetime.utcnow()

    def should_fire(
        self,
        element_count: int,
        watermark: Watermark,
        processing_time: datetime,
    ) -> bool:
        """
        Determine if trigger should fire.

        Args:
            element_count: Number of elements in window
            watermark: Current watermark
            processing_time: Current processing time

        Returns:
            True if trigger should fire
        """
        if self.trigger_type == TriggerType.EVERY_ELEMENT:
            return True

        elif self.trigger_type == TriggerType.COUNT_BASED:
            count_threshold = self.trigger_params.get("count", 100)
            return element_count >= count_threshold

        elif self.trigger_type == TriggerType.PROCESSING_TIME:
            interval = self.trigger_params.get("interval", timedelta(seconds=5))
            elapsed = processing_time - self._last_processing_time
            if elapsed >= interval:
                self._last_processing_time = processing_time
                return True
            return False

        elif self.trigger_type == TriggerType.WATERMARK:
            # Fire when watermark reaches window end
            return True

        return False


class WindowedAggregate:
    """Holds aggregated state for a window."""

    def __init__(self, window: Window) -> None:
        """
        Initialize windowed aggregate.

        Args:
            window: Window specification
        """
        self.window = window
        self.records: list[Record] = []
        self.state: dict[str, Any] = {}
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()

    def add_record(self, record: Record) -> None:
        """Add record to aggregate."""
        self.records.append(record)
        self.last_updated = datetime.utcnow()

    def get_result(self) -> Record:
        """Get aggregated result."""
        if not self.records:
            return Record(data={})

        return Record(
            data={
                "window_start": self.window.start,
                "window_end": self.window.end,
                "count": len(self.records),
                "records": [r.to_dict() for r in self.records],
                **self.state,
            }
        )


class StreamProcessor:
    """
    Processes streaming data with windowing and watermarks.

    Handles window assignment, watermark tracking, trigger policies,
    and late data.
    """

    def __init__(
        self,
        window_spec: WindowSpec,
        trigger_policy: TriggerPolicy,
        allowed_lateness: timedelta = None,
    ) -> None:
        """
        Initialize stream processor.

        Args:
            window_spec: Window specification
            trigger_policy: Trigger policy
            allowed_lateness: How long to accept late data
        """
        self.window_spec = window_spec
        self.trigger_policy = trigger_policy
        self.window_assigner = WindowAssigner(window_spec)
        self.watermark_tracker = WatermarkTracker(allowed_lateness)

        self._windows: dict[Window, WindowedAggregate] = {}
        self._late_records: list[WindowedRecord] = []
        self._output_records: list[Record] = []
        self._element_count = 0

    def process_record(
        self,
        record: Record,
        event_time: datetime | None = None,
    ) -> list[Record]:
        """
        Process a record through windowing.

        Args:
            record: Record to process
            event_time: Event time (defaults to record timestamp)

        Returns:
            Any records emitted by trigger
        """
        if event_time is None:
            event_time = record.timestamp

        self._element_count += 1

        # Check if record is late
        is_late = self.watermark_tracker.is_late(event_time)

        # Assign to windows
        windows = self.window_assigner.assign_windows(record, event_time)

        # Update watermark
        self.watermark_tracker.update(event_time)

        # Add to windows
        for window in windows:
            if window not in self._windows:
                self._windows[window] = WindowedAggregate(window)

            agg = self._windows[window]
            agg.add_record(record)

            # Check trigger
            if self.trigger_policy.should_fire(
                len(agg.records),
                self.watermark_tracker.get_watermark(),
                datetime.utcnow(),
            ):
                result = agg.get_result()
                self._output_records.append(result)

        if is_late:
            windowed = WindowedRecord(
                record=record,
                window_start=windows[0].start if windows else event_time,
                window_end=windows[0].end if windows else event_time,
                window_id=str(windows[0]) if windows else "unknown",
                is_late=True,
            )
            self._late_records.append(windowed)

        return self._output_records

    def get_results_for_window(self, window: Window) -> Record | None:
        """Get aggregated result for window."""
        if window in self._windows:
            return self._windows[window].get_result()
        return None

    def get_all_results(self) -> list[Record]:
        """Get all emitted results."""
        return self._output_records

    def get_late_records(self) -> list[WindowedRecord]:
        """Get all late-arriving records."""
        return self._late_records

    def get_watermark(self) -> Watermark:
        """Get current watermark."""
        return self.watermark_tracker.get_watermark()


class StatefulProcessor:
    """Handles stateful stream processing (keyed state)."""

    def __init__(self) -> None:
        """Initialize stateful processor."""
        self._state: dict[str, dict[str, Any]] = {}
        self._timers: list[TimerContext] = []

    def get_state(self, key: str, state_name: str) -> Any:
        """Get state for key."""
        if key not in self._state:
            self._state[key] = {}
        return self._state[key].get(state_name)

    def set_state(self, key: str, state_name: str, value: Any) -> None:
        """Set state for key."""
        if key not in self._state:
            self._state[key] = {}
        self._state[key][state_name] = value

    def delete_state(self, key: str, state_name: str) -> None:
        """Delete state for key."""
        if key in self._state and state_name in self._state[key]:
            del self._state[key][state_name]

    def register_timer(
        self,
        key: str,
        timestamp: datetime,
        timer_type: str = "event_time",
    ) -> None:
        """Register a timer callback."""
        timer = TimerContext(
            timestamp=timestamp,
            state_key=key,
            timer_type=timer_type,
        )
        self._timers.append(timer)
        self._timers.sort(key=lambda t: t.timestamp)

    def get_expired_timers(self, current_time: datetime) -> list[TimerContext]:
        """Get timers that have expired."""
        expired = [t for t in self._timers if t.timestamp <= current_time]
        self._timers = [t for t in self._timers if t.timestamp > current_time]
        return expired


class ExactlyOnceProcessor:
    """
    Implements exactly-once processing semantics.

    Uses checkpointing to ensure records are processed exactly once.
    """

    def __init__(self) -> None:
        """Initialize exactly-once processor."""
        self._checkpoint_id = 0
        self._processed_records: dict[int, set] = {}
        self._pending_commits: list[int] = []

    def create_checkpoint(self) -> int:
        """Create a new checkpoint."""
        self._checkpoint_id += 1
        self._processed_records[self._checkpoint_id] = set()
        return self._checkpoint_id

    def mark_processed(self, checkpoint_id: int, record_id: str) -> None:
        """Mark record as processed in checkpoint."""
        if checkpoint_id in self._processed_records:
            self._processed_records[checkpoint_id].add(record_id)

    def commit_checkpoint(self, checkpoint_id: int) -> bool:
        """Commit checkpoint."""
        if checkpoint_id in self._processed_records:
            self._pending_commits.append(checkpoint_id)
            return True
        return False

    def is_duplicate(self, checkpoint_id: int, record_id: str) -> bool:
        """Check if record was already processed."""
        if checkpoint_id in self._processed_records:
            return record_id in self._processed_records[checkpoint_id]
        return False

    def get_pending_commits(self) -> list[int]:
        """Get pending checkpoint commits."""
        return self._pending_commits

    def finalize_commit(self, checkpoint_id: int) -> bool:
        """Finalize checkpoint commit."""
        if checkpoint_id in self._pending_commits:
            self._pending_commits.remove(checkpoint_id)
            return True
        return False


class MicroBatchProcessor:
    """
    Processes stream as micro-batches.

    Groups records into batches for efficient processing.
    """

    def __init__(
        self,
        batch_size: int = 100,
        batch_timeout: timedelta = None,
    ) -> None:
        """
        Initialize micro-batch processor.

        Args:
            batch_size: Records per batch
            batch_timeout: Max time to wait before flushing batch
        """
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout or timedelta(seconds=5)
        self._current_batch: list[Record] = []
        self._batch_start_time = datetime.utcnow()

    def add_record(self, record: Record) -> list[Record] | None:
        """
        Add record to batch.

        Args:
            record: Record to add

        Returns:
            Batch if ready to emit, None otherwise
        """
        self._current_batch.append(record)

        if len(self._current_batch) >= self.batch_size:
            return self.flush_batch()

        return None

    def flush_batch(self) -> list[Record] | None:
        """Flush current batch."""
        if not self._current_batch:
            return None

        batch = self._current_batch
        self._current_batch = []
        self._batch_start_time = datetime.utcnow()
        return batch

    def should_flush(self) -> bool:
        """Check if batch should be flushed by timeout."""
        if not self._current_batch:
            return False

        elapsed = datetime.utcnow() - self._batch_start_time
        return elapsed >= self.batch_timeout
