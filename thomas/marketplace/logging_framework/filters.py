"""Log filters for controlling which records are processed."""

import re
import threading
import time
from collections.abc import Callable
from typing import Any

from thomas.marketplace.logging_framework._exceptions import FilterError
from thomas.marketplace.logging_framework._types import LogFilter, LogLevel, LogRecord


class LevelFilter(LogFilter):
    """Filter that accepts records within a level range."""

    def __init__(
        self,
        min_level: LogLevel = LogLevel.DEBUG,
        max_level: LogLevel = LogLevel.CRITICAL,
    ) -> None:
        """Initialize level filter.

        Args:
            min_level: Minimum log level to accept
            max_level: Maximum log level to accept
        """
        self.min_level = min_level
        self.max_level = max_level

    def filter(self, record: LogRecord) -> bool:
        """Filter by log level.

        Args:
            record: Log record to filter

        Returns:
            True if record level is in range
        """
        return self.min_level <= record.level <= self.max_level


class RegexFilter(LogFilter):
    """Filter that matches on message or field values using regex."""

    def __init__(
        self,
        pattern: str,
        field: str = "message",
        invert: bool = False,
    ) -> None:
        """Initialize regex filter.

        Args:
            pattern: Regex pattern to match
            field: Field to match against ("message" or field name)
            invert: Invert filter logic (reject matching records)
        """
        try:
            self.pattern = re.compile(pattern)
        except re.error as e:
            raise FilterError(f"Invalid regex pattern: {e}", "RegexFilter")
        self.field = field
        self.invert = invert

    def filter(self, record: LogRecord) -> bool:
        """Filter by regex pattern.

        Args:
            record: Log record to filter

        Returns:
            True if pattern matches (or doesn't match if inverted)
        """
        try:
            if self.field == "message":
                text = record.message
            elif self.field in record.fields:
                text = str(record.fields[self.field].value)
            else:
                return not self.invert

            matches = bool(self.pattern.search(text))
            return not matches if self.invert else matches
        except (ValueError, TypeError):
            return not self.invert


class RateLimitFilter(LogFilter):
    """Filter that rate-limits logging using token bucket algorithm."""

    def __init__(
        self,
        rate_per_second: float = 10.0,
        key_field: str | None = None,
    ) -> None:
        """Initialize rate limit filter.

        Args:
            rate_per_second: Maximum logs per second
            key_field: Field to rate limit by (limits per unique value)
        """
        if rate_per_second <= 0:
            raise FilterError("Rate must be positive", "RateLimitFilter")
        self.rate_per_second = rate_per_second
        self.key_field = key_field
        self._tokens: dict[str, float] = {}
        self._last_update: dict[str, float] = {}
        self._lock = threading.RLock()

    def filter(self, record: LogRecord) -> bool:
        """Filter using token bucket algorithm.

        Args:
            record: Log record to filter

        Returns:
            True if under rate limit
        """
        with self._lock:
            # Determine the key (global or per-field)
            if self.key_field:
                if self.key_field in record.fields:
                    key = str(record.fields[self.key_field].value)
                else:
                    key = "__default__"
            else:
                key = "__global__"

            now = time.time()

            # Initialize if needed
            if key not in self._tokens:
                self._tokens[key] = self.rate_per_second
                self._last_update[key] = now

            # Add tokens based on elapsed time
            elapsed = now - self._last_update[key]
            self._tokens[key] = min(
                self.rate_per_second,
                self._tokens[key] + elapsed * self.rate_per_second,
            )
            self._last_update[key] = now

            # Check if we can log
            if self._tokens[key] >= 1:
                self._tokens[key] -= 1
                return True
            return False


class SamplingFilter(LogFilter):
    """Filter that samples logs probabilistically."""

    def __init__(
        self,
        sample_rate: float = 0.5,
        consistent_key: str | None = None,
    ) -> None:
        """Initialize sampling filter.

        Args:
            sample_rate: Probability of logging (0.0 to 1.0)
            consistent_key: Field to consistently sample by
        """
        if not 0.0 <= sample_rate <= 1.0:
            raise FilterError("Sample rate must be between 0 and 1", "SamplingFilter")
        self.sample_rate = sample_rate
        self.consistent_key = consistent_key
        self._hash_cache: dict[str, bool] = {}

    def filter(self, record: LogRecord) -> bool:
        """Filter using probabilistic sampling.

        Args:
            record: Log record to filter

        Returns:
            True if record should be sampled
        """
        import random

        if self.sample_rate == 1.0:
            return True

        # Consistent sampling by field value
        if self.consistent_key:
            if self.consistent_key in record.fields:
                key = str(record.fields[self.consistent_key].value)
                if key not in self._hash_cache:
                    # Use hash for consistent sampling per key
                    hash_val = hash(key) % 100
                    self._hash_cache[key] = hash_val < (self.sample_rate * 100)
                return self._hash_cache[key]

        # Random sampling
        return random.random() < self.sample_rate


class DeduplicationFilter(LogFilter):
    """Filter that suppresses repeated messages within a time window."""

    def __init__(
        self,
        time_window: float = 60.0,
        key_field: str = "message",
        max_duplicates: int = 0,
    ) -> None:
        """Initialize deduplication filter.

        Args:
            time_window: Time window in seconds to track duplicates
            key_field: Field to deduplicate on
            max_duplicates: How many duplicates to allow (0 = no duplicates)
        """
        self.time_window = time_window
        self.key_field = key_field
        self.max_duplicates = max_duplicates
        self._seen: dict[str, list[float]] = {}
        self._lock = threading.RLock()

    def filter(self, record: LogRecord) -> bool:
        """Filter duplicate records.

        Args:
            record: Log record to filter

        Returns:
            True if record is not a duplicate
        """
        with self._lock:
            # Get the key
            if self.key_field == "message":
                key = record.message
            elif self.key_field in record.fields:
                key = str(record.fields[self.key_field].value)
            else:
                return True

            now = time.time()

            # Clean up old entries
            if key in self._seen:
                self._seen[key] = [t for t in self._seen[key] if now - t < self.time_window]
            else:
                self._seen[key] = []

            # Check if we've seen this too many times
            if len(self._seen[key]) > self.max_duplicates:
                return False

            # Record this occurrence
            self._seen[key].append(now)
            return True


class ContextFilter(LogFilter):
    """Filter that matches on structured field values."""

    def __init__(
        self,
        field_conditions: dict[str, Any],
        match_all: bool = True,
    ) -> None:
        """Initialize context filter.

        Args:
            field_conditions: Dict of field names to expected values
            match_all: If True, all conditions must match (AND logic)
        """
        self.field_conditions = field_conditions
        self.match_all = match_all

    def filter(self, record: LogRecord) -> bool:
        """Filter by structured field values.

        Args:
            record: Log record to filter

        Returns:
            True if field conditions are met
        """
        results = []
        for field_name, expected_value in self.field_conditions.items():
            if field_name in record.fields:
                actual = record.fields[field_name].value
                results.append(actual == expected_value)
            else:
                results.append(False)

        if self.match_all:
            return all(results) if results else False
        else:
            return any(results)


class CompositeFilter(LogFilter):
    """Filter that combines multiple filters with boolean logic."""

    def __init__(self, operator: str = "AND") -> None:
        """Initialize composite filter.

        Args:
            operator: Logic operator ("AND", "OR", "NOT")
        """
        if operator not in ("AND", "OR", "NOT"):
            raise FilterError(f"Invalid operator: {operator}", "CompositeFilter")
        self.operator = operator
        self.filters: list[LogFilter] = []

    def add_filter(self, filter: LogFilter) -> None:
        """Add a filter to the composite.

        Args:
            filter: Filter to add
        """
        self.filters.append(filter)

    def remove_filter(self, filter: LogFilter) -> None:
        """Remove a filter from the composite.

        Args:
            filter: Filter to remove
        """
        if filter in self.filters:
            self.filters.remove(filter)

    def filter(self, record: LogRecord) -> bool:
        """Filter using composite logic.

        Args:
            record: Log record to filter

        Returns:
            Result of composite filter
        """
        if not self.filters:
            return True

        results = [f.filter(record) for f in self.filters]

        if self.operator == "AND":
            return all(results)
        elif self.operator == "OR":
            return any(results)
        elif self.operator == "NOT":
            return not results[0] if results else True
        return True


class DynamicFilter(LogFilter):
    """Filter with rules that can be updated at runtime."""

    def __init__(self) -> None:
        """Initialize dynamic filter."""
        self.rules: dict[str, Callable[[LogRecord], bool]] = {}
        self._lock = threading.RLock()

    def add_rule(self, name: str, rule_func: Callable[[LogRecord], bool]) -> None:
        """Add a filter rule.

        Args:
            name: Rule name
            rule_func: Callable that evaluates a log record
        """
        with self._lock:
            self.rules[name] = rule_func

    def remove_rule(self, name: str) -> None:
        """Remove a filter rule.

        Args:
            name: Rule name to remove
        """
        with self._lock:
            if name in self.rules:
                del self.rules[name]

    def update_rule(self, name: str, rule_func: Callable[[LogRecord], bool]) -> None:
        """Update an existing rule.

        Args:
            name: Rule name
            rule_func: New callable for the rule
        """
        with self._lock:
            self.rules[name] = rule_func

    def filter(self, record: LogRecord) -> bool:
        """Filter using dynamic rules.

        Args:
            record: Log record to filter

        Returns:
            True if all rules pass
        """
        with self._lock:
            for rule_func in self.rules.values():
                try:
                    if not rule_func(record):
                        return False
                except Exception:  # REVIEWED: broad catch
                    continue
            return True


class LoggerNameFilter(LogFilter):
    """Filter that matches on logger name with wildcard support."""

    def __init__(self, logger_pattern: str) -> None:
        """Initialize logger name filter.

        Args:
            logger_pattern: Pattern like "app.service.*" or exact "app.service.db"
        """
        self.logger_pattern = logger_pattern
        # Convert wildcard pattern to regex
        self.pattern = re.compile("^" + logger_pattern.replace(".", r"\.").replace("*", ".*") + "$")

    def filter(self, record: LogRecord) -> bool:
        """Filter by logger name.

        Args:
            record: Log record to filter

        Returns:
            True if logger name matches pattern
        """
        return bool(self.pattern.match(record.logger_name))


class ExceptionFilter(LogFilter):
    """Filter that matches records with exceptions."""

    def __init__(self, exception_types: list[type] | None = None) -> None:
        """Initialize exception filter.

        Args:
            exception_types: Optional list of exception types to match
        """
        self.exception_types = exception_types

    def filter(self, record: LogRecord) -> bool:
        """Filter records with exceptions.

        Args:
            record: Log record to filter

        Returns:
            True if record has exception (and type matches if specified)
        """
        if not record.exc_info:
            return False

        if self.exception_types:
            exc_type = record.exc_info[0]
            return issubclass(exc_type, tuple(self.exception_types))

        return True
