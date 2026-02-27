"""
Discrete Event Simulation (DES) engine.

Implements core DES infrastructure with priority queue-based event scheduling,
event handlers, and statistics collection.
"""

import heapq
import logging
import time as walltime
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._exceptions import EventError
from ._types import Event, EventType, MetricSample, SimConfig, SimResult, SimState

logger = logging.getLogger(__name__)


@dataclass
class EventHandler:
    """Handler for events of a specific type."""

    event_type: EventType
    handler_func: Callable[[Event, "DiscreteEventSimulation"], None]
    priority: int = 0


@dataclass
class ConditionalEvent:
    """Event that fires when a condition is met."""

    condition: Callable[["DiscreteEventSimulation"], bool]
    action: Callable[["DiscreteEventSimulation"], None]
    check_frequency: float = 1.0
    last_check_time: float = 0.0
    fired: bool = False


class DiscreteEventSimulation:
    """
    Discrete Event Simulation engine with priority queue event scheduling.

    Features:
    - Heap-based event priority queue
    - Event handler registry
    - Conditional event triggering
    - Event cancellation
    - Statistics collection
    - Event logging
    """

    def __init__(self, config: SimConfig) -> None:
        """
        Initialize discrete event simulator.

        Args:
            config: Simulation configuration parameters
        """
        self.config = config
        self.state = SimState(current_time=config.start_time)

        # Event management
        self._event_queue: list[Event] = []
        self._next_event_id = 0
        self._cancelled_events: set[int | None] = set()
        self._event_handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._conditional_events: list[ConditionalEvent] = []

        # Statistics
        self._events_log: list[Event] = []
        self._event_counts: dict[EventType, int] = defaultdict(int)
        self._event_times: dict[EventType, list[float]] = defaultdict(list)

        # Metrics
        self._metrics: dict[str, float] = {}
        self._metric_samples: list[MetricSample] = []

        self._wall_start_time = 0.0

    def register_event_handler(
        self,
        event_type: EventType,
        handler: Callable[[Event, "DiscreteEventSimulation"], None],
        priority: int = 0,
    ) -> None:
        """
        Register handler function for event type.

        Args:
            event_type: Type of event to handle
            handler: Callable taking (event, simulator)
            priority: Execution priority (higher = earlier)
        """
        event_handler = EventHandler(event_type, handler, priority)
        self._event_handlers[event_type].append(event_handler)
        self._event_handlers[event_type].sort(key=lambda h: h.priority, reverse=True)

    def schedule_event(
        self,
        event_type: EventType,
        time: float,
        data: dict[str, Any] | None = None,
        priority: int = 0,
    ) -> int:
        """
        Schedule event at future time.

        Args:
            event_type: Type of event
            time: Simulation time to trigger
            data: Event-specific data
            priority: Lower = earlier processing at same time

        Returns:
            Event ID for cancellation
        """
        if time < self.state.current_time:
            raise EventError(f"Cannot schedule event in past: {time} < {self.state.current_time}")

        event_id = self._next_event_id
        self._next_event_id += 1

        event = Event(
            time=time,
            event_type=event_type,
            data=data or {},
            priority=priority,
            event_id=event_id,
        )

        heapq.heappush(self._event_queue, event)
        logger.debug(f"Scheduled {event_type} at time {time} (ID: {event_id})")

        return event_id

    def schedule_conditional_event(
        self,
        condition: Callable[["DiscreteEventSimulation"], bool],
        action: Callable[["DiscreteEventSimulation"], None],
        check_frequency: float = 1.0,
    ) -> None:
        """
        Register conditional event that fires when condition met.

        Args:
            condition: Callable returning boolean
            action: Callable to invoke when condition true
            check_frequency: How often to check condition (sim time units)
        """
        cond_event = ConditionalEvent(condition, action, check_frequency)
        self._conditional_events.append(cond_event)

    def cancel_event(self, event_id: int) -> bool:
        """
        Cancel scheduled event by ID.

        Args:
            event_id: ID returned from schedule_event

        Returns:
            True if cancelled, False if not found
        """
        if event_id in self._cancelled_events:
            return False

        self._cancelled_events.add(event_id)
        logger.debug(f"Cancelled event {event_id}")
        return True

    def _process_event(self, event: Event) -> None:
        """
        Execute event by calling registered handlers.

        Args:
            event: Event to process
        """
        # Record statistics
        self._events_log.append(event)
        self._event_counts[event.event_type] += 1
        self._event_times[event.event_type].append(event.time)
        self.state.events_processed += 1

        # Call registered handlers in priority order
        if event.event_type in self._event_handlers:
            for handler in self._event_handlers[event.event_type]:
                try:
                    handler.handler_func(event, self)
                except Exception as e:
                    logger.error(f"Handler failed for {event.event_type}: {e}")
                    self.state.errors = getattr(self.state, "errors", [])
                    if not hasattr(self.state, "errors"):
                        self.state.errors = []
                    self.state.errors.append(str(e))

    def _check_conditional_events(self) -> None:
        """Check and fire conditional events if conditions met."""
        for cond_event in self._conditional_events:
            if self.state.current_time - cond_event.last_check_time >= cond_event.check_frequency:
                cond_event.last_check_time = self.state.current_time
                try:
                    if cond_event.condition(self):
                        cond_event.action(self)
                        cond_event.fired = True
                except Exception as e:
                    logger.error(f"Conditional event failed: {e}")

    def record_metric(
        self,
        metric_name: str,
        value: float,
        agent_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record metric sample.

        Args:
            metric_name: Name of metric
            value: Measured value
            agent_id: Associated agent (optional)
            metadata: Additional context
        """
        sample = MetricSample(
            metric_name=metric_name,
            value=value,
            time=self.state.current_time,
            agent_id=agent_id,
            metadata=metadata or {},
        )
        self._metric_samples.append(sample)

    def run(self) -> SimResult:
        """
        Run simulation until stopping condition met.

        Returns:
            Complete simulation result
        """
        self._wall_start_time = walltime.time()
        logger.info(f"Starting simulation: {self.config.sim_id}")

        while True:
            # Check stopping conditions
            if self.config.end_time is not None and self.state.current_time >= self.config.end_time:
                self.state.stopped = True
                self.state.stop_reason = "End time reached"
                break

            if self.config.max_events is not None and self.state.events_processed >= self.config.max_events:
                self.state.stopped = True
                self.state.stop_reason = "Event limit reached"
                break

            if not self._event_queue:
                self.state.stopped = True
                self.state.stop_reason = "No more events"
                break

            # Get next event
            event = heapq.heappop(self._event_queue)

            # Skip cancelled events
            if event.event_id in self._cancelled_events:
                continue

            # Advance simulation time
            self.state.current_time = event.time

            # Check conditional events
            self._check_conditional_events()

            # Process event
            self._process_event(event)

        # Calculate statistics
        self._compute_statistics()

        wall_time = walltime.time() - self._wall_start_time
        logger.info(f"Simulation completed: {self.state.events_processed} events in {wall_time:.2f}s")

        return SimResult(
            config=self.config,
            final_state=self.state,
            events_log=self._events_log,
            metrics=self._metrics,
            samples=self._metric_samples,
            wall_time=wall_time,
        )

    def _compute_statistics(self) -> None:
        """Compute aggregate statistics from collected data."""
        # Event counts
        for event_type in self._event_counts:
            self._metrics[f"event_count_{event_type.value}"] = float(self._event_counts[event_type])

        # Event rates
        if self.state.current_time > self.config.warmup_time:
            elapsed = self.state.current_time - self.config.warmup_time
            for event_type in self._event_counts:
                if elapsed > 0:
                    rate = self._event_counts[event_type] / elapsed
                    self._metrics[f"event_rate_{event_type.value}"] = rate

        # Timing statistics
        for event_type in self._event_times:
            times = self._event_times[event_type]
            if times:
                self._metrics[f"event_mean_time_{event_type.value}"] = sum(times) / len(times)
                self._metrics[f"event_min_time_{event_type.value}"] = min(times)
                self._metrics[f"event_max_time_{event_type.value}"] = max(times)

        # Metric aggregates
        sample_groups: dict[str, list[float]] = defaultdict(list)
        for sample in self._metric_samples:
            if sample.time >= self.config.warmup_time:
                sample_groups[sample.metric_name].append(sample.value)

        for metric_name, values in sample_groups.items():
            if values:
                self._metrics[f"{metric_name}_mean"] = sum(values) / len(values)
                self._metrics[f"{metric_name}_min"] = min(values)
                self._metrics[f"{metric_name}_max"] = max(values)
                self._metrics[f"{metric_name}_count"] = float(len(values))

    def get_metric(self, metric_name: str) -> float | None:
        """Get computed metric value."""
        return self._metrics.get(metric_name)

    def get_all_metrics(self) -> dict[str, float]:
        """Get all computed metrics."""
        return self._metrics.copy()

    def get_events_of_type(self, event_type: EventType) -> list[Event]:
        """Get all logged events of specific type."""
        return [e for e in self._events_log if e.event_type == event_type]

    def peek_next_event(self) -> Event | None:
        """Get next event without processing it."""
        if self._event_queue:
            return self._event_queue[0]
        return None

    def queue_size(self) -> int:
        """Return number of pending events."""
        return len(self._event_queue)
