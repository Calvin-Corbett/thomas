"""Main TSDB engine for the Thomas time-series database.

Coordinates writing, querying, compression, and retention across all components.
"""

import threading
import time
from collections import defaultdict

from ._exceptions import MetricNotFoundError
from ._types import (
    DataPoint,
    TagFilter,
    TimeRange,
    TSDBConfig,
)
from .aggregator import AggregationEngine
from .downsampler import RollupEngine
from .index import TSDBIndex
from .query import QueryResult
from .retention import RetentionManager
from .storage import Chunk, MemoryBuffer, StorageManager


class TSDBEngine:
    """Main TSDB engine coordinating all operations.

    Manages data ingestion, storage, querying, compression, and retention.
    """

    def __init__(self, config: TSDBConfig) -> None:
        """Initialize the TSDB engine.

        Args:
            config: TSDBConfig with engine settings

        Raises:
            StorageError: If storage initialization fails
        """
        self.config = config
        self.storage_manager = StorageManager(config.storage_path)
        self.memory_buffer = MemoryBuffer(config.memory_limit_bytes)
        self.index = TSDBIndex()
        self.aggregation_engine = AggregationEngine()
        self.retention_manager = RetentionManager(config)
        self.rollup_engine = RollupEngine()

        # Track chunks and series
        self.series_chunks: dict[int, list[int]] = defaultdict(list)
        self.metric_series: dict[str, set[int]] = defaultdict(set)
        self.next_chunk_id = 0
        self.flush_thread: threading.Thread | None = None
        self.engine_running = False

        # Add default rollup configs
        for downsample_config in config.downsample_configs:
            self.rollup_engine.add_rollup_config(downsample_config)

        self.start_flush_scheduler()

    def write_point(
        self,
        metric_name: str,
        timestamp: int,
        value: float,
        tags: dict[str, str] = None,
    ) -> None:
        """Write a single data point.

        Args:
            metric_name: Name of the metric
            timestamp: Timestamp in milliseconds
            value: Numeric value
            tags: Optional tags

        Raises:
            ValueError: If data is invalid
        """
        point = DataPoint(timestamp=timestamp, value=value, tags=tags or {})
        self.write_points(metric_name, [point])

    def write_points(self, metric_name: str, points: list[DataPoint]) -> None:
        """Write multiple data points.

        Args:
            metric_name: Name of the metric
            points: List of DataPoints to write

        Raises:
            ValueError: If data is invalid
        """
        if not points:
            return

        # Get or create series
        series_id = self._get_or_create_series(metric_name, points[0].tags)

        # Add to memory buffer
        for point in points:
            self.memory_buffer.add_point(metric_name, series_id, point)

        # Flush if buffer is full
        if self.memory_buffer.is_full():
            self.flush()

    def query(
        self,
        metric_name: str,
        time_range: TimeRange,
        aggregations: list[str] = None,
        tag_filters: list[TagFilter] = None,
    ) -> list[QueryResult]:
        """Query time-series data.

        Args:
            metric_name: Name of metric to query
            time_range: Time range for query
            aggregations: Optional list of aggregation types
            tag_filters: Optional tag filters

        Returns:
            List of QueryResult objects

        Raises:
            MetricNotFoundError: If metric doesn't exist
            QueryError: If query execution fails
        """
        if aggregations is None:
            aggregations = ["avg"]

        # Find matching series
        tag_filter_tuples = [(f.key, f.value) for f in (tag_filters or [])]
        series_ids = self.index.find_series(metric_name, tag_filter_tuples)

        if not series_ids:
            raise MetricNotFoundError(metric_name)

        results: list[QueryResult] = []

        # Query each series
        for series_id in series_ids:
            chunks_to_read = self.series_chunks.get(series_id, [])

            # Collect data from chunks
            timestamps: list[int] = []
            values: list[float] = []

            for chunk_id in chunks_to_read:
                chunk = self.storage_manager.load_chunk(chunk_id)
                if not chunk:
                    continue

                # Filter by time range
                if not chunk.start_time < time_range.end_time or chunk.end_time <= time_range.start_time:
                    chunk.decompress()
                    chunk_points = chunk.get_points()

                    for point in chunk_points:
                        if time_range.contains(point.timestamp):
                            timestamps.append(point.timestamp)
                            values.append(float(point.value))

            # Apply aggregations
            for agg_str in aggregations:
                agg_value = self.aggregation_engine.aggregate(agg_str, values)

                result = QueryResult(
                    query=None,
                    metric_name=metric_name,
                    timestamps=timestamps,
                    values=[agg_value] if agg_value is not None else [None],
                    aggregation=agg_str,
                )

                results.append(result)

        return results

    def flush(self) -> None:
        """Flush in-memory buffer to disk."""
        buffered_data = self.memory_buffer.get_all_points()

        for metric_name, series_data in buffered_data.items():
            for series_id, points in series_data.items():
                if not points:
                    continue

                # Sort points by timestamp
                points.sort()

                # Create chunks
                for point in points:
                    chunk_start = (point.timestamp // self.config.chunk_size_ms) * self.config.chunk_size_ms
                    chunk_end = chunk_start + self.config.chunk_size_ms

                    # Get or create chunk

                    chunk = Chunk(
                        chunk_id=self.next_chunk_id,
                        metric_name=metric_name,
                        start_time=chunk_start,
                        end_time=chunk_end,
                        tags=point.tags,
                        compression_enabled=self.config.compression_enabled,
                    )

                    chunk.add_point(point)

                    # Compress and save
                    chunk.compress()
                    self.storage_manager.save_chunk(chunk)

                    # Update indexes
                    chunk_id = self.next_chunk_id
                    self.series_chunks[series_id].append(chunk_id)
                    self.index.add_chunk(series_id, chunk_start, chunk_end)

                    self.next_chunk_id += 1

        self.memory_buffer.clear()

    def get_tags(self, metric_name: str) -> dict[str, set[str]]:
        """Get all tag keys and values for a metric.

        Args:
            metric_name: Name of metric

        Returns:
            Dictionary mapping tag key to set of values

        Raises:
            MetricNotFoundError: If metric doesn't exist
        """
        series_ids = self.index.metric_index.get_series_ids(metric_name)

        if not series_ids:
            raise MetricNotFoundError(metric_name)

        tags_by_key: dict[str, set[str]] = defaultdict(set)

        for series_id in series_ids:
            series_tags = self.index.get_series_tags(series_id)
            for key, value in series_tags.items():
                tags_by_key[key].add(value)

        return dict(tags_by_key)

    def get_metrics(self) -> list[str]:
        """Get all metric names.

        Returns:
            List of metric names
        """
        return self.index.metric_index.get_all_metrics()

    def get_engine_stats(self) -> dict:
        """Get engine statistics.

        Returns:
            Dictionary with various statistics
        """
        index_stats = self.index.get_stats()

        return {
            "unique_metrics": index_stats["unique_metrics"],
            "total_series": index_stats["total_series"],
            "total_chunks": index_stats["total_chunks"],
            "buffered_points": self.memory_buffer.point_count,
            "buffer_size_bytes": self.memory_buffer.current_size_bytes,
            "compression_enabled": self.config.compression_enabled,
            "chunk_size_ms": self.config.chunk_size_ms,
        }

    def start_flush_scheduler(self) -> None:
        """Start background flush scheduler."""
        if self.engine_running:
            return

        self.engine_running = True

        def flush_loop():
            while self.engine_running:
                time.sleep(self.config.flush_interval_ms / 1000.0)
                if self.engine_running and self.memory_buffer.point_count > 0:
                    self.flush()

        self.flush_thread = threading.Thread(target=flush_loop, daemon=True)
        self.flush_thread.start()

    def stop_flush_scheduler(self) -> None:
        """Stop the background flush scheduler."""
        self.engine_running = False
        if self.flush_thread:
            self.flush_thread.join(timeout=5)

    def close(self) -> None:
        """Close the engine and flush remaining data."""
        self.stop_flush_scheduler()
        if self.memory_buffer.point_count > 0:
            self.flush()

    def _get_or_create_series(self, metric_name: str, tags: dict[str, str]) -> int:
        """Get or create a series ID for metric+tags combination.

        Args:
            metric_name: Name of metric
            tags: Tag dictionary

        Returns:
            Series ID
        """
        # For now, one series per metric (simplified)
        # In production, would need to handle multiple series per metric
        if metric_name in self.metric_series:
            series_id = list(self.metric_series[metric_name])[0]
        else:
            series_id = self.index.add_metric(metric_name, tags)
            self.metric_series[metric_name].add(series_id)

        return series_id

    def __enter__(self) -> "TSDBEngine":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
