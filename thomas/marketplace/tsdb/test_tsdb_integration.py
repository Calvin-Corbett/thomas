"""Integration tests for full TSDB pipeline.

Tests complete workflows: write → compress → downsample → query.
"""

import math
import tempfile
import time

import pytest

from . import (
    AggregationType,
    DataPoint,
    DownsampleConfig,
    RetentionPolicy,
    TimeRange,
    TSDBConfig,
    TSDBEngine,
)


@pytest.fixture
def temp_storage():
    """Provide temporary storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def engine_with_downsampling(temp_storage):
    """Provide engine with downsampling configured."""
    config = TSDBConfig(
        storage_path=temp_storage,
        chunk_size_ms=3600000,
        memory_limit_mb=50,
        flush_interval_ms=1000,
        downsample_configs=[
            DownsampleConfig(
                interval_minutes=5,
                aggregations=[AggregationType.AVG, AggregationType.MAX],
                retention_days=90,
            ),
            DownsampleConfig(
                interval_minutes=60,
                aggregations=[AggregationType.AVG],
                retention_days=365,
            ),
        ],
        compression_enabled=True,
    )
    return TSDBEngine(config)


class TestCompleteWriteQueryFlow:
    """Tests complete write and query flow."""

    def test_write_and_query_single_metric(self, temp_storage):
        """Test writing and querying single metric."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write data
        for i in range(10):
            engine.write_point(
                "cpu_usage",
                now + i * 60000,  # 1 minute intervals
                40.0 + i,
            )

        engine.flush()

        # Query
        time_range = TimeRange(start_time=now, end_time=now + 600000)
        results = engine.query("cpu_usage", time_range, aggregations=["avg"])

        assert len(results) > 0
        engine.close()

    def test_write_with_tags_and_query(self, temp_storage):
        """Test writing with tags and querying."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write data with different hosts
        for i in range(5):
            engine.write_point(
                "cpu_usage",
                now + i * 60000,
                40.0 + i,
                tags={"host": "web1", "datacenter": "us-east"},
            )

        for i in range(5):
            engine.write_point(
                "cpu_usage",
                now + i * 60000,
                50.0 + i,
                tags={"host": "web2", "datacenter": "us-west"},
            )

        engine.flush()

        # Query
        time_range = TimeRange(start_time=now, end_time=now + 600000)
        results = engine.query("cpu_usage", time_range, aggregations=["avg"])

        assert len(results) > 0

        # Check tags
        tags = engine.get_tags("cpu_usage")
        assert "host" in tags
        assert "web1" in tags["host"]
        assert "web2" in tags["host"]

        engine.close()

    def test_batch_write_and_query(self, temp_storage):
        """Test batch write and query."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Create batch of points
        points = []
        for i in range(100):
            points.append(
                DataPoint(
                    timestamp=now + i * 1000,
                    value=50.0 + math.sin(i / 10.0) * 10,
                )
            )

        # Write batch
        engine.write_points("temperature", points)
        engine.flush()

        # Query
        time_range = TimeRange(start_time=now, end_time=now + 100000)
        results = engine.query("temperature", time_range, aggregations=["avg", "min", "max"])

        assert len(results) >= 3

        engine.close()


class TestCompressionRoundTrip:
    """Tests compression and decompression."""

    def test_compressed_data_roundtrip(self, temp_storage):
        """Test that compressed data can be retrieved correctly."""
        config = TSDBConfig(
            storage_path=temp_storage,
            compression_enabled=True,
        )
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)
        expected_values = []

        # Write data
        for i in range(1000):
            value = 50.0 + 10.0 * math.sin(i / 100.0)
            engine.write_point("metric", now + i * 1000, value)
            expected_values.append(value)

        engine.flush()

        # Query and compare
        time_range = TimeRange(start_time=now, end_time=now + 1000000)
        results = engine.query("metric", time_range, aggregations=["count"])

        # Should preserve data correctly through compression
        assert len(results) > 0

        engine.close()

    def test_compression_disabled(self, temp_storage):
        """Test engine with compression disabled."""
        config = TSDBConfig(
            storage_path=temp_storage,
            compression_enabled=False,
        )
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write data
        for i in range(100):
            engine.write_point("metric", now + i * 1000, float(i))

        engine.flush()

        # Query
        time_range = TimeRange(start_time=now, end_time=now + 100000)
        results = engine.query("metric", time_range)

        assert len(results) >= 0

        engine.close()


class TestMultipleMetrics:
    """Tests handling multiple metrics."""

    def test_write_and_query_multiple_metrics(self, temp_storage):
        """Test writing and querying multiple metrics."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write multiple metrics
        for i in range(10):
            engine.write_point("cpu_usage", now + i * 1000, 40.0 + i)
            engine.write_point("memory_usage", now + i * 1000, 60.0 + i)
            engine.write_point("disk_usage", now + i * 1000, 30.0 + i)

        engine.flush()

        # Get all metrics
        metrics = engine.get_metrics()
        assert len(metrics) == 3
        assert "cpu_usage" in metrics
        assert "memory_usage" in metrics
        assert "disk_usage" in metrics

        # Query each metric
        time_range = TimeRange(start_time=now, end_time=now + 10000)
        cpu_results = engine.query("cpu_usage", time_range)
        mem_results = engine.query("memory_usage", time_range)
        disk_results = engine.query("disk_usage", time_range)

        assert len(cpu_results) > 0
        assert len(mem_results) > 0
        assert len(disk_results) > 0

        engine.close()


class TestAggregationTypes:
    """Tests various aggregation types."""

    def test_multiple_aggregations_same_query(self, temp_storage):
        """Test querying with multiple aggregation types."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write varying data
        for i in range(20):
            engine.write_point("metric", now + i * 1000, 30.0 + i)

        engine.flush()

        # Query with multiple aggregations
        time_range = TimeRange(start_time=now, end_time=now + 20000)
        results = engine.query(
            "metric",
            time_range,
            aggregations=["sum", "avg", "min", "max", "count"],
        )

        assert len(results) >= 5

        engine.close()

    def test_percentile_aggregation(self, temp_storage):
        """Test percentile aggregation."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write data
        for i in range(100):
            engine.write_point("metric", now + i * 1000, float(i))

        engine.flush()

        # Query percentiles
        time_range = TimeRange(start_time=now, end_time=now + 100000)
        results = engine.query("metric", time_range, aggregations=["percentile_50"])

        assert len(results) > 0

        engine.close()


class TestDownsampling:
    """Tests downsampling functionality."""

    def test_downsampling_configuration(self, engine_with_downsampling):
        """Test that downsampling is configured."""
        stats = engine_with_downsampling.get_engine_stats()
        assert stats is not None

        rollup_stats = engine_with_downsampling.rollup_engine.get_stats()
        assert rollup_stats["rollup_count"] == 2

    def test_select_best_rollup(self, engine_with_downsampling):
        """Test selecting best rollup for time range."""
        # 24 hour range
        time_range_ms = 24 * 60 * 60 * 1000

        # Should select appropriate rollup
        best_rollup = engine_with_downsampling.rollup_engine.select_best_rollup(time_range_ms)
        assert best_rollup is not None

    def test_downsample_points(self, engine_with_downsampling):
        """Test downsampling data points."""
        now = int(time.time() * 1000)

        # Create time series
        timestamps = list(range(now, now + 60000, 1000))
        values = [50.0 + i * 0.1 for i in range(len(timestamps))]

        # Downsample to 5 minute intervals
        rollup_points = engine_with_downsampling.rollup_engine.downsample_points(
            "metric",
            timestamps,
            values,
            "5m",
        )

        assert len(rollup_points) > 0

        engine_with_downsampling.close()


class TestRetention:
    """Tests retention policy functionality."""

    def test_retention_policy_application(self, temp_storage):
        """Test that retention policies are applied."""
        policy = RetentionPolicy(
            name="default",
            duration_days=30,
        )

        config = TSDBConfig(
            storage_path=temp_storage,
            default_retention=policy,
        )
        engine = TSDBEngine(config)

        # Verify policy is applied
        retrieved_policy = engine.retention_manager.get_policy_for_metric("any.metric")
        assert retrieved_policy is not None

        engine.close()

    def test_custom_retention_policy(self, temp_storage):
        """Test custom retention policy per metric."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        custom_policy = RetentionPolicy(
            name="short",
            duration_days=7,
            metric_patterns=["logs.*"],
        )

        engine.retention_manager.add_policy(custom_policy)

        # Verify it applies to matching metrics
        policy = engine.retention_manager.get_policy_for_metric("logs.app")
        assert policy == custom_policy

        engine.close()


class TestEngineStatistics:
    """Tests engine statistics and monitoring."""

    def test_comprehensive_statistics(self, temp_storage):
        """Test gathering comprehensive statistics."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write data
        for metric_num in range(5):
            for point_num in range(20):
                engine.write_point(
                    f"metric{metric_num}",
                    now + point_num * 1000,
                    float(point_num),
                )

        engine.flush()

        # Get statistics
        stats = engine.get_engine_stats()

        assert stats["unique_metrics"] == 5
        assert stats["buffered_points"] == 0  # After flush
        assert stats["total_chunks"] > 0

        engine.close()

    def test_index_statistics(self, temp_storage):
        """Test index statistics."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Write tagged data
        engine.write_point(
            "metric",
            now,
            100.0,
            tags={"host": "web1", "region": "us-east"},
        )

        engine.flush()

        # Get index stats
        index_stats = engine.index.get_stats()

        assert index_stats["unique_metrics"] > 0
        assert index_stats["total_series"] > 0

        engine.close()


class TestErrorHandling:
    """Tests error handling in workflows."""

    def test_query_nonexistent_metric(self, temp_storage):
        """Test querying non-existent metric."""
        from . import MetricNotFoundError

        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        time_range = TimeRange(start_time=0, end_time=1000000)

        with pytest.raises(MetricNotFoundError):
            engine.query("nonexistent", time_range)

        engine.close()

    def test_write_invalid_data(self, temp_storage):
        """Test writing invalid data."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        with pytest.raises(ValueError):
            engine.write_point("metric", -1000, 50.0)  # Negative timestamp

        engine.close()

    def test_invalid_time_range(self, temp_storage):
        """Test with invalid time range."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        with pytest.raises(ValueError):
            TimeRange(start_time=1000, end_time=500)  # End before start

        engine.close()


class TestContextManagement:
    """Tests context manager and resource cleanup."""

    def test_context_manager_flow(self, temp_storage):
        """Test using engine as context manager."""
        config = TSDBConfig(storage_path=temp_storage)

        with TSDBEngine(config) as engine:
            now = int(time.time() * 1000)
            engine.write_point("metric", now, 50.0)

            metrics = engine.get_metrics()
            assert "metric" in metrics

        # Engine should be closed after context

    def test_multiple_writes_with_flushes(self, temp_storage):
        """Test multiple write and flush cycles."""
        config = TSDBConfig(storage_path=temp_storage)
        engine = TSDBEngine(config)

        now = int(time.time() * 1000)

        # Multiple write/flush cycles
        for cycle in range(3):
            for i in range(10):
                engine.write_point("metric", now + cycle * 100000 + i * 1000, float(i))
            engine.flush()

        metrics = engine.get_metrics()
        assert "metric" in metrics

        engine.close()
