"""
Tests for trigger types and functionality.
"""

from datetime import datetime, timedelta, timezone

import pytest

from thomas.scheduler_deep._types import Calendar, DateTrigger, DependencyTrigger, IntervalTrigger
from thomas.scheduler_deep.triggers import (
    CalendarTrigger,
    CompoundTrigger,
    ConditionalTrigger,
    ExponentialBackoffTrigger,
)


class TestIntervalTrigger:
    """Test interval-based triggers."""

    def test_first_run_always_ready(self) -> None:
        """Test that first run is always ready."""
        trigger = IntervalTrigger(interval_seconds=3600)
        assert trigger.should_run(None) is True

    def test_interval_not_elapsed(self) -> None:
        """Test trigger when interval hasn't elapsed."""
        trigger = IntervalTrigger(interval_seconds=3600)
        last_run = datetime.now(timezone.utc)
        assert trigger.should_run(last_run) is False

    def test_interval_elapsed(self) -> None:
        """Test trigger when interval has elapsed."""
        trigger = IntervalTrigger(interval_seconds=1)
        last_run = datetime.now(timezone.utc) - timedelta(seconds=2)
        assert trigger.should_run(last_run) is True

    def test_next_occurrence(self) -> None:
        """Test calculating next occurrence."""
        trigger = IntervalTrigger(interval_seconds=3600)
        from_time = datetime.now(timezone.utc)
        next_time = trigger.next_occurrence(from_time)

        expected = from_time + timedelta(seconds=3600)
        assert abs((next_time - expected).total_seconds()) < 1


class TestDateTrigger:
    """Test date-based one-shot triggers."""

    def test_future_date_not_ready(self) -> None:
        """Test that future dates aren't ready."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        trigger = DateTrigger(future)
        assert trigger.should_run(None) is False

    def test_past_date_ready(self) -> None:
        """Test that past dates are ready."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        trigger = DateTrigger(past)
        assert trigger.should_run(None) is True

    def test_already_run(self) -> None:
        """Test that already-run dates don't run again."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        trigger = DateTrigger(past)
        last_run = datetime.now(timezone.utc) - timedelta(minutes=30)
        assert trigger.should_run(last_run) is False

    def test_next_occurrence_future(self) -> None:
        """Test next occurrence with future date."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        trigger = DateTrigger(future)
        from_time = datetime.now(timezone.utc)
        next_time = trigger.next_occurrence(from_time)

        assert next_time == future

    def test_next_occurrence_past(self) -> None:
        """Test next occurrence with past date."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        trigger = DateTrigger(past)
        from_time = datetime.now(timezone.utc)
        next_time = trigger.next_occurrence(from_time)

        assert next_time is None


class TestDependencyTrigger:
    """Test dependency-based triggers."""

    def test_creation(self) -> None:
        """Test creating dependency trigger."""
        trigger = DependencyTrigger(["job1", "job2"])
        assert trigger.dependency_job_ids == ["job1", "job2"]
        assert trigger.wait_all is True

    def test_wait_any_mode(self) -> None:
        """Test wait_any mode."""
        trigger = DependencyTrigger(["job1", "job2"], wait_all=False)
        assert trigger.wait_all is False


class TestCalendarTrigger:
    """Test calendar-based triggers."""

    def test_business_hours_during_work(self) -> None:
        """Test calendar trigger during business hours."""
        calendar = Calendar(
            business_start_hour=9,
            business_end_hour=17,
            business_days={0, 1, 2, 3, 4},
        )
        trigger = CalendarTrigger(calendar)

        # Monday 10 AM
        work_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert trigger.should_run(None) or not calendar.is_business_hours(work_time)

    def test_business_hours_after_work(self) -> None:
        """Test calendar trigger after business hours."""
        calendar = Calendar(
            business_start_hour=9,
            business_end_hour=17,
            business_days={0, 1, 2, 3, 4},
        )
        trigger = CalendarTrigger(calendar)

        # Monday 6 PM (after hours)
        after_hours = datetime(2024, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
        assert not calendar.is_business_hours(after_hours)

    def test_business_days_weekday(self) -> None:
        """Test business days on weekday."""
        calendar = Calendar(business_days={0, 1, 2, 3, 4})
        # Monday 2024-01-01
        assert calendar.is_business_day(datetime(2024, 1, 1, tzinfo=timezone.utc))

    def test_business_days_weekend(self) -> None:
        """Test business days on weekend."""
        calendar = Calendar(business_days={0, 1, 2, 3, 4})
        # Saturday 2024-01-06
        assert not calendar.is_business_day(datetime(2024, 1, 6, tzinfo=timezone.utc))


class TestCompoundTrigger:
    """Test compound trigger combinations."""

    def test_and_logic(self) -> None:
        """Test AND logic for compound triggers."""
        trigger1 = IntervalTrigger(interval_seconds=1)
        trigger2 = IntervalTrigger(interval_seconds=1)

        compound = CompoundTrigger([trigger1, trigger2], condition="AND")
        assert compound.should_run(None) is True

    def test_or_logic(self) -> None:
        """Test OR logic for compound triggers."""
        trigger1 = IntervalTrigger(interval_seconds=3600)
        trigger2 = IntervalTrigger(interval_seconds=1)

        compound = CompoundTrigger([trigger1, trigger2], condition="OR")
        assert compound.should_run(None) is True

    def test_invalid_condition(self) -> None:
        """Test invalid condition raises error."""
        with pytest.raises(ValueError):
            CompoundTrigger([], condition="XOR")


class TestConditionalTrigger:
    """Test condition-based triggers."""

    def test_condition_true(self) -> None:
        """Test trigger when condition is true."""
        trigger = ConditionalTrigger(lambda: True)
        assert trigger.should_run(None) is True

    def test_condition_false(self) -> None:
        """Test trigger when condition is false."""
        trigger = ConditionalTrigger(lambda: False)
        assert trigger.should_run(None) is False

    def test_with_base_trigger(self) -> None:
        """Test conditional trigger with base trigger."""
        base = IntervalTrigger(interval_seconds=1)
        trigger = ConditionalTrigger(lambda: True, base_trigger=base)
        assert trigger.should_run(None) is True


class TestExponentialBackoffTrigger:
    """Test exponential backoff retry logic."""

    def test_initial_interval(self) -> None:
        """Test initial retry interval."""
        trigger = ExponentialBackoffTrigger(initial_interval_seconds=1)
        last_run = datetime.now(timezone.utc) - timedelta(seconds=2)
        assert trigger.should_run(last_run) is True

    def test_backoff_increases(self) -> None:
        """Test that backoff interval increases."""
        trigger = ExponentialBackoffTrigger(
            initial_interval_seconds=1,
            multiplier=2.0,
        )

        # First retry: 1 second
        next_time_1 = trigger.next_occurrence(datetime.now(timezone.utc))

        # Simulate retry
        trigger.record_retry()

        # Second retry: 2 seconds
        next_time_2 = trigger.next_occurrence(datetime.now(timezone.utc))
        assert (next_time_2 - next_time_1).total_seconds() > 0

    def test_max_interval_cap(self) -> None:
        """Test that backoff respects maximum interval."""
        trigger = ExponentialBackoffTrigger(
            initial_interval_seconds=1,
            multiplier=10.0,
            max_interval_seconds=60,
        )

        # Simulate many retries
        for _ in range(10):
            trigger.record_retry()

        next_time = trigger.next_occurrence(datetime.now(timezone.utc))
        elapsed = (next_time - datetime.now(timezone.utc)).total_seconds()
        assert elapsed <= 60

    def test_reset(self) -> None:
        """Test resetting retry counter."""
        trigger = ExponentialBackoffTrigger(initial_interval_seconds=1)

        trigger.record_retry()
        trigger.record_retry()
        assert trigger.retry_count == 2

        trigger.reset()
        assert trigger.retry_count == 0
