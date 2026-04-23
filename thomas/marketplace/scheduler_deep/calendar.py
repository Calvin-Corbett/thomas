"""
Business calendar for working day/hour calculations.

Provides utilities for calculating business days, working hours, and holiday management.
"""

from datetime import date, datetime, timedelta
from enum import IntEnum


class Weekday(IntEnum):
    """Weekday enumeration (0=Monday, 6=Sunday)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class BusinessCalendar:
    """Business calendar for scheduling within working hours."""

    def __init__(
        self,
        business_start_hour: int = 9,
        business_end_hour: int = 17,
        business_days: set[int] | None = None,
        holidays: set[date] | None = None,
        timezone: str = "UTC",
    ) -> None:
        """Initialize business calendar.

        Args:
            business_start_hour: Start of business hours (0-23)
            business_end_hour: End of business hours (0-23)
            business_days: Set of weekdays (0=Monday, 6=Sunday)
            holidays: Set of holiday dates
            timezone: Timezone identifier

        Raises:
            ValueError: If hours or days are invalid
        """
        if business_start_hour < 0 or business_start_hour > 23:
            raise ValueError("business_start_hour must be 0-23")
        if business_end_hour < 0 or business_end_hour > 23:
            raise ValueError("business_end_hour must be 0-23")
        if business_start_hour >= business_end_hour:
            raise ValueError("business_start_hour must be before business_end_hour")

        self.business_start_hour = business_start_hour
        self.business_end_hour = business_end_hour
        self.business_days = business_days or {
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
        }
        self.holidays = holidays or set()
        self.timezone = timezone

        # Validate business days
        for day in self.business_days:
            if day < 0 or day > 6:
                raise ValueError("business_days must be in range 0-6")

    def is_business_day(self, dt: datetime) -> bool:
        """Check if date is a business day.

        Args:
            dt: Datetime to check

        Returns:
            True if day is a business day and not a holiday
        """
        if dt.date() in self.holidays:
            return False
        return dt.weekday() in self.business_days

    def is_business_hours(self, dt: datetime) -> bool:
        """Check if datetime is during business hours.

        Args:
            dt: Datetime to check

        Returns:
            True if within business hours on a business day
        """
        if not self.is_business_day(dt):
            return False
        return self.business_start_hour <= dt.hour < self.business_end_hour

    def next_business_day(self, dt: datetime) -> datetime:
        """Get next business day.

        Args:
            dt: Starting datetime

        Returns:
            Next business day at start of business hours
        """
        current = dt.replace(hour=self.business_start_hour, minute=0, second=0)
        current += timedelta(days=1)

        max_iterations = 100
        iterations = 0

        while not self.is_business_day(current):
            current += timedelta(days=1)
            iterations += 1
            if iterations > max_iterations:
                raise RuntimeError("Could not find next business day")

        return current

    def previous_business_day(self, dt: datetime) -> datetime:
        """Get previous business day.

        Args:
            dt: Starting datetime

        Returns:
            Previous business day at end of business hours
        """
        current = dt.replace(hour=self.business_end_hour - 1, minute=59, second=59)
        current -= timedelta(days=1)

        max_iterations = 100
        iterations = 0

        while not self.is_business_day(current):
            current -= timedelta(days=1)
            iterations += 1
            if iterations > max_iterations:
                raise RuntimeError("Could not find previous business day")

        return current

    def next_business_hours(self, dt: datetime) -> datetime:
        """Get next business hours occurrence.

        Args:
            dt: Starting datetime

        Returns:
            Next datetime within business hours
        """
        current = dt

        if not self.is_business_day(current):
            return self.next_business_day(current)

        if current.hour < self.business_start_hour:
            return current.replace(hour=self.business_start_hour, minute=0, second=0)

        if current.hour >= self.business_end_hour:
            return self.next_business_day(current)

        return current

    def business_hours_between(
        self,
        start: datetime,
        end: datetime,
    ) -> timedelta:
        """Calculate business hours between two datetimes.

        Args:
            start: Starting datetime
            end: Ending datetime

        Returns:
            Timedelta of business hours
        """
        if start > end:
            raise ValueError("start must be before end")

        total_hours = 0
        current = start

        while current < end:
            if self.is_business_hours(current):
                total_hours += 1
            current += timedelta(hours=1)

        return timedelta(hours=total_hours)

    def add_business_hours(self, dt: datetime, hours: float) -> datetime:
        """Add business hours to datetime.

        Args:
            dt: Starting datetime
            hours: Number of business hours to add

        Returns:
            Datetime after adding business hours
        """
        remaining_hours = hours
        current = self.next_business_hours(dt)

        while remaining_hours > 0:
            if self.is_business_hours(current):
                remaining_hours -= 1
                current += timedelta(hours=1)
            else:
                current = self.next_business_hours(current)

        return current

    def add_business_days(self, dt: datetime, days: int) -> datetime:
        """Add business days to datetime.

        Args:
            dt: Starting datetime
            days: Number of business days to add

        Returns:
            Datetime after adding business days
        """
        if days < 0:
            raise ValueError("days must be non-negative")

        current = self.next_business_day(dt)
        for _ in range(days - 1):
            current = self.next_business_day(current)

        return current

    def add_holiday(self, holiday_date: date) -> None:
        """Add a holiday to the calendar.

        Args:
            holiday_date: Date to mark as holiday
        """
        self.holidays.add(holiday_date)

    def remove_holiday(self, holiday_date: date) -> None:
        """Remove a holiday from the calendar.

        Args:
            holiday_date: Date to remove from holidays
        """
        self.holidays.discard(holiday_date)

    def set_business_days(self, business_days: set[int]) -> None:
        """Set which days are business days.

        Args:
            business_days: Set of weekday integers (0=Monday, 6=Sunday)

        Raises:
            ValueError: If invalid weekdays provided
        """
        for day in business_days:
            if day < 0 or day > 6:
                raise ValueError("Weekday must be 0-6")
        self.business_days = business_days

    def set_business_hours(self, start_hour: int, end_hour: int) -> None:
        """Set business hours.

        Args:
            start_hour: Start of business hours (0-23)
            end_hour: End of business hours (0-23)

        Raises:
            ValueError: If hours are invalid
        """
        if start_hour < 0 or start_hour > 23:
            raise ValueError("start_hour must be 0-23")
        if end_hour < 0 or end_hour > 23:
            raise ValueError("end_hour must be 0-23")
        if start_hour >= end_hour:
            raise ValueError("start_hour must be before end_hour")

        self.business_start_hour = start_hour
        self.business_end_hour = end_hour

    def get_holidays(self) -> set[date]:
        """Get set of holidays.

        Returns:
            Set of holiday dates
        """
        return self.holidays.copy()

    def get_business_days(self) -> set[int]:
        """Get set of business weekdays.

        Returns:
            Set of business weekday integers
        """
        return self.business_days.copy()

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"BusinessCalendar("
            f"hours={self.business_start_hour}-{self.business_end_hour}, "
            f"days={self.business_days}, "
            f"holidays={len(self.holidays)})"
        )
