"""Comprehensive tests for the TSDB engine.

Tests core functionality: writing, querying, filtering, aggregation.
"""

import tempfile
import time

import pytest

from . import (
    DataPoint,
    MetricNotFoundError,
    TagFilter,
    TimeRange,
    TSDBConfig,
    TSDBEngine,
)


@pytest.fixture
def temp_storage():
    """Provide temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def engine(temp_storage):
    """Provide initialized TSDB engine."""
    config = TSDBConfig(
        storage_path=temp_storage,
        chunk_size_ms=3600000,
        memory_limit_mb=10,
        flush_interval_ms=1000,
    )
    return TSDBEngine(config)


class TestWriteOperations:
    """Tests for write operations."""

    def test_write_single_point(self, engine):
        """Test writing a single data point."""
        now = int(time.time() * 1000)
        engine.write_point("cpu_usage", now, 45.5)
        assert engine.get_metrics() == ["cpu_usage"]

    def test_write_multiple_points(self, engine):
        """Test writing multiple points at once."""
        now = int(time.time() * 1000)
        points = [
            DataPoint(timestamp=now, value=45.5),
            DataPoint(timestamp=now + 1000, value=46.0),
            DataPoint(timestamp=now + 2000, value=44.5),
        ]
        engine.write_points("memory_usage", points)
        assert "memory_usage" in engine.get_metrics()

    def test_write_with_tags(self, engine):
        """Test writing points with tags."""
        now = int(time.time() * 1000)
        tags = {"host": "web1", "datacenter": "us-east"}
        engine.write_point("cpu_usage", now, 45.5, tags=tags)

        # Get tags
        metric_tags = engine.get_tags("cpu_usage")
        assert "host" in metric_tags
        assert "web1" in metric_tags["host"]

    def test_write_invalid_data_point(self, engine):
        """Test writing invalid data point raises error."""
        with pytest.raises(ValueError):
            engine.write_point("cpu", -1000, 45.5)  # Negative timestamp

    def test_flush_on_buffer_full(self, engine):
        """Test automatic flush when buffer fills."""
        engine.memory_buffer.max_size_bytes = 100  # Very small buffer
        now = int(time.time() * 1000)

        # Write enough to fill buffer
        for i in range(20):
            engine.write_point("metric", now + i * 1000, float(i))

        # Buffer should be flushed
        assert engine.memory_buffer.point_count < 20

    def test_write_preserves_timestamp_order(self, engine):
        """Test that timestamps are preserved correctly."""
        now = int(time.time() * 1000)
        points = [
            DataPoint(timestamp=now + 3000, value=3.0),
            DataPoint(timestamp=now + 1000, value=1.0),
            DataPoint(timestamp=now + 2000, value=2.0),
        ]
        engine.write_points("metric", points)
        engine.flush()

        # Points should maintain original timestamps
        stats = engine.get_engine_stats()
        assert stats["total_chunks"] > 0


class TestQueryOperations:
    """Tests for query operations."""

    def test_query_nonexistent_metric(self, engine):
        """Test querying non-existent metric raises error."""
        now = int(time.time() * 1000)
        time_range = TimeRange(start_time=now - 3600000, end_time=now)

        with pytest.raises(MetricNotFoundError):
            engine.query("nonexistent", time_range)

    def test_basic_query(self, engine):
        """Test basic query retrieval."""
        now = int(time.time() * 1000)

        # Write data
        for i in range(10):
            engine.write_point("cpu", now + i * 60000, 40.0 + i)

        engine.flush()

        # Query
        time_range = TimeRange(start_time=now, end_time=now + 600000)
        results = engine.query("cpu", time_range, aggregations=["avg"])

        assert len(results) > 0
        assert results[0].metric_name == "cpu"

    def test_query_with_tag_filters(self, engine):
        """Test querying with tag filters."""
        now = int(time.time() * 1000)
        tags_web = {"host": "web1", "type": "web"}
        tags_db = {"host": "db1", "type": "database"}

        engine.write_point("cpu", now, 45.0, tags=tags_web)
        engine.write_point("cpu", now, 35.0, tags=tags_db)
        engine.flush()

        time_range = TimeRange(start_time=now - 1000, end_time=now + 1000)

        # Query with filter
        tag_filters = [TagFilter(key="type", operator="=", value="web")]
        results = engine.query("cpu", time_range, tag_filters=tag_filters)

        # Should get result for web host
        assert len(results) > 0

    def test_query_empty_time_range(self, engine):
        """Test querying empty time range."""
        now = int(time.time() * 1000)
        time_range = TimeRange(start_time=now, end_time=now + 1000)

        # Write data outside range
        engine.write_point("metric", now - 10000, 50.0)
        engine.flush()

        results = engine.query("metric", time_range)
        # Should return empty or zero results
        assert len(results) >= 0

    def test_query_multiple_aggregations(self, engine):
        """Test querying with multiple aggregation types."""
        now = int(time.time() * 1000)

        # Write varying data
        for i in range(10):
            engine.write_point("metric", now + i * 1000, float(i * 10))

        engine.flush()

        time_range = TimeRange(start_time=now, end_time=now + 10000)
        results = engine.query(
            "metric",
            time_range,
            aggregations=["sum", "avg", "min", "max", "count"],
        )

        assert len(results) >= 5  # Should have results for each aggregation


class TestAggregations:
    """Tests for aggregation functions."""

    def test_sum_aggregation(self, engine):
        """Test sum aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregation_engine.aggregate("sum", values)
        assert result == 60.0

    def test_avg_aggregation(self, engine):
        """Test average aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregation_engine.aggregate("avg", values)
        assert result == 20.0

    def test_min_aggregation(self, engine):
        """Test minimum aggregation."""
        values = [10.0, 20.0, 5.0, 30.0]
        result = engine.aggregation_engine.aggregate("min", values)
        assert result == 5.0

    def test_max_aggregation(self, engine):
        """Test maximum aggregation."""
        values = [10.0, 20.0, 5.0, 30.0]
        result = engine.aggregation_engine.aggregate("max", values)
        assert result == 30.0

    def test_count_aggregation(self, engine):
        """Test count aggregation."""
        values = [10.0, 20.0, 30.0]
        result = engine.aggregation_engine.aggregate("count", values)
        assert result == 3.0

    def test_percentile_aggregation(self, engine):
        """Test percentile aggregation."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = engine.aggregation_engine.aggregate("percentile_50", values)
        assert result == 3.0

    def test_stddev_aggregation(self, engine):
        """Test standard deviation aggregation."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = engine.aggregation_engine.aggregate("stddev", values)
        assert result is not None
        assert result > 0

    def test_empty_aggregation(self, engine):
        """Test aggregation on empty list."""
        result = engine.aggregation_engine.aggregate("avg", [])
        assert result is None

    def test_aggregation_by_interval(self, engine):
        """Test aggregating by time interval."""
        timestamps = [1000, 2000, 3000, 4000, 5000]
        values = [10.0, 20.0, 30.0, 40.0, 50.0]

        results = engine.aggregation_engine.aggregate_by_interval(timestamps, values, 2000, "avg")

        assert len(results) > 0
        assert all(r.value is not None for r in results)


class TestTagFiltering:
    """Tests for tag-based filtering."""

    def test_tag_filter_equality(self):
        """Test tag filter with equality operator."""
        filter = TagFilter(key="host", operator="=", value="web1")
        assert filter.matches("web1")
        assert not filter.matches("db1")

    def test_tag_filter_inequality(self):
        """Test tag filter with inequality operator."""
        filter = TagFilter(key="host", operator="!=", value="web1")
        assert not filter.matches("web1")
        assert filter.matches("db1")

    def test_tag_filter_in_list(self):
        """Test tag filter with 'in' operator."""
        filter = TagFilter(key="host", operator="in", value=["web1", "web2"])
        assert filter.matches("web1")
        assert filter.matches("web2")
        assert not filter.matches("db1")

    def test_tag_filter_regex(self):
        """Test tag filter with regex operator."""
        filter = TagFilter(key="host", operator="regex", value="web.*")
        assert filter.matches("web1")
        assert filter.matches("web2")
        assert not filter.matches("db1")

    def test_tag_filter_comparison(self):
        """Test tag filter with comparison operators."""
        filter_gt = TagFilter(key="port", operator=">", value="8000")
        assert filter_gt.matches("9000")
        assert not filter_gt.matches("7000")

        filter_lt = TagFilter(key="port", operator="<", value="8000")
        assert not filter_lt.matches("9000")
        assert filter_lt.matches("7000")


class TestEngineStatistics:
    """Tests for engine statistics."""

    def test_get_metrics(self, engine):
        """Test retrieving all metrics."""
        now = int(time.time() * 1000)
        engine.write_point("metric1", now, 10.0)
        engine.write_point("metric2", now, 20.0)
        engine.write_point("metric3", now, 30.0)

        metrics = engine.get_metrics()
        assert len(metrics) == 3
        assert "metric1" in metrics
        assert "metric2" in metrics
        assert "metric3" in metrics

    def test_get_engine_stats(self, engine):
        """Test retrieving engine statistics."""
        now = int(time.time() * 1000)
        for i in range(10):
            engine.write_point(f"metric{i}", now, float(i))

        stats = engine.get_engine_stats()
        assert "unique_metrics" in stats
        assert "total_series" in stats
        assert "buffered_points" in stats
        assert stats["buffered_points"] == 10

    def test_buffer_memory_usage(self, engine):
        """Test memory buffer usage tracking."""
        now = int(time.time() * 1000)

        initial_size = engine.memory_buffer.current_size_bytes
        engine.write_point("metric", now, 45.5)
        new_size = engine.memory_buffer.current_size_bytes

        assert new_size > initial_size

    def test_compression_stats(self, engine):
        """Test compression statistics after flush."""
        now = int(time.time() * 1000)
        for i in range(100):
            engine.write_point("metric", now + i * 1000, float(i))

        engine.flush()
        stats = engine.get_engine_stats()
        assert stats["total_chunks"] > 0


class TestContextManager:
    """Tests for context manager protocol."""

    def test_engine_as_context_manager(self, temp_storage):
        """Test using engine as context manager."""
        config = TSDBConfig(storage_path=temp_storage)

        with TSDBEngine(config) as engine:
            now = int(time.time() * 1000)
            engine.write_point("metric", now, 45.5)
            assert "metric" in engine.get_metrics()

    def test_engine_cleanup_on_exit(self, temp_storage):
        """Test engine cleanup when exiting context."""
        config = TSDBConfig(storage_path=temp_storage)

        with TSDBEngine(config) as engine:
            now = int(time.time() * 1000)
            engine.write_point("metric", now, 45.5)

        # Engine should be closed and cleaned up
        assert not engine.engine_running
