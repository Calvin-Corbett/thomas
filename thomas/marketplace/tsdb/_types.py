"""Core data types for the Thomas time-series database."""

from dataclasses import dataclass, field
from enum import Enum, auto


class AggregationType(Enum):
    """Supported aggregation functions for time-series data."""

    SUM = auto()
    AVG = auto()
    MIN = auto()
    MAX = auto()
    COUNT = auto()
    PERCENTILE = auto()
    STDDEV = auto()
    RATE = auto()
    DELTA = auto()

    def __str__(self) -> str:
        """Return string representation."""
        return self.name.lower()


class FillPolicy(Enum):
    """Policy for handling missing values in time-series data."""

    NULL = auto()  # Return None for missing intervals
    ZERO = auto()  # Fill with 0
    LINEAR = auto()  # Linear interpolation
    PREVIOUS = auto()  # Last observed value


@dataclass
class DataPoint:
    """Represents a single time-series data point.

    Attributes:
        timestamp: Unix timestamp in milliseconds
        value: Numeric value (int or float)
        tags: Optional dictionary of tag key-value pairs
    """

    timestamp: int
    value: int | float
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate data point after initialization."""
        if self.timestamp < 0:
            raise ValueError("Timestamp must be non-negative")
        if not isinstance(self.value, (int, float)):
            raise ValueError("Value must be numeric")
        if isinstance(self.value, bool):
            raise ValueError("Value cannot be boolean")

    def __lt__(self, other: "DataPoint") -> bool:
        """Enable sorting by timestamp."""
        return self.timestamp < other.timestamp

    def __eq__(self, other: object) -> bool:
        """Check equality by timestamp and value."""
        if not isinstance(other, DataPoint):
            return NotImplemented
        return self.timestamp == other.timestamp and self.value == other.value


@dataclass
class TimeSeries:
    """Represents a complete time-series with metric name and data points.

    Attributes:
        metric_name: Name of the metric
        points: List of DataPoint objects
        tags: Optional tags common to all points
    """

    metric_name: str
    points: list[DataPoint] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate time series after initialization."""
        if not self.metric_name:
            raise ValueError("Metric name cannot be empty")
        if not isinstance(self.points, list):
            raise ValueError("Points must be a list")

    def add_point(self, point: DataPoint) -> None:
        """Add a data point to the series.

        Args:
            point: DataPoint to add

        Raises:
            ValueError: If point is invalid
        """
        if not isinstance(point, DataPoint):
            raise ValueError("Point must be a DataPoint instance")
        self.points.append(point)

    def sort(self) -> None:
        """Sort points by timestamp."""
        self.points.sort()

    @property
    def time_range(self) -> tuple[int, int]:
        """Get the time range of the series.

        Returns:
            Tuple of (min_timestamp, max_timestamp)

        Raises:
            ValueError: If series is empty
        """
        if not self.points:
            raise ValueError("Cannot get time range of empty series")
        timestamps = [p.timestamp for p in self.points]
        return (min(timestamps), max(timestamps))


@dataclass
class TimeRange:
    """Represents a time range for queries.

    Attributes:
        start_time: Start timestamp in milliseconds
        end_time: End timestamp in milliseconds
    """

    start_time: int
    end_time: int

    def __post_init__(self) -> None:
        """Validate time range."""
        if self.start_time < 0:
            raise ValueError("Start time must be non-negative")
        if self.end_time < 0:
            raise ValueError("End time must be non-negative")
        if self.start_time >= self.end_time:
            raise ValueError("Start time must be before end time")

    def contains(self, timestamp: int) -> bool:
        """Check if timestamp is within range.

        Args:
            timestamp: Timestamp to check

        Returns:
            True if timestamp is within [start_time, end_time)
        """
        return self.start_time <= timestamp < self.end_time

    def overlaps(self, other: "TimeRange") -> bool:
        """Check if this range overlaps with another.

        Args:
            other: TimeRange to compare with

        Returns:
            True if ranges overlap
        """
        return not (self.end_time <= other.start_time or self.start_time >= other.end_time)

    @property
    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        return self.end_time - self.start_time


@dataclass
class TagFilter:
    """Represents a filter condition on tag values.

    Attributes:
        key: Tag key to filter on
        operator: Comparison operator (=, !=, >, <, >=, <=, in, not_in, regex)
        value: Filter value(s) - can be string or list for 'in'/'not_in'
    """

    key: str
    operator: str
    value: str | list[str]

    VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "in", "not_in", "regex"}

    def __post_init__(self) -> None:
        """Validate filter after initialization."""
        if not self.key:
            raise ValueError("Tag key cannot be empty")
        if self.operator not in self.VALID_OPERATORS:
            raise ValueError(f"Invalid operator: {self.operator}")
        if self.operator in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError(f"Operator {self.operator} requires list value")

    def matches(self, tag_value: str) -> bool:
        """Check if a tag value matches this filter.

        Args:
            tag_value: The tag value to check

        Returns:
            True if the value matches the filter
        """
        import re

        if self.operator == "=":
            return tag_value == self.value
        elif self.operator == "!=":
            return tag_value != self.value
        elif self.operator == ">":
            return tag_value > str(self.value)
        elif self.operator == "<":
            return tag_value < str(self.value)
        elif self.operator == ">=":
            return tag_value >= str(self.value)
        elif self.operator == "<=":
            return tag_value <= str(self.value)
        elif self.operator == "in":
            return tag_value in self.value  # type: ignore
        elif self.operator == "not_in":
            return tag_value not in self.value  # type: ignore
        elif self.operator == "regex":
            return bool(re.match(str(self.value), tag_value))
        return False


@dataclass
class RetentionPolicy:
    """Defines how long data is retained.

    Attributes:
        name: Name of the policy
        duration_days: How many days to retain (None = infinite)
        max_size_bytes: Maximum size in bytes (None = unlimited)
        metric_patterns: List of metric name patterns this applies to (None = all)
    """

    name: str
    duration_days: int | None = None
    max_size_bytes: int | None = None
    metric_patterns: list[str] | None = None

    def __post_init__(self) -> None:
        """Validate policy."""
        if not self.name:
            raise ValueError("Policy name cannot be empty")
        if self.duration_days is not None and self.duration_days <= 0:
            raise ValueError("Duration must be positive")
        if self.max_size_bytes is not None and self.max_size_bytes <= 0:
            raise ValueError("Max size must be positive")

    def applies_to(self, metric_name: str) -> bool:
        """Check if this policy applies to a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            True if policy applies
        """
        if not self.metric_patterns:
            return True

        import fnmatch

        return any(fnmatch.fnmatch(metric_name, pattern) for pattern in self.metric_patterns)

    def is_expired(self, timestamp: int, now: int) -> bool:
        """Check if a data point is expired.

        Args:
            timestamp: Timestamp of the point in milliseconds
            now: Current time in milliseconds

        Returns:
            True if the point is expired
        """
        if self.duration_days is None:
            return False
        expiry_ms = self.duration_days * 24 * 60 * 60 * 1000
        return (now - timestamp) > expiry_ms


@dataclass
class DownsampleConfig:
    """Configuration for downsampling/rollup rules.

    Attributes:
        interval_minutes: Interval for downsampling in minutes
        aggregations: List of aggregation types to compute
        retention_days: How long to keep downsampled data
    """

    interval_minutes: int
    aggregations: list[AggregationType] = field(default_factory=lambda: [AggregationType.AVG])
    retention_days: int = 90

    def __post_init__(self) -> None:
        """Validate config."""
        if self.interval_minutes <= 0:
            raise ValueError("Interval must be positive")
        if self.retention_days <= 0:
            raise ValueError("Retention must be positive")
        if not self.aggregations:
            raise ValueError("Must specify at least one aggregation")

    @property
    def interval_ms(self) -> int:
        """Get interval in milliseconds."""
        return self.interval_minutes * 60 * 1000


@dataclass
class TSDBConfig:
    """Configuration for the TSDB engine.

    Attributes:
        storage_path: Path to store data on disk
        chunk_size_ms: Size of time chunks in milliseconds
        memory_limit_mb: Maximum in-memory buffer size in MB
        flush_interval_ms: How often to flush to disk
        default_retention: Default retention policy
        downsample_configs: List of downsampling configurations
        compression_enabled: Whether to enable compression
    """

    storage_path: str
    chunk_size_ms: int = 3600000  # 1 hour
    memory_limit_mb: int = 512
    flush_interval_ms: int = 5000
    default_retention: RetentionPolicy | None = None
    downsample_configs: list[DownsampleConfig] = field(default_factory=list)
    compression_enabled: bool = True

    def __post_init__(self) -> None:
        """Validate config."""
        if not self.storage_path:
            raise ValueError("Storage path cannot be empty")
        if self.chunk_size_ms <= 0:
            raise ValueError("Chunk size must be positive")
        if self.memory_limit_mb <= 0:
            raise ValueError("Memory limit must be positive")
        if self.flush_interval_ms <= 0:
            raise ValueError("Flush interval must be positive")

    @property
    def memory_limit_bytes(self) -> int:
        """Get memory limit in bytes."""
        return self.memory_limit_mb * 1024 * 1024
