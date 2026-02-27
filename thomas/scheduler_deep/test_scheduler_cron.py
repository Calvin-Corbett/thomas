"""
Tests for cron expression parsing and evaluation.
"""

from datetime import datetime, timezone

import pytest

from thomas.scheduler_deep._exceptions import InvalidCronExpression
from thomas.scheduler_deep.cron import CronExpression, CronIterator


class TestCronExpression:
    """Test cron expression parsing and matching."""

    def test_wildcard_all_values(self) -> None:
        """Test wildcard matching all values."""
        cron = CronExpression("* * * * *")
        now = datetime.now(timezone.utc)
        assert cron.matches(now) is True

    def test_specific_minute_and_hour(self) -> None:
        """Test matching specific minute and hour."""
        cron = CronExpression("30 14 * * *")
        test_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=timezone.utc)
        assert cron.matches(test_time) is True

        non_match = datetime(2024, 1, 1, 14, 31, 0, tzinfo=timezone.utc)
        assert cron.matches(non_match) is False

    def test_range_parsing(self) -> None:
        """Test parsing range syntax."""
        cron = CronExpression("0 9-17 * * *")
        for hour in range(9, 18):
            test_time = datetime(2024, 1, 1, hour, 0, 0, tzinfo=timezone.utc)
            assert cron.matches(test_time) is True

        outside = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(outside) is False

    def test_step_values(self) -> None:
        """Test step syntax."""
        cron = CronExpression("*/15 * * * *")
        for minute in [0, 15, 30, 45]:
            test_time = datetime(2024, 1, 1, 12, minute, 0, tzinfo=timezone.utc)
            assert cron.matches(test_time) is True

        outside = datetime(2024, 1, 1, 12, 7, 0, tzinfo=timezone.utc)
        assert cron.matches(outside) is False

    def test_list_values(self) -> None:
        """Test list syntax."""
        cron = CronExpression("0 9,12,15 * * *")
        for hour in [9, 12, 15]:
            test_time = datetime(2024, 1, 1, hour, 0, 0, tzinfo=timezone.utc)
            assert cron.matches(test_time) is True

        outside = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(outside) is False

    def test_weekday_matching(self) -> None:
        """Test weekday matching."""
        # Monday-Friday
        cron = CronExpression("0 9 * * 0-4")

        # Monday 2024-01-01
        monday = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(monday) is True

        # Saturday
        saturday = datetime(2024, 1, 6, 9, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(saturday) is False

    def test_invalid_expression_too_few_fields(self) -> None:
        """Test validation of field count."""
        with pytest.raises(InvalidCronExpression):
            CronExpression("0 9 * *")

    def test_invalid_expression_out_of_range(self) -> None:
        """Test validation of value ranges."""
        with pytest.raises(InvalidCronExpression):
            CronExpression("0 25 * * *")  # Hour 25 is invalid

    def test_next_occurrence(self) -> None:
        """Test calculating next occurrence."""
        cron = CronExpression("0 9 * * *")
        base = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        next_time = cron.next_occurrence(base)

        assert next_time is not None
        assert next_time.hour == 9
        assert next_time.minute == 0
        assert next_time.date() == base.date()

    def test_next_occurrence_tomorrow(self) -> None:
        """Test next occurrence on next day."""
        cron = CronExpression("0 9 * * *")
        base = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        next_time = cron.next_occurrence(base)

        assert next_time is not None
        assert next_time.hour == 9
        assert next_time.date() > base.date()

    def test_shortcuts_daily(self) -> None:
        """Test @daily shortcut."""
        cron = CronExpression("@daily")
        test_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(test_time) is True

    def test_shortcuts_hourly(self) -> None:
        """Test @hourly shortcut."""
        cron = CronExpression("@hourly")
        test_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert cron.matches(test_time) is True

    def test_next_occurrences_iterator(self) -> None:
        """Test generating multiple occurrences."""
        cron = CronExpression("0 9 * * *")
        base = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        occurrences = list(cron.next_occurrences(base, count=5))

        assert len(occurrences) == 5
        # All should be at 9 AM
        for occ in occurrences:
            assert occ.hour == 9
            assert occ.minute == 0


class TestCronIterator:
    """Test cron iterator functionality."""

    def test_iterator_basic(self) -> None:
        """Test basic iterator functionality."""
        cron_iter = CronIterator(
            "0 9 * * *",
            datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 5, 0, 0, 0, tzinfo=timezone.utc),
        )

        occurrences = list(cron_iter)
        assert len(occurrences) > 0

        for occ in occurrences:
            assert occ.hour == 9
            assert occ.minute == 0

    def test_iterator_with_end_time(self) -> None:
        """Test iterator respects end time."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 3, 0, 0, 0, tzinfo=timezone.utc)

        cron_iter = CronIterator("0 9 * * *", start, end)
        occurrences = list(cron_iter)

        assert all(occ < end for occ in occurrences)

    def test_iterator_no_end_time(self) -> None:
        """Test iterator without end time stops manually."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cron_iter = CronIterator("0 9 * * *", start)

        # Manually get a few occurrences
        first = next(cron_iter)
        assert first.hour == 9

        second = next(cron_iter)
        assert second > first

    def test_complex_cron_expression(self) -> None:
        """Test complex cron patterns."""
        # Every 15 minutes during business hours on weekdays
        cron = CronExpression("*/15 9-17 * * 1-5")

        business_hours = datetime(2024, 1, 1, 10, 15, 0, tzinfo=timezone.utc)
        assert cron.matches(business_hours) is True

        outside_hours = datetime(2024, 1, 1, 8, 15, 0, tzinfo=timezone.utc)
        assert cron.matches(outside_hours) is False

        weekend = datetime(2024, 1, 6, 10, 15, 0, tzinfo=timezone.utc)
        assert cron.matches(weekend) is False
