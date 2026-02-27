"""
Thomas Data Pipeline Framework

A comprehensive ETL/ELT data pipeline framework with support for streaming,
batch processing, data quality, lineage tracking, and monitoring.
"""

from thomas.data_pipeline._exceptions import (
    ConfigurationError,
    PipelineException,
    SinkError,
    SourceError,
    StageError,
    TransformationError,
    ValidationError,
)
from thomas.data_pipeline._types import (
    Aggregation,
    Alert,
    Checkpoint,
    DataSink,
    DataSource,
    Filter,
    JoinSpec,
    Metric,
    PipelineConfig,
    PipelineState,
    Record,
    Schema,
    Stage,
    Transform,
    Watermark,
    WindowSpec,
)

__all__ = [
    "PipelineConfig",
    "Stage",
    "DataSource",
    "DataSink",
    "Record",
    "Schema",
    "Transform",
    "Filter",
    "Aggregation",
    "JoinSpec",
    "WindowSpec",
    "Watermark",
    "Checkpoint",
    "PipelineState",
    "Metric",
    "Alert",
    "PipelineException",
    "ConfigurationError",
    "ValidationError",
    "TransformationError",
    "SourceError",
    "SinkError",
    "StageError",
]

__version__ = "0.1.0"
