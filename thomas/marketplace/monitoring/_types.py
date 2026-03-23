"""
Core type definitions for the monitoring system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class MetricType(Enum):
    """Types of metrics supported by the system."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AggregationType(Enum):
    """Aggregation operations for time series data."""

    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    STDDEV = "stddev"
    MEDIAN = "median"


class AlertState(Enum):
    """State of an alert."""

    PENDING = "pending"
    FIRING = "firing"
    RESOLVED = "resolved"
    INHIBITED = "inhibited"


class CheckStatus(Enum):
    """Status of a health check."""

    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"
    FLAPPING = "flapping"


@dataclass(frozen=True)
class Label:
    """A label key-value pair for metrics."""

    name: str
    value: str

    def __hash__(self) -> int:
        return hash((self.name, self.value))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Label):
            return NotImplemented
        return self.name == other.name and self.value == other.value


@dataclass(frozen=True)
class Percentile:
    """A percentile value for summary metrics."""

    quantile: float
    value: float

    def __post_init__(self) -> None:
        if not 0 <= self.quantile <= 1:
            raise ValueError(f"Quantile must be between 0 and 1, got {self.quantile}")


@dataclass
class MetricSample:
    """A single sample of a metric at a point in time."""

    timestamp: float
    value: float
    exemplar_labels: dict[str, str] | None = None
    trace_id: str | None = None

    def __lt__(self, other: "MetricSample") -> bool:
        return self.timestamp < other.timestamp


@dataclass
class Metric:
    """A metric with name, type, labels, and documentation."""

    name: str
    type: MetricType
    help: str
    unit: str = ""
    labels: list[Label] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash((self.name, self.type, tuple(self.labels)))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Metric):
            return NotImplemented
        return self.name == other.name and self.type == other.type and self.labels == other.labels


@dataclass
class TimeSeries:
    """A time series of metric samples with associated metadata."""

    metric: Metric
    labels: list[Label]
    samples: list[MetricSample] = field(default_factory=list)
    last_update: float | None = None

    def add_sample(self, sample: MetricSample) -> None:
        """Add a sample to the time series."""
        self.samples.append(sample)
        self.samples.sort()
        self.last_update = sample.timestamp

    def samples_in_range(self, start: float, end: float) -> list[MetricSample]:
        """Get all samples within a time range."""
        return [s for s in self.samples if start <= s.timestamp <= end]


@dataclass
class Threshold:
    """A threshold value for alerting or visualization."""

    value: float
    severity: str = "warning"  # warning, critical
    description: str = ""


@dataclass
class AlertRule:
    """A rule that fires alerts based on metric data."""

    name: str
    expr: str  # PromQL expression
    duration: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    severity: str = "warning"
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Alert:
    """An alert instance fired from an alert rule."""

    rule: AlertRule
    state: AlertState
    value: float
    firing_at: datetime | None = None
    resolved_at: datetime | None = None
    pending_since: datetime | None = None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""

    def __hash__(self) -> int:
        return hash(self.fingerprint)


@dataclass
class Check:
    """A health check definition."""

    name: str
    check_type: str  # http, tcp, process, disk, custom
    interval: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    timeout: timedelta = field(default_factory=lambda: timedelta(seconds=5))
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class CheckResult:
    """Result of a health check execution."""

    check: Check
    status: CheckStatus
    timestamp: datetime = field(default_factory=datetime.utcnow)
    response_time: float | None = None  # milliseconds
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Query:
    """A monitoring query (PromQL or similar)."""

    expr: str
    start: float | None = None
    end: float | None = None
    step: float | None = None
    timeout: float = 30.0


@dataclass
class Panel:
    """A dashboard panel displaying metric data."""

    id: str
    title: str
    panel_type: str  # graph, stat, table, heatmap, gauge
    query: Query
    interval: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    thresholds: list[Threshold] = field(default_factory=list)
    unit: str = ""
    min_value: float | None = None
    max_value: float | None = None
    decimals: int = 2
    legend_visible: bool = True
    repeat_by: str | None = None  # repeat panel for each label value


@dataclass
class Dashboard:
    """A monitoring dashboard with panels."""

    id: str
    title: str
    description: str = ""
    panels: list[Panel] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    time_range: tuple[str, str] = ("now-6h", "now")
    refresh_interval: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1
    tags: list[str] = field(default_factory=list)


@dataclass
class ScrapeTarget:
    """A target for metric scraping."""

    job_name: str
    address: str
    port: int = 9090
    scheme: str = "http"
    path: str = "/metrics"
    interval: timedelta = field(default_factory=lambda: timedelta(seconds=15))
    timeout: timedelta = field(default_factory=lambda: timedelta(seconds=10))
    labels: dict[str, str] = field(default_factory=dict)
    relabel_rules: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True


@dataclass
class Annotation:
    """An annotation marking important events on a dashboard."""

    timestamp: datetime
    title: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    severity: str = "info"  # info, warning, critical
    dashboard_id: str | None = None
