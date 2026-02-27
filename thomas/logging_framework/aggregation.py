"""Log aggregation and analysis utilities."""

import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from thomas.logging_framework._types import LogAggregation, LogLevel, LogRecord


class LogGrouper:
    """Groups log records by field values."""

    def __init__(self, group_by: list[str]) -> None:
        """Initialize log grouper.

        Args:
            group_by: List of field names to group by
        """
        self.group_by = group_by
        self.groups: dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record to grouping.

        Args:
            record: Log record to group
        """
        with self._lock:
            # Build composite key from specified fields
            key_parts = []
            for field_name in self.group_by:
                if field_name == "level":
                    key_parts.append(record.level.name)
                elif field_name == "logger":
                    key_parts.append(record.logger_name)
                elif field_name in record.fields:
                    key_parts.append(str(record.fields[field_name].value))
                else:
                    key_parts.append("unknown")

            key = "|".join(key_parts)
            self.groups[key] += 1

    def get_results(self) -> LogAggregation:
        """Get aggregation results.

        Returns:
            LogAggregation with grouped results
        """
        with self._lock:
            result = LogAggregation(group_by=self.group_by)
            result.groups = dict(self.groups)
            result.total_count = sum(self.groups.values())
            return result


class TimeWindowAggregator:
    """Aggregates logs into time windows."""

    def __init__(self, window_size_seconds: int = 60) -> None:
        """Initialize time window aggregator.

        Args:
            window_size_seconds: Size of time window in seconds
        """
        self.window_size = timedelta(seconds=window_size_seconds)
        self.time_buckets: dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record to aggregation.

        Args:
            record: Log record to add
        """
        with self._lock:
            # Create time bucket key
            bucket_time = record.timestamp.replace(second=0, microsecond=0) + timedelta(
                seconds=record.timestamp.second // 60 * 60
            )
            bucket_key = bucket_time.isoformat()
            self.time_buckets[bucket_key] += 1

    def get_results(self) -> dict[str, int]:
        """Get time bucket results.

        Returns:
            Dict mapping bucket times to counts
        """
        with self._lock:
            return dict(self.time_buckets)


class PatternExtractor:
    """Extracts common patterns from log messages."""

    def __init__(self, min_occurrences: int = 5) -> None:
        """Initialize pattern extractor.

        Args:
            min_occurrences: Minimum occurrences to consider a pattern
        """
        self.min_occurrences = min_occurrences
        self.message_counter: Counter = Counter()
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record for pattern analysis.

        Args:
            record: Log record to analyze
        """
        with self._lock:
            # Generalize the message by replacing numbers and hashes
            pattern = self._generalize_message(record.message)
            self.message_counter[pattern] += 1

    @staticmethod
    def _generalize_message(message: str) -> str:
        """Generalize a message by replacing variable parts.

        Args:
            message: Original message

        Returns:
            Generalized pattern
        """
        # Replace numbers with #NUM#
        pattern = re.sub(r"\d+", "#NUM#", message)
        # Replace UUIDs with #UUID#
        pattern = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "#UUID#",
            pattern,
            flags=re.IGNORECASE,
        )
        # Replace IP addresses with #IP#
        pattern = re.sub(
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            "#IP#",
            pattern,
        )
        return pattern

    def get_patterns(self) -> list[tuple[str, int]]:
        """Get extracted patterns sorted by frequency.

        Returns:
            List of (pattern, count) tuples
        """
        with self._lock:
            return [
                (pattern, count)
                for pattern, count in self.message_counter.most_common()
                if count >= self.min_occurrences
            ]


class ErrorRateCalculator:
    """Calculates error rates from log records."""

    def __init__(self, window_seconds: int = 300) -> None:
        """Initialize error rate calculator.

        Args:
            window_seconds: Time window for rate calculation
        """
        self.window = timedelta(seconds=window_seconds)
        self.records: list[LogRecord] = []
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record for error rate calculation.

        Args:
            record: Log record to add
        """
        with self._lock:
            self.records.append(record)
            # Clean up old records outside window
            cutoff = datetime.now() - self.window
            self.records = [r for r in self.records if r.timestamp > cutoff]

    def get_error_rate(self) -> float:
        """Get current error rate (0.0 to 1.0).

        Returns:
            Fraction of logs that are errors or above
        """
        with self._lock:
            if not self.records:
                return 0.0
            error_count = sum(1 for r in self.records if r.level >= LogLevel.ERROR)
            return error_count / len(self.records)

    def get_log_counts(self) -> dict[LogLevel, int]:
        """Get counts of logs by level.

        Returns:
            Dict mapping levels to counts
        """
        with self._lock:
            counts = defaultdict(int)
            for record in self.records:
                counts[record.level] += 1
            return dict(counts)


class TopErrorsFinder:
    """Finds the most common error messages."""

    def __init__(self, top_n: int = 10) -> None:
        """Initialize top errors finder.

        Args:
            top_n: Number of top errors to track
        """
        self.top_n = top_n
        self.error_messages: Counter = Counter()
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record.

        Args:
            record: Log record to analyze
        """
        if record.level >= LogLevel.ERROR:
            with self._lock:
                self.error_messages[record.message] += 1

    def get_top_errors(self) -> list[tuple[str, int]]:
        """Get top error messages.

        Returns:
            List of (message, count) tuples
        """
        with self._lock:
            return self.error_messages.most_common(self.top_n)


class TrendDetector:
    """Detects trends in log metrics."""

    def __init__(self, window_size: int = 10) -> None:
        """Initialize trend detector.

        Args:
            window_size: Number of data points for trend detection
        """
        self.window_size = window_size
        self.error_rate_history: list[float] = []
        self.volume_history: list[int] = []
        self._lock = threading.RLock()

    def add_metric(self, error_rate: float, log_volume: int) -> None:
        """Add a metric snapshot.

        Args:
            error_rate: Current error rate
            log_volume: Number of logs
        """
        with self._lock:
            self.error_rate_history.append(error_rate)
            self.volume_history.append(log_volume)
            # Keep only recent history
            if len(self.error_rate_history) > self.window_size:
                self.error_rate_history = self.error_rate_history[-self.window_size :]
                self.volume_history = self.volume_history[-self.window_size :]

    def get_error_rate_trend(self) -> str | None:
        """Detect trend in error rate.

        Returns:
            "increasing", "decreasing", "stable", or None
        """
        with self._lock:
            if len(self.error_rate_history) < 3:
                return None

            recent = self.error_rate_history[-3:]
            avg_first_half = sum(recent[:2]) / 2
            avg_second_half = recent[-1]

            if avg_second_half > avg_first_half * 1.1:
                return "increasing"
            elif avg_second_half < avg_first_half * 0.9:
                return "decreasing"
            else:
                return "stable"

    def get_volume_trend(self) -> str | None:
        """Detect trend in log volume.

        Returns:
            "increasing", "decreasing", "stable", or None
        """
        with self._lock:
            if len(self.volume_history) < 3:
                return None

            recent = self.volume_history[-3:]
            avg_first_half = sum(recent[:2]) / 2
            avg_second_half = recent[-1]

            if avg_second_half > avg_first_half * 1.1:
                return "increasing"
            elif avg_second_half < avg_first_half * 0.9:
                return "decreasing"
            else:
                return "stable"


class LogMetricsConverter:
    """Converts log data to metrics (counters, histograms)."""

    def __init__(self) -> None:
        """Initialize metrics converter."""
        self.level_counters: dict[LogLevel, int] = defaultdict(int)
        self.logger_counters: dict[str, int] = defaultdict(int)
        self.duration_values: list[float] = []
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record to metrics.

        Args:
            record: Log record to add
        """
        with self._lock:
            self.level_counters[record.level] += 1
            self.logger_counters[record.logger_name] += 1

            # Extract duration if present in fields
            if "duration" in record.fields:
                try:
                    duration = float(record.fields["duration"].value)
                    self.duration_values.append(duration)
                except (ValueError, TypeError):
                    pass

    def get_level_metrics(self) -> dict[str, int]:
        """Get counters by level.

        Returns:
            Dict mapping level names to counts
        """
        with self._lock:
            return {level.name: count for level, count in self.level_counters.items()}

    def get_logger_metrics(self) -> dict[str, int]:
        """Get counters by logger.

        Returns:
            Dict mapping logger names to counts
        """
        with self._lock:
            return dict(self.logger_counters)

    def get_duration_stats(self) -> dict[str, float]:
        """Get statistics on durations.

        Returns:
            Dict with min, max, avg, median
        """
        with self._lock:
            if not self.duration_values:
                return {}

            sorted_durations = sorted(self.duration_values)
            return {
                "min": min(sorted_durations),
                "max": max(sorted_durations),
                "avg": sum(sorted_durations) / len(sorted_durations),
                "median": sorted_durations[len(sorted_durations) // 2],
            }


class AlertingRule:
    """Rule for generating alerts based on log metrics."""

    def __init__(
        self,
        name: str,
        condition: callable,
        severity: str = "warning",
    ) -> None:
        """Initialize alerting rule.

        Args:
            name: Rule name
            condition: Callable that evaluates condition on aggregated data
            severity: Alert severity ("info", "warning", "critical")
        """
        self.name = name
        self.condition = condition
        self.severity = severity
        self.last_triggered: datetime | None = None

    def evaluate(self, aggregation: LogAggregation) -> bool:
        """Evaluate if alert should trigger.

        Args:
            aggregation: Aggregated log data

        Returns:
            True if condition is met
        """
        try:
            return self.condition(aggregation)
        except Exception:  # REVIEWED: broad catch
            return False


class AlertManager:
    """Manages alerting rules and triggered alerts."""

    def __init__(self) -> None:
        """Initialize alert manager."""
        self.rules: dict[str, AlertingRule] = {}
        self.triggered_alerts: list[tuple[str, datetime]] = []
        self._lock = threading.RLock()

    def add_rule(self, rule: AlertingRule) -> None:
        """Add an alerting rule.

        Args:
            rule: AlertingRule to add
        """
        with self._lock:
            self.rules[rule.name] = rule

    def evaluate_all(self, aggregation: LogAggregation) -> list[str]:
        """Evaluate all rules and return triggered alerts.

        Args:
            aggregation: Log aggregation to evaluate

        Returns:
            List of triggered alert names
        """
        triggered = []
        with self._lock:
            for rule_name, rule in self.rules.items():
                if rule.evaluate(aggregation):
                    triggered.append(rule_name)
                    self.triggered_alerts.append((rule_name, datetime.now()))

        return triggered

    def get_recent_alerts(self, minutes: int = 5) -> list[str]:
        """Get recently triggered alerts.

        Args:
            minutes: How far back to look

        Returns:
            List of alert names triggered in time window
        """
        with self._lock:
            cutoff = datetime.now() - timedelta(minutes=minutes)
            recent = [alert_name for alert_name, trigger_time in self.triggered_alerts if trigger_time > cutoff]
            return recent
