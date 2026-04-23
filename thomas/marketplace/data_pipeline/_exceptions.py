"""
Exception classes for the data pipeline framework.

Defines custom exceptions for various error conditions.
"""


class PipelineException(Exception):
    """Base exception for all pipeline-related errors."""

    def __init__(self, message: str, error_code: str = "PIPELINE_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


class ConfigurationError(PipelineException):
    """Raised when pipeline configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "CONFIG_ERROR")


class ValidationError(PipelineException):
    """Raised when data validation fails."""

    def __init__(self, message: str, field_name: str = "") -> None:
        super().__init__(message, "VALIDATION_ERROR")
        self.field_name = field_name


class TransformationError(PipelineException):
    """Raised when a transformation fails."""

    def __init__(self, message: str, stage_name: str = "", transform_name: str = "") -> None:
        super().__init__(message, "TRANSFORM_ERROR")
        self.stage_name = stage_name
        self.transform_name = transform_name


class SourceError(PipelineException):
    """Raised when a data source fails."""

    def __init__(self, message: str, source_name: str = "") -> None:
        super().__init__(message, "SOURCE_ERROR")
        self.source_name = source_name


class SinkError(PipelineException):
    """Raised when a data sink fails."""

    def __init__(self, message: str, sink_name: str = "") -> None:
        super().__init__(message, "SINK_ERROR")
        self.sink_name = sink_name


class StageError(PipelineException):
    """Raised when a pipeline stage fails."""

    def __init__(self, message: str, stage_name: str = "") -> None:
        super().__init__(message, "STAGE_ERROR")
        self.stage_name = stage_name


class RetryError(PipelineException):
    """Raised when retries are exhausted."""

    def __init__(self, message: str, retry_count: int = 0) -> None:
        super().__init__(message, "RETRY_ERROR")
        self.retry_count = retry_count


class CircuitBreakerOpen(PipelineException):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, stage_name: str = "") -> None:
        super().__init__(message, "CIRCUIT_BREAKER_OPEN")
        self.stage_name = stage_name


class TimeoutError(PipelineException):
    """Raised when a pipeline operation times out."""

    def __init__(self, message: str, timeout_seconds: int = 0) -> None:
        super().__init__(message, "TIMEOUT_ERROR")
        self.timeout_seconds = timeout_seconds


class DataQualityError(PipelineException):
    """Raised when data quality checks fail."""

    def __init__(self, message: str, rule_name: str = "") -> None:
        super().__init__(message, "DATA_QUALITY_ERROR")
        self.rule_name = rule_name


class CheckpointError(PipelineException):
    """Raised when checkpointing fails."""

    def __init__(self, message: str, checkpoint_id: str = "") -> None:
        super().__init__(message, "CHECKPOINT_ERROR")
        self.checkpoint_id = checkpoint_id
