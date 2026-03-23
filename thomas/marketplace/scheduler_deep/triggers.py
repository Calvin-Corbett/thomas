"""
Advanced trigger types for job scheduling.

Includes interval, date, calendar-based, dependency, and compound triggers.
"""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum

from thomas.marketplace.scheduler_deep._types import Calendar, Trigger


class MissedFirePolicy(Enum):
    """Policy for handling missed job executions."""

    SKIP = "skip"
    RUN_ALL = "run_all"
    RUN_LATEST = "run_latest"


class CalendarTrigger(Trigger):
    """Trigger based on business calendar."""

    def __init__(
        self,
        calendar: Calendar,
        name: str = "calendar",
        timezone: str = "UTC",
    ) -> None:
        """Initialize calendar trigger.

        Args:
            calendar: Business calendar configuration
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.calendar = calendar

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if current time is during business hours."""
        now = datetime.now(timezone.utc)
        return self.calendar.is_business_hours(now)

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next business hours occurrence."""
        current = from_time
        max_iterations = 60  # Check up to 60 days ahead

        for _ in range(max_iterations):
            if self.calendar.is_business_hours(current):
                return current
            current += timedelta(hours=1)

        return None


class CompoundTrigger(Trigger):
    """Combine multiple triggers with AND/OR logic."""

    def __init__(
        self,
        triggers: list[Trigger],
        condition: str = "AND",
        name: str = "compound",
        timezone: str = "UTC",
    ) -> None:
        """Initialize compound trigger.

        Args:
            triggers: List of triggers to combine
            condition: "AND" or "OR" logic
            name: Trigger name
            timezone: Timezone for scheduling

        Raises:
            ValueError: If condition is invalid
        """
        super().__init__(name, timezone)
        if condition not in ("AND", "OR"):
            raise ValueError("condition must be 'AND' or 'OR'")
        self.triggers = triggers
        self.condition = condition

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if combined trigger condition is met."""
        if not self.triggers:
            return False

        results = [trigger.should_run(last_run) for trigger in self.triggers]

        if self.condition == "AND":
            return all(results)
        else:
            return any(results)

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence based on condition."""
        if not self.triggers:
            return None

        if self.condition == "AND":
            return self._next_and(from_time)
        else:
            return self._next_or(from_time)

    def _next_and(self, from_time: datetime) -> datetime | None:
        """Get next occurrence where all triggers match."""
        current = from_time
        max_iterations = 1000

        for _ in range(max_iterations):
            all_match = all(
                trigger.matches(current) if hasattr(trigger, "matches") else trigger.should_run(current)
                for trigger in self.triggers
            )
            if all_match:
                return current
            current += timedelta(minutes=1)

        return None

    def _next_or(self, from_time: datetime) -> datetime | None:
        """Get next occurrence where any trigger matches."""
        next_times = []
        for trigger in self.triggers:
            next_time = trigger.next_occurrence(from_time)
            if next_time:
                next_times.append(next_time)

        return min(next_times) if next_times else None


class AdaptiveTrigger(Trigger):
    """Trigger that adapts based on job execution history."""

    def __init__(
        self,
        base_trigger: Trigger,
        adapt_func: Callable[[dict[str, any]], Trigger],
        name: str = "adaptive",
        timezone: str = "UTC",
    ) -> None:
        """Initialize adaptive trigger.

        Args:
            base_trigger: Base trigger to start with
            adapt_func: Function to adapt trigger based on stats
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.base_trigger = base_trigger
        self.adapt_func = adapt_func
        self.current_trigger = base_trigger

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if current trigger should run."""
        return self.current_trigger.should_run(last_run)

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence from current trigger."""
        return self.current_trigger.next_occurrence(from_time)

    def update_trigger(self, stats: dict[str, any]) -> None:
        """Update trigger based on job statistics.

        Args:
            stats: Job execution statistics
        """
        self.current_trigger = self.adapt_func(stats)


class RandomTrigger(Trigger):
    """Trigger at random times within a window."""

    def __init__(
        self,
        min_interval_seconds: int,
        max_interval_seconds: int,
        name: str = "random",
        timezone: str = "UTC",
    ) -> None:
        """Initialize random trigger.

        Args:
            min_interval_seconds: Minimum interval between runs
            max_interval_seconds: Maximum interval between runs
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.min_interval = min_interval_seconds
        self.max_interval = max_interval_seconds
        self._next_run: datetime | None = None

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if random interval has elapsed."""
        if last_run is None:
            import random

            interval = random.randint(self.min_interval, self.max_interval)
            self._next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
            return False

        return datetime.now(timezone.utc) >= self._next_run

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence (approximate)."""
        import random

        interval = random.randint(self.min_interval, self.max_interval)
        return from_time + timedelta(seconds=interval)


class ConditionalTrigger(Trigger):
    """Trigger based on a condition function."""

    def __init__(
        self,
        condition_func: Callable[[], bool],
        base_trigger: Trigger | None = None,
        name: str = "conditional",
        timezone: str = "UTC",
    ) -> None:
        """Initialize conditional trigger.

        Args:
            condition_func: Function returning True/False
            base_trigger: Optional base trigger to also check
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.condition_func = condition_func
        self.base_trigger = base_trigger

    def should_run(self, last_run: datetime | None) -> bool:
        """Check condition and optional base trigger."""
        if not self.condition_func():
            return False
        if self.base_trigger:
            return self.base_trigger.should_run(last_run)
        return True

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence if condition allows."""
        if not self.condition_func():
            return None
        if self.base_trigger:
            return self.base_trigger.next_occurrence(from_time)
        return from_time


class ExponentialBackoffTrigger(Trigger):
    """Trigger with exponential backoff for retries."""

    def __init__(
        self,
        initial_interval_seconds: int = 1,
        multiplier: float = 2.0,
        max_interval_seconds: int = 3600,
        name: str = "exponential_backoff",
        timezone: str = "UTC",
    ) -> None:
        """Initialize exponential backoff trigger.

        Args:
            initial_interval_seconds: Starting interval
            multiplier: Multiplier for each retry
            max_interval_seconds: Maximum interval cap
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.initial_interval = initial_interval_seconds
        self.multiplier = multiplier
        self.max_interval = max_interval_seconds
        self.retry_count = 0

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if backoff interval has elapsed."""
        if last_run is None:
            return True

        interval = min(self.initial_interval * (self.multiplier**self.retry_count), self.max_interval)
        elapsed = datetime.now(timezone.utc) - last_run
        return elapsed.total_seconds() >= interval

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence with backoff."""
        interval = min(self.initial_interval * (self.multiplier**self.retry_count), self.max_interval)
        return from_time + timedelta(seconds=interval)

    def record_retry(self) -> None:
        """Record a retry attempt."""
        self.retry_count += 1

    def reset(self) -> None:
        """Reset retry counter."""
        self.retry_count = 0
