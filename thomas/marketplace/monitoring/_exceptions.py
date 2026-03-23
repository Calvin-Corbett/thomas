"""
Exceptions for the monitoring module.
"""


class MonitoringError(Exception):
    """Base exception for all monitoring-related errors."""

    pass


class MetricError(MonitoringError):
    """Raised when metric operations fail."""

    pass


class AlertError(MonitoringError):
    """Raised when alert operations fail."""

    pass


class StorageError(MonitoringError):
    """Raised when storage operations fail."""

    pass


class QueryError(MonitoringError):
    """Raised when query operations fail."""

    pass


class HealthCheckError(MonitoringError):
    """Raised when health check operations fail."""

    pass


class AnomalyError(MonitoringError):
    """Raised when anomaly detection operations fail."""

    pass


class TracingError(MonitoringError):
    """Raised when tracing operations fail."""

    pass


class SeriesNotFoundError(StorageError):
    """Raised when a requested time series is not found."""

    pass


class InvalidQueryError(QueryError):
    """Raised when a query is invalid."""

    pass


class AlertRuleViolationError(AlertError):
    """Raised when an alert rule constraint is violated."""

    pass


class CardinityExceededError(MetricError):
    """Raised when metric cardinality exceeds limits."""

    pass


class ChunkNotFoundError(StorageError):
    """Raised when a chunk is not found."""

    pass


class SampleRejectedError(MetricError):
    """Raised when a metric sample is rejected."""

    pass
