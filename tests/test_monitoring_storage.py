"""
Tests for storage module.
"""

import time
from datetime import timedelta

import pytest

from thomas.marketplace.monitoring._exceptions import StorageError
from thomas.marketplace.monitoring._types import Label, Metric, MetricSample, MetricType
from thomas.marketplace.monitoring.storage import Chunk, DownsamplePolicy, TimeSeriesDB


class TestChunk:
    """Test Chunk storage."""

    def test_chunk_add_sample(self) -> None:
        """Test adding samples to chunk."""
        chunk = Chunk(1000.0, 2000.0)
        sample = MetricSample(timestamp=1500.0, value=42.0)

        assert chunk.add_sample(sample)
        assert chunk.sample_count() == 1

    def test_chunk_outside_range(self) -> None:
        """Test sample outside chunk range is rejected."""
        chunk = Chunk(1000.0, 2000.0)
        sample = MetricSample(timestamp=2500.0, value=42.0)

        assert not chunk.add_sample(sample)

    def test_chunk_at_capacity(self) -> None:
        """Test chunk rejects samples when full."""
        chunk = Chunk(1000.0, 2000.0, chunk_size=2)
        chunk.add_sample(MetricSample(timestamp=1100.0, value=1.0))
        chunk.add_sample(MetricSample(timestamp=1200.0, value=2.0))

        assert chunk.is_full()
        assert not chunk.add_sample(MetricSample(timestamp=1300.0, value=3.0))

    def test_chunk_query_range(self) -> None:
        """Test querying samples in range."""
        chunk = Chunk(1000.0, 2000.0)
        chunk.add_sample(MetricSample(timestamp=1100.0, value=1.0))
        chunk.add_sample(MetricSample(timestamp=1500.0, value=2.0))
        chunk.add_sample(MetricSample(timestamp=1900.0, value=3.0))

        results = chunk.get_samples(1200.0, 1800.0)
        assert len(results) == 1
        assert results[0].value == 2.0

    def test_chunk_summary(self) -> None:
        """Test chunk summary statistics."""
        chunk = Chunk(1000.0, 2000.0)
        for val in [1.0, 2.0, 3.0, 4.0, 5.0]:
            chunk.add_sample(MetricSample(timestamp=1100.0 + val * 100, value=val))

        summary = chunk.get_summary()
        assert summary is not None
        assert summary.min_value == 1.0
        assert summary.max_value == 5.0
        assert summary.count == 5
        assert summary.avg_value == 3.0


class TestTimeSeriesDB:
    """Test time-series database."""

    def test_write_and_query(self) -> None:
        """Test writing and querying data."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test metric",
        )
        sample = MetricSample(timestamp=time.time(), value=42.0)

        db.write("test_series", sample, metric)

        results = db.query("test_series", sample.timestamp - 10, sample.timestamp + 10)
        assert results is not None
        assert len(results) == 1
        assert results[0].value == 42.0

    def test_series_not_found(self) -> None:
        """Test querying non-existent series."""
        db = TimeSeriesDB()
        results = db.query("nonexistent", 0, 100)
        assert results is None

    def test_get_series(self) -> None:
        """Test retrieving series metadata."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )
        sample = MetricSample(timestamp=time.time(), value=10.0)
        db.write("test_series", sample, metric)

        ts = db.get_series("test_series")
        assert ts is not None
        assert ts.metric.name == "test_metric"

    def test_multiple_samples(self) -> None:
        """Test multiple samples in same series."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )
        now = time.time()

        for i in range(5):
            sample = MetricSample(timestamp=now + i, value=float(i))
            db.write("test_series", sample, metric)

        results = db.query("test_series", now - 1, now + 10)
        assert len(results) == 5

    def test_list_series(self) -> None:
        """Test listing all series."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )
        sample = MetricSample(timestamp=time.time(), value=1.0)

        for i in range(3):
            db.write(f"series_{i}", sample, metric)

        all_series = db.list_series()
        assert len(all_series) == 3
        assert "series_0" in all_series

    def test_find_by_labels(self) -> None:
        """Test finding series by labels."""
        db = TimeSeriesDB()
        label1 = Label("env", "prod")
        label2 = Label("service", "api")

        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
            labels=[label1, label2],
        )
        sample = MetricSample(timestamp=time.time(), value=1.0)

        db.write("series_1", sample, metric)

        results = db.find_series_by_labels({"env": "prod"})
        assert "series_1" in results

    def test_downsample_policy(self) -> None:
        """Test downsampling."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )

        now = time.time()
        for i in range(100):
            sample = MetricSample(timestamp=now + i, value=float(i))
            db.write("test_series", sample, metric)

        policy = DownsamplePolicy(
            interval=timedelta(seconds=10),
            aggregations=["min", "max", "avg"],
        )

        downsampled = db.downsample("test_series", policy)
        assert downsampled is not None
        assert len(downsampled) > 0

    def test_compact_chunks(self) -> None:
        """Test chunk compaction."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )

        # Create samples spread across time
        base_time = time.time()
        for chunk_idx in range(3):
            chunk_start = base_time + (chunk_idx * 3600)
            for i in range(5):
                sample = MetricSample(
                    timestamp=chunk_start + i * 10,
                    value=float(i),
                )
                db.write("test_series", sample, metric)

        merged = db.compact_chunks("test_series")
        assert merged >= 0

    def test_get_stats(self) -> None:
        """Test storage statistics."""
        db = TimeSeriesDB()
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )
        now = time.time()

        for i in range(10):
            sample = MetricSample(timestamp=now + i, value=float(i))
            db.write("test_series", sample, metric)

        stats = db.get_stats()
        assert stats["series_count"] == 1
        assert stats["sample_count"] == 10
        assert stats["chunk_count"] > 0

    def test_max_series_limit(self) -> None:
        """Test max series limit."""
        db = TimeSeriesDB(max_series=5)
        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )
        sample = MetricSample(timestamp=time.time(), value=1.0)

        # Add up to limit
        for i in range(5):
            db.write(f"series_{i}", sample, metric)

        # Try to exceed limit
        with pytest.raises(StorageError):
            db.write("series_overflow", sample, metric)

    def test_cleanup_old_data(self) -> None:
        """Test cleanup of old data."""
        db = TimeSeriesDB(retention_hours=1, chunk_duration_s=3600)
        db.start()

        metric = Metric(
            name="test_metric",
            type=MetricType.GAUGE,
            help="Test",
        )

        # Add old sample
        old_time = time.time() - (2 * 3600)
        sample = MetricSample(timestamp=old_time, value=1.0)
        db.write("test_series", sample, metric)

        # Run cleanup
        db._cleanup_old_data()

        db.stop()


class TestChunkSampling:
    """Test chunk sampling behavior."""

    def test_samples_sorted(self) -> None:
        """Test samples are sorted by timestamp."""
        chunk = Chunk(1000.0, 2000.0)

        # Add in non-sorted order
        chunk.add_sample(MetricSample(timestamp=1500.0, value=2.0))
        chunk.add_sample(MetricSample(timestamp=1100.0, value=1.0))
        chunk.add_sample(MetricSample(timestamp=1800.0, value=3.0))

        results = chunk.get_samples(1000.0, 2000.0)
        assert results[0].timestamp == 1100.0
        assert results[1].timestamp == 1500.0
        assert results[2].timestamp == 1800.0

    def test_empty_range_query(self) -> None:
        """Test querying empty range."""
        chunk = Chunk(1000.0, 2000.0)
        chunk.add_sample(MetricSample(timestamp=1100.0, value=1.0))

        results = chunk.get_samples(1200.0, 1300.0)
        assert len(results) == 0
