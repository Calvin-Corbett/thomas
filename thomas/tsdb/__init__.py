"""Thomas Time-Series Database (TSDB) Module.

A complete time-series database engine with compression, retention policies,
downsampling, and advanced query capabilities.

Core Components:
- engine: Main TSDB engine coordinating all operations
- storage: Chunk-based storage with compression
- compression: Delta encoding and XOR-based compression
- index: Metric and tag indices for fast lookups
- aggregator: Aggregation functions (sum, avg, min, max, percentile, etc.)
- retention: Retention policy management and cleanup
- downsampler: Automatic downsampling and rollup
- query: Query parsing and execution
- functions: Built-in mathematical and transformational functions

Example usage:

    from thomas.tsdb import TSDBEngine, TSDBConfig, DataPoint, TimeRange
    import time

    # Create engine
    config = TSDBConfig(storage_path="/tmp/tsdb")
    engine = TSDBEngine(config)

    # Write data
    now = int(time.time() * 1000)
    engine.write_point(
        metric_name="cpu_usage",
        timestamp=now,
        value=45.5,
        tags={"host": "web1", "datacenter": "us-east"}
    )

    # Query data
    time_range = TimeRange(start_time=now - 3600000, end_time=now)
    results = engine.query(
        metric_name="cpu_usage",
        time_range=time_range,
        aggregations=["avg", "max"]
    )

    # Close engine
    engine.close()
"""

__version__ = "0.1.0"
__author__ = "Thomas Project"

# Core types
# Exceptions
from ._exceptions import (
    MetricNotFoundError,
    QueryError,
    RetentionError,
    StorageError,
    TSDBError,
)
from ._types import (
    AggregationType,
    DataPoint,
    DownsampleConfig,
    FillPolicy,
    RetentionPolicy,
    TagFilter,
    TimeRange,
    TimeSeries,
    TSDBConfig,
)

# Aggregation
from .aggregator import (
    AggregationEngine,
    AggregationResult,
    Aggregator,
    AverageAggregator,
    CountAggregator,
    DeltaAggregator,
    MaxAggregator,
    MinAggregator,
    PercentileAggregator,
    RateAggregator,
    StdDevAggregator,
    StreamingAggregationEngine,
    SumAggregator,
)

# Compression
from .compression import (
    CompressionStats,
    DeltaOfDeltaEncoder,
    RunLengthEncoder,
    XORFloatCompressor,
)

# Downsampling
from .downsampler import (
    RollupConfig,
    RollupEngine,
    RollupPoint,
    RollupScheduler,
)

# Main engine
from .engine import TSDBEngine

# Functions
from .functions import (
    MathFunctions,
    PredictiveFunctions,
    TransformFunctions,
    WindowFunctions,
)

# Indexing
from .index import (
    BloomFilter,
    MetricIndex,
    TagIndex,
    TimeRangeIndex,
    TSDBIndex,
)
from .query import (
    FillPolicy as QueryFillPolicy,
)

# Query
from .query import (
    Query,
    QueryExecutor,
    QueryOptimizer,
    QueryParser,
    QueryResult,
)

# Retention
from .retention import (
    RetentionManager,
    RetentionStats,
)

# Storage
from .storage import (
    Chunk,
    ChunkMetadata,
    MemoryBuffer,
    StorageManager,
)

__all__ = [
    # Version
    "__version__",
    # Types
    "DataPoint",
    "TimeSeries",
    "TimeRange",
    "TagFilter",
    "AggregationType",
    "FillPolicy",
    "RetentionPolicy",
    "DownsampleConfig",
    "TSDBConfig",
    # Exceptions
    "TSDBError",
    "MetricNotFoundError",
    "RetentionError",
    "QueryError",
    "StorageError",
    # Storage
    "Chunk",
    "ChunkMetadata",
    "StorageManager",
    "MemoryBuffer",
    # Compression
    "DeltaOfDeltaEncoder",
    "XORFloatCompressor",
    "RunLengthEncoder",
    "CompressionStats",
    # Index
    "BloomFilter",
    "MetricIndex",
    "TagIndex",
    "TimeRangeIndex",
    "TSDBIndex",
    # Aggregation
    "Aggregator",
    "SumAggregator",
    "AverageAggregator",
    "MinAggregator",
    "MaxAggregator",
    "CountAggregator",
    "StdDevAggregator",
    "PercentileAggregator",
    "RateAggregator",
    "DeltaAggregator",
    "StreamingAggregationEngine",
    "AggregationEngine",
    "AggregationResult",
    # Retention
    "RetentionManager",
    "RetentionStats",
    # Downsampling
    "RollupConfig",
    "RollupPoint",
    "RollupEngine",
    "RollupScheduler",
    # Query
    "Query",
    "QueryResult",
    "QueryParser",
    "QueryOptimizer",
    "QueryExecutor",
    "QueryFillPolicy",
    # Functions
    "MathFunctions",
    "TransformFunctions",
    "WindowFunctions",
    "PredictiveFunctions",
    # Main Engine
    "TSDBEngine",
]
