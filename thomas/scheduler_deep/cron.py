"""
Cron expression parser and evaluator.

Supports 5-field cron syntax with ranges, steps, lists, wildcards, and @shortcuts.
"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

from thomas.scheduler_deep._exceptions import InvalidCronExpression


class CronExpression:
    """Parser and evaluator for cron expressions."""

    # Shortcuts for common cron patterns
    SHORTCUTS: dict[str, str] = {
        "@yearly": "0 0 1 1 *",
        "@annually": "0 0 1 1 *",
        "@monthly": "0 0 1 * *",
        "@weekly": "0 0 ? * 0",
        "@daily": "0 0 * * ?",
        "@midnight": "0 0 * * ?",
        "@hourly": "0 * * * *",
    }

    def __init__(self, expression: str, timezone_str: str = "UTC") -> None:
        """Initialize cron expression parser.

        Args:
            expression: 5-field cron expression or @shortcut
            timezone_str: Timezone for time calculations

        Raises:
            InvalidCronExpression: If expression is invalid
        """
        self.original_expression = expression
        self.timezone_str = timezone_str
        self.timezone_obj = timezone.utc

        # Expand shortcuts
        if expression in self.SHORTCUTS:
            expression = self.SHORTCUTS[expression]

        # Parse cron fields
        fields = expression.split()
        if len(fields) != 5:
            raise InvalidCronExpression(expression, "Must have 5 fields")

        self.minute_field = fields[0]
        self.hour_field = fields[1]
        self.day_field = fields[2]
        self.month_field = fields[3]
        self.weekday_field = fields[4]

        # Parse and validate each field
        self.minutes = self._parse_field(self.minute_field, 0, 59)
        self.hours = self._parse_field(self.hour_field, 0, 23)
        self.days = self._parse_field(self.day_field, 1, 31, allow_any=True)
        self.months = self._parse_field(self.month_field, 1, 12)
        self.weekdays = self._parse_field(self.weekday_field, 0, 6, allow_any=True)

        # Handle ? (no specific value)
        self.day_restricted = self.day_field != "*"
        self.weekday_restricted = self.weekday_field != "*"

    def _parse_field(
        self,
        field: str,
        min_val: int,
        max_val: int,
        allow_any: bool = False,
    ) -> set[int]:
        """Parse a single cron field.

        Args:
            field: Field string to parse
            min_val: Minimum allowed value
            max_val: Maximum allowed value
            allow_any: Whether to allow ? or *

        Returns:
            Set of valid values for this field

        Raises:
            InvalidCronExpression: If field format is invalid
        """
        if field == "*":
            return set(range(min_val, max_val + 1))

        if field == "?" and allow_any:
            return set(range(min_val, max_val + 1))

        values: set[int] = set()

        # Split by comma for lists
        for part in field.split(","):
            part = part.strip()

            # Handle ranges with steps
            if "/" in part:
                range_part, step = part.split("/")
                step_val = int(step)

                if range_part == "*":
                    range_start, range_end = min_val, max_val
                elif "-" in range_part:
                    start_str, end_str = range_part.split("-")
                    range_start = int(start_str)
                    range_end = int(end_str)
                else:
                    range_start = int(range_part)
                    range_end = max_val

                values.update(range(range_start, range_end + 1, step_val))

            # Handle ranges without steps
            elif "-" in part:
                start_str, end_str = part.split("-")
                start = int(start_str)
                end = int(end_str)
                if start > end:
                    raise InvalidCronExpression(self.original_expression, f"Invalid range {start}-{end}")
                values.update(range(start, end + 1))

            # Handle single values
            else:
                val = int(part)
                values.add(val)

        # Validate all values are in range
        for val in values:
            if val < min_val or val > max_val:
                raise InvalidCronExpression(
                    self.original_expression, f"Value {val} out of range [{min_val}, {max_val}]"
                )

        return values

    def matches(self, dt: datetime) -> bool:
        """Check if datetime matches cron expression.

        Args:
            dt: Datetime to check (in UTC)

        Returns:
            True if datetime matches cron expression
        """
        # Check minute and hour
        if dt.minute not in self.minutes:
            return False
        if dt.hour not in self.hours:
            return False

        # Check day and weekday (at least one must match)
        day_match = dt.day in self.days
        weekday_match = dt.weekday() in self.weekdays

        # If both are restricted, at least one must match
        if self.day_restricted and self.weekday_restricted:
            if not (day_match or weekday_match):
                return False
        else:
            # If only day is restricted, it must match
            if self.day_restricted and not day_match:
                return False
            # If only weekday is restricted, it must match
            if self.weekday_restricted and not weekday_match:
                return False

        # Check month
        if dt.month not in self.months:
            return False

        return True

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Calculate next occurrence after from_time.

        Args:
            from_time: Base time for calculation

        Returns:
            Next datetime matching cron expression
        """
        # Start from the next minute
        current = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)

        # Search up to 4 years ahead
        max_iterations = 365 * 4 * 24 * 60
        iterations = 0

        while iterations < max_iterations:
            if self.matches(current):
                return current
            current += timedelta(minutes=1)
            iterations += 1

        return None

    def next_occurrences(
        self,
        from_time: datetime,
        count: int = 10,
    ) -> Iterator[datetime]:
        """Generate next N occurrences.

        Args:
            from_time: Base time for calculation
            count: Number of occurrences to generate

        Yields:
            Next matching datetimes
        """
        current = from_time
        for _ in range(count):
            next_time = self.next_occurrence(current)
            if next_time is None:
                break
            yield next_time
            current = next_time

    def __repr__(self) -> str:
        """String representation."""
        return f"CronExpression({self.original_expression})"


class CronIterator:
    """Iterator over cron occurrences."""

    def __init__(
        self,
        expression: str,
        start_time: datetime,
        end_time: datetime | None = None,
        timezone_str: str = "UTC",
    ) -> None:
        """Initialize cron iterator.

        Args:
            expression: Cron expression
            start_time: Starting time
            end_time: Optional ending time
            timezone_str: Timezone for calculations
        """
        self.cron = CronExpression(expression, timezone_str)
        self.current = start_time
        self.end_time = end_time

    def __iter__(self) -> "CronIterator":
        """Return iterator."""
        return self

    def __next__(self) -> datetime:
        """Get next cron occurrence.

        Returns:
            Next matching datetime

        Raises:
            StopIteration: When end_time is reached
        """
        next_time = self.cron.next_occurrence(self.current)
        if next_time is None:
            raise StopIteration
        if self.end_time and next_time > self.end_time:
            raise StopIteration
        self.current = next_time
        return next_time
