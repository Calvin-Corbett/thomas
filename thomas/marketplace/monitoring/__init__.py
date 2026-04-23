"""
Thomas monitoring and observability platform.

A comprehensive infrastructure monitoring system with metrics, alerting,
health checks, tracing, and anomaly detection.
"""

from thomas.marketplace.monitoring._exceptions import (
    AlertError,
    AnomalyError,
    HealthCheckError,
    MetricError,
    MonitoringError,
    QueryError,
    StorageError,
    TracingError,
)
from thomas.marketplace.monitoring._types import (
    AggregationType,
    Alert,
    AlertRule,
    AlertState,
    Annotation,
    Check,
    CheckResult,
    CheckStatus,
    Dashboard,
    Label,
    Metric,
    MetricSample,
    MetricType,
    Panel,
    Percentile,
    Query,
    ScrapeTarget,
    Threshold,
    TimeSeries,
)
from thomas.marketplace.monitoring.alerting import AlertGroup, AlertManager
from thomas.marketplace.monitoring.anomaly import Anomaly, AnomalyDetector
from thomas.marketplace.monitoring.collection import MetricCollector, ScrapeJob
from thomas.marketplace.monitoring.dashboards import DashboardEngine
from thomas.marketplace.monitoring.health import HealthChecker, HealthStatus
from thomas.marketplace.monitoring.metrics import Counter, Gauge, Histogram, MetricsRegistry, Summary
from thomas.marketplace.monitoring.query_engine import InstantResult, QueryEngine, RangeResult
from thomas.marketplace.monitoring.storage import Chunk, DownsamplePolicy, TimeSeriesDB
from thomas.marketplace.monitoring.tracing import Span, Trace, TracingCollector

__all__ = [
    "MetricType",
    "Metric",
    "MetricSample",
    "Label",
    "TimeSeries",
    "Alert",
    "AlertRule",
    "AlertState",
    "Check",
    "CheckResult",
    "CheckStatus",
    "Dashboard",
    "Panel",
    "Query",
    "Threshold",
    "AggregationType",
    "Percentile",
    "ScrapeTarget",
    "Annotation",
    "MonitoringError",
    "MetricError",
    "AlertError",
    "StorageError",
    "QueryError",
    "HealthCheckError",
    "AnomalyError",
    "TracingError",
    "MetricsRegistry",
    "Counter",
    "Gauge",
    "Histogram",
    "Summary",
    "MetricCollector",
    "ScrapeJob",
    "TimeSeriesDB",
    "Chunk",
    "DownsamplePolicy",
    "QueryEngine",
    "InstantResult",
    "RangeResult",
    "AlertManager",
    "AlertGroup",
    "DashboardEngine",
    "HealthChecker",
    "HealthStatus",
    "AnomalyDetector",
    "Anomaly",
    "TracingCollector",
    "Span",
    "Trace",
]

__version__ = "0.1.0"
