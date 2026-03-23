"""
Core type definitions for the data pipeline framework.

Defines essential data structures for pipeline configuration, data handling,
transformations, and execution state.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class DataType(Enum):
    """Supported data types in the pipeline."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP = "timestamp"
    BYTES = "bytes"
    ARRAY = "array"
    MAP = "map"
    STRUCT = "struct"
    NULL = "null"
    ANY = "any"


class PipelineState(Enum):
    """Possible states of a pipeline execution."""

    CREATED = "created"
    INITIALIZED = "initialized"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"


class TriggerType(Enum):
    """Types of triggers for stream processing."""

    EVERY_ELEMENT = "every_element"
    PROCESSING_TIME = "processing_time"
    WATERMARK = "watermark"
    COUNT_BASED = "count_based"


class JoinType(Enum):
    """Types of join operations."""

    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"
    CROSS = "cross"


class WindowType(Enum):
    """Types of windows in stream processing."""

    TUMBLING = "tumbling"
    SLIDING = "sliding"
    SESSION = "session"


@dataclass
class Field:
    """Represents a field in a schema."""

    name: str
    data_type: DataType
    nullable: bool = True
    default: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        null_str = "NULL" if self.nullable else "NOT NULL"
        return f"{self.name}: {self.data_type.value} {null_str}"


@dataclass
class Schema:
    """
    Defines the structure of records.

    Maintains a collection of fields and provides validation utilities.
    """

    fields: list[Field]
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_field(self, name: str) -> Field | None:
        """Get a field by name."""
        for field in self.fields:
            if field.name == name:
                return field
        return None

    def field_names(self) -> list[str]:
        """Get all field names."""
        return [f.name for f in self.fields]

    def validate_record(self, record: "Record") -> tuple[bool, list[str]]:
        """
        Validate a record against this schema.

        Args:
            record: Record to validate

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        for field in self.fields:
            if field.name not in record.data:
                if not field.nullable:
                    errors.append(f"Required field '{field.name}' is missing")
            else:
                value = record.data[field.name]
                if value is None and not field.nullable:
                    errors.append(f"Field '{field.name}' cannot be null")

        return len(errors) == 0, errors

    def __repr__(self) -> str:
        fields_str = ", ".join(str(f) for f in self.fields)
        return f"Schema({fields_str})"


@dataclass
class Record:
    """
    Represents a single data record.

    Contains field values and metadata about the record's lineage and timing.
    """

    data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    lineage: dict[str, list[str]] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a field value."""
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a field value."""
        self.data[key] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert record to dictionary."""
        return dict(self.data)

    def __repr__(self) -> str:
        return f"Record({self.data})"


@dataclass
class Watermark:
    """
    Tracks the progress of event time in stream processing.

    Represents the maximum event time that has been processed, allowing
    for late data handling and windowing semantics.
    """

    event_time: datetime
    allowed_lateness: timedelta = field(default_factory=lambda: timedelta(seconds=0))
    update_timestamp: datetime = field(default_factory=datetime.utcnow)

    def is_late(self, event_timestamp: datetime) -> bool:
        """Check if a record is late relative to watermark."""
        cutoff = self.event_time - self.allowed_lateness
        return event_timestamp < cutoff

    def advance(self, new_time: datetime) -> None:
        """Advance watermark to new time."""
        if new_time > self.event_time:
            self.event_time = new_time
            self.update_timestamp = datetime.utcnow()

    def __repr__(self) -> str:
        return f"Watermark({self.event_time}, lateness={self.allowed_lateness})"


@dataclass
class Checkpoint:
    """
    Snapshot of pipeline state for recovery.

    Captures the current processing position, state, and metadata needed
    to resume execution from this point.
    """

    checkpoint_id: str
    pipeline_name: str
    stage_name: str
    offset: int
    processed_count: int
    timestamp: datetime = field(default_factory=datetime.utcnow)
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return (
            f"Checkpoint(id={self.checkpoint_id}, stage={self.stage_name}, "
            f"offset={self.offset}, processed={self.processed_count})"
        )


@dataclass
class Metric:
    """
    Represents a performance or quality metric.

    Tracks numerical measurements with timestamps for monitoring and analysis.
    """

    name: str
    value: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    tags: dict[str, str] = field(default_factory=dict)
    unit: str = "count"
    dimensions: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Metric({self.name}={self.value}{self.unit}, tags={self.tags})"


@dataclass
class Alert:
    """
    Represents an alerting condition or triggered alert.

    Contains threshold information and alert state.
    """

    alert_id: str
    pipeline_name: str
    stage_name: str
    metric_name: str
    threshold: float
    current_value: float
    comparison: str  # "gt", "lt", "eq", "gte", "lte"
    severity: str = "warning"  # "info", "warning", "critical"
    triggered: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message: str = ""

    def is_triggered(self) -> bool:
        """Evaluate if alert should be triggered."""
        if self.comparison == "gt":
            return self.current_value > self.threshold
        elif self.comparison == "lt":
            return self.current_value < self.threshold
        elif self.comparison == "gte":
            return self.current_value >= self.threshold
        elif self.comparison == "lte":
            return self.current_value <= self.threshold
        elif self.comparison == "eq":
            return self.current_value == self.threshold
        return False

    def __repr__(self) -> str:
        status = "TRIGGERED" if self.triggered else "OK"
        return f"Alert({self.alert_id}, {self.metric_name}{self.comparison}" f"{self.threshold}, {status})"


class Transform(ABC):
    """
    Base class for transformations.

    Abstract interface for implementing record transformations.
    """

    @abstractmethod
    def transform(self, record: Record) -> Record | list[Record]:
        """
        Apply transformation to a record.

        Args:
            record: Input record

        Returns:
            Transformed record(s). Can return single record or list of records
        """
        pass

    @abstractmethod
    def get_output_schema(self, input_schema: Schema) -> Schema:
        """
        Determine output schema for given input schema.

        Args:
            input_schema: Schema of input records

        Returns:
            Schema of output records
        """
        pass


class Filter(ABC):
    """
    Base class for filter predicates.

    Abstract interface for implementing record filtering logic.
    """

    @abstractmethod
    def matches(self, record: Record) -> bool:
        """
        Evaluate if a record matches the filter.

        Args:
            record: Record to evaluate

        Returns:
            True if record matches the filter
        """
        pass


class Aggregation(ABC):
    """
    Base class for aggregation operations.

    Implements stateful aggregation logic.
    """

    @abstractmethod
    def add(self, record: Record) -> None:
        """Add a record to the aggregation."""
        pass

    @abstractmethod
    def get_result(self) -> Record:
        """Get the aggregation result as a record."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the aggregation state."""
        pass


@dataclass
class JoinSpec:
    """
    Specification for join operations.

    Defines how two data streams or batches should be joined.
    """

    left_key: str | list[str]
    right_key: str | list[str]
    join_type: JoinType = JoinType.INNER
    left_suffix: str = "_left"
    right_suffix: str = "_right"
    condition: Callable[[Record, Record], bool] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.left_key, str):
            self.left_key = [self.left_key]
        if isinstance(self.right_key, str):
            self.right_key = [self.right_key]


@dataclass
class WindowSpec:
    """
    Specification for windowing in stream processing.

    Defines window type, size, and slide parameters.
    """

    window_type: WindowType
    window_duration: timedelta
    slide_duration: timedelta | None = None
    timeout: timedelta | None = None

    @property
    def is_tumbling(self) -> bool:
        """Check if this is a tumbling window."""
        return self.window_type == WindowType.TUMBLING

    @property
    def is_sliding(self) -> bool:
        """Check if this is a sliding window."""
        return self.window_type == WindowType.SLIDING

    @property
    def is_session(self) -> bool:
        """Check if this is a session window."""
        return self.window_type == WindowType.SESSION

    def __repr__(self) -> str:
        if self.window_type == WindowType.TUMBLING:
            return f"TumblingWindow({self.window_duration})"
        elif self.window_type == WindowType.SLIDING:
            return f"SlidingWindow({self.window_duration}, {self.slide_duration})"
        else:
            return f"SessionWindow({self.timeout})"


class DataSource(ABC):
    """
    Base class for data sources.

    Abstract interface for implementing data sources.
    """

    @abstractmethod
    def read(self) -> list[Record]:
        """Read records from source."""
        pass

    @abstractmethod
    def get_schema(self) -> Schema:
        """Get schema of data from this source."""
        pass

    @abstractmethod
    def supports_streaming(self) -> bool:
        """Check if source supports streaming reads."""
        pass


class DataSink(ABC):
    """
    Base class for data sinks.

    Abstract interface for implementing data sinks.
    """

    @abstractmethod
    def write(self, record: Record) -> None:
        """Write a single record to sink."""
        pass

    @abstractmethod
    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to sink."""
        pass

    @abstractmethod
    def flush(self) -> None:
        """Flush any buffered data."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the sink."""
        pass


@dataclass
class Stage:
    """
    Represents a stage in a data pipeline.

    A stage consists of a source, optional transformations, and a sink.
    """

    name: str
    source: DataSource
    sink: DataSink
    transforms: list[Transform] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    partition_by: list[str] | None = None
    parallelism: int = 1
    checkpoint_interval: int = 1000
    timeout: timedelta | None = None
    retry_policy: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Stage({self.name}, {len(self.transforms)} transforms)"


@dataclass
class PipelineConfig:
    """
    Configuration for a data pipeline.

    Specifies pipeline-level settings and metadata.
    """

    name: str
    description: str = ""
    stages: list[Stage] = field(default_factory=list)
    max_parallelism: int = 4
    default_timeout: timedelta = field(default_factory=lambda: timedelta(hours=1))
    enable_checkpointing: bool = True
    checkpoint_interval: int = 1000
    enable_metrics: bool = True
    enable_lineage: bool = True
    dry_run: bool = False
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    owner: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_stage(self, stage: Stage) -> None:
        """Add a stage to the pipeline."""
        self.stages.append(stage)

    def get_stage(self, name: str) -> Stage | None:
        """Get a stage by name."""
        for stage in self.stages:
            if stage.name == name:
                return stage
        return None

    def stage_names(self) -> list[str]:
        """Get all stage names in execution order."""
        return [s.name for s in self.stages]

    def __repr__(self) -> str:
        return f"PipelineConfig({self.name}, {len(self.stages)} stages, " f"parallelism={self.max_parallelism})"
