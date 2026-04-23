"""Core type definitions for the logging framework."""

import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Protocol,
)

if TYPE_CHECKING:
    from .logger import Logger


class LogLevel(IntEnum):
    """Log level enumeration with numeric values for comparison."""

    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    def __str__(self) -> str:
        """String representation of log level."""
        return self.name

    @classmethod
    def from_string(cls, value: str) -> "LogLevel":
        """Convert string to LogLevel.

        Args:
            value: Level name (case-insensitive)

        Returns:
            LogLevel enum value

        Raises:
            ValueError: If level name is invalid
        """
        try:
            return cls[value.upper()]
        except KeyError:
            valid = ", ".join([l.name for l in cls])
            raise ValueError(f"Invalid log level '{value}'. Valid: {valid}")


@dataclass
class StructuredField:
    """Represents a structured field in a log record."""

    name: str
    value: Any
    is_pii: bool = False
    is_redacted: bool = False
    value_type: str = field(default_factory=lambda: "unknown")

    def __post_init__(self) -> None:
        """Infer value type after initialization."""
        if self.value_type == "unknown":
            self.value_type = type(self.value).__name__

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return asdict(self)


@dataclass
class TraceContext:
    """Distributed trace context for cross-service correlation."""

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    sampled: bool = True

    @classmethod
    def create(
        cls,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> "TraceContext":
        """Create a new trace context."""
        return cls(
            trace_id=trace_id or str(uuid.uuid4()),
            span_id=span_id or str(uuid.uuid4()),
        )

    def to_headers(self) -> dict[str, str]:
        """Convert to HTTP headers for propagation."""
        return {
            "X-Trace-Id": self.trace_id,
            "X-Span-Id": self.span_id,
            "X-Parent-Span-Id": self.parent_span_id or "",
            "X-Sampled": str(self.sampled).lower(),
        }

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> Optional["TraceContext"]:
        """Parse trace context from HTTP headers."""
        trace_id = headers.get("X-Trace-Id")
        span_id = headers.get("X-Span-Id")
        if not trace_id or not span_id:
            return None
        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=headers.get("X-Parent-Span-Id") or None,
            sampled=headers.get("X-Sampled", "true").lower() == "true",
        )


@dataclass
class CorrelationId:
    """Request correlation identifier."""

    request_id: str
    session_id: str | None = None
    user_id: str | None = None

    @classmethod
    def create(cls) -> "CorrelationId":
        """Create a new correlation ID."""
        return cls(request_id=str(uuid.uuid4()))


@dataclass
class LogRecord:
    """Immutable log record containing all log information."""

    timestamp: datetime
    level: LogLevel
    logger_name: str
    message: str
    fields: dict[str, StructuredField] = field(default_factory=dict)
    exception: BaseException | None = None
    exc_info: tuple[Any, Any, Any] | None = None
    caller_frame: str | None = None
    caller_line: int | None = None
    caller_function: str | None = None
    thread_id: int = field(default_factory=threading.get_ident)
    thread_name: str = field(default_factory=threading.current_thread().getName)
    process_id: int = field(default_factory=lambda: __import__("os").getpid())
    trace_context: TraceContext | None = None
    correlation_id: CorrelationId | None = None
    context_data: dict[str, Any] = field(default_factory=dict)

    def get_field(self, name: str) -> StructuredField | None:
        """Get a structured field by name."""
        return self.fields.get(name)

    def get_field_value(self, name: str) -> Any:
        """Get the value of a structured field."""
        field = self.fields.get(name)
        return field.value if field else None

    def to_dict(self) -> dict[str, Any]:
        """Convert log record to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.name,
            "logger": self.logger_name,
            "message": self.message,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "thread_id": self.thread_id,
            "thread_name": self.thread_name,
            "process_id": self.process_id,
            "caller": {
                "file": self.caller_frame,
                "line": self.caller_line,
                "function": self.caller_function,
            }
            if self.caller_frame
            else None,
        }


@dataclass
class LogContext:
    """Contextual information for a logger."""

    parent_logger: Optional["Logger"] = None
    level: LogLevel = LogLevel.INFO
    handlers: list["LogHandler"] = field(default_factory=list)
    filters: list["LogFilter"] = field(default_factory=list)
    propagate: bool = True
    structured_fields: dict[str, Any] = field(default_factory=dict)
    trace_context: TraceContext | None = None
    correlation_id: CorrelationId | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    def add_field(self, name: str, value: Any, is_pii: bool = False) -> None:
        """Add a structured field to the context."""
        with self.lock:
            self.structured_fields[name] = {
                "value": value,
                "is_pii": is_pii,
            }

    def get_fields(self) -> dict[str, Any]:
        """Get all structured fields."""
        with self.lock:
            return dict(self.structured_fields)

    def clear_fields(self) -> None:
        """Clear all structured fields."""
        with self.lock:
            self.structured_fields.clear()


class LogHandler(ABC):
    """Abstract base class for log handlers."""

    def __init__(
        self,
        level: LogLevel = LogLevel.DEBUG,
        formatter: Optional["LogFormatter"] = None,
    ) -> None:
        """Initialize handler.

        Args:
            level: Minimum log level to handle
            formatter: Optional formatter for log records
        """
        self.level = level
        self.formatter = formatter
        self.filters: list[LogFilter] = []

    def add_filter(self, filter: "LogFilter") -> None:
        """Add a filter to the handler."""
        self.filters.append(filter)

    def remove_filter(self, filter: "LogFilter") -> None:
        """Remove a filter from the handler."""
        if filter in self.filters:
            self.filters.remove(filter)

    def should_handle(self, record: LogRecord) -> bool:
        """Determine if handler should process the record.

        Args:
            record: Log record to evaluate

        Returns:
            True if record should be handled
        """
        if record.level < self.level:
            return False
        for f in self.filters:
            if not f.filter(record):
                return False
        return True

    @abstractmethod
    def emit(self, record: LogRecord) -> None:
        """Emit a log record.

        Args:
            record: Log record to emit
        """
        pass

    def handle(self, record: LogRecord) -> None:
        """Handle a log record if applicable.

        Args:
            record: Log record to handle
        """
        if self.should_handle(record):
            try:
                self.emit(record)
            except Exception:  # REVIEWED: broad catch
                self.handle_error(record)

    def handle_error(self, record: LogRecord) -> None:
        """Handle an error during emit.

        Args:
            record: Log record that caused error
        """
        pass


class LogFilter(ABC):
    """Abstract base class for log filters."""

    @abstractmethod
    def filter(self, record: LogRecord) -> bool:
        """Determine if record should be processed.

        Args:
            record: Log record to filter

        Returns:
            True if record should pass filter
        """
        pass


class LogFormatter(ABC):
    """Abstract base class for log formatters."""

    @abstractmethod
    def format(self, record: LogRecord) -> str:
        """Format a log record.

        Args:
            record: Log record to format

        Returns:
            Formatted log string
        """
        pass

    def format_exception(self, exc_info: tuple[Any, Any, Any]) -> str:
        """Format exception traceback.

        Args:
            exc_info: Exception info tuple (type, value, traceback)

        Returns:
            Formatted exception string
        """
        import traceback

        return "".join(traceback.format_exception(*exc_info))


class LogSink(Protocol):
    """Protocol for log sinks (destinations)."""

    def write(self, data: str) -> None:
        """Write data to sink.

        Args:
            data: Data to write
        """
        ...

    def flush(self) -> None:
        """Flush any buffered data."""
        ...

    def close(self) -> None:
        """Close the sink."""
        ...


@dataclass
class RotationPolicy:
    """Policy for log file rotation."""

    rotation_type: str  # "size", "time", "both"
    max_size: int | None = None  # bytes
    max_count: int | None = None  # max rotated files
    time_interval: str | None = None  # "daily", "hourly"
    backup_count: int = 5

    def should_rotate(
        self,
        current_size: int,
        last_rotation_time: datetime,
    ) -> bool:
        """Determine if rotation should occur.

        Args:
            current_size: Current file size in bytes
            last_rotation_time: Time of last rotation

        Returns:
            True if rotation is needed
        """
        if self.rotation_type in ("size", "both"):
            if self.max_size and current_size >= self.max_size:
                return True

        if self.rotation_type in ("time", "both"):
            if self.time_interval == "daily":
                if (datetime.now() - last_rotation_time).days > 0:
                    return True
            elif self.time_interval == "hourly":
                if (datetime.now() - last_rotation_time).seconds > 3600:
                    return True

        return False


@dataclass
class RetentionPolicy:
    """Policy for log retention and cleanup."""

    retention_days: int = 30
    retention_size: int | None = None  # bytes
    archive_after_days: int | None = None
    archive_path: str | None = None
    delete_archived_after_days: int | None = None
    compression_type: str = "gzip"  # "gzip", "bzip2", "lzma", "none"

    def is_expired(self, file_modification_time: datetime) -> bool:
        """Check if a log file is expired.

        Args:
            file_modification_time: File modification timestamp

        Returns:
            True if file has exceeded retention period
        """
        age_days = (datetime.now() - file_modification_time).days
        return age_days >= self.retention_days


@dataclass
class SamplingPolicy:
    """Policy for log sampling (rate limiting)."""

    sample_rate: float = 1.0  # 0.0 to 1.0
    sample_by: str | None = None  # "trace_id", "message", "level"
    per_logger_rates: dict[str, float] = field(default_factory=dict)
    initial_count: int = 10  # Log first N before sampling
    burst_size: int = 100  # Allow N logs in a burst

    def should_sample(self, record: LogRecord, count: int = 0) -> bool:
        """Determine if a record should be sampled.

        Args:
            record: Log record to evaluate
            count: Current count for token bucket

        Returns:
            True if record should be logged
        """
        if count < self.initial_count:
            return True
        return __import__("random").random() < self.sample_rate


@dataclass
class LogQuery:
    """Query specification for log search."""

    text_search: str | None = None
    level_min: LogLevel = LogLevel.DEBUG
    level_max: LogLevel = LogLevel.CRITICAL
    logger_name: str | None = None
    time_range: tuple[datetime, datetime] | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    request_id: str | None = None
    limit: int = 1000
    offset: int = 0

    def matches(self, record: LogRecord) -> bool:
        """Check if a record matches this query.

        Args:
            record: Log record to evaluate

        Returns:
            True if record matches query
        """
        if self.text_search:
            if self.text_search.lower() not in record.message.lower():
                return False

        if record.level < self.level_min or record.level > self.level_max:
            return False

        if self.logger_name and self.logger_name not in record.logger_name:
            return False

        if self.time_range:
            start, end = self.time_range
            if not (start <= record.timestamp <= end):
                return False

        if self.trace_id and record.trace_context:
            if self.trace_id != record.trace_context.trace_id:
                return False

        if self.request_id and record.correlation_id:
            if self.request_id != record.correlation_id.request_id:
                return False

        for key, value in self.fields.items():
            if key not in record.fields:
                return False
            if record.fields[key].value != value:
                return False

        return True


@dataclass
class LogAggregation:
    """Result of log aggregation operation."""

    group_by: list[str]
    groups: dict[str, int] = field(default_factory=dict)
    total_count: int = 0
    time_buckets: dict[str, int] = field(default_factory=dict)
    error_rate: float = 0.0
    top_messages: list[tuple[str, int]] = field(default_factory=list)

    def add_group(self, key: str) -> None:
        """Increment count for a group."""
        self.groups[key] = self.groups.get(key, 0) + 1
        self.total_count += 1

    def add_time_bucket(self, bucket_key: str) -> None:
        """Increment count for a time bucket."""
        self.time_buckets[bucket_key] = self.time_buckets.get(bucket_key, 0) + 1
