"""
Tests for telemetry engine module.

Tests telemetry ingestion, validation, querying, aggregation,
downsampling, and data retention.
"""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from thomas.iot_platform._exceptions import TelemetryError
from thomas.iot_platform._types import TelemetryPoint
from thomas.iot_platform.telemetry import TelemetryEngine


class TestTelemetryEngine:
    """Test telemetry engine functionality."""

    @pytest.fixture
    def engine(self) -> TelemetryEngine:
        """Create a telemetry engine instance."""
        return TelemetryEngine(retention_days=30)

    @pytest.fixture
    def device_id(self) -> str:
        """Get a test device ID."""
        return uuid4()

    def test_ingest_telemetry(self, engine: TelemetryEngine, device_id) -> None:
        """Test ingesting a single telemetry point."""
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=22.5,
            timestamp=datetime.utcnow(),
        )

        engine.ingest_telemetry(point)

        assert engine.get_data_point_count() == 1

    def test_ingest_invalid_metric(self, engine: TelemetryEngine, device_id) -> None:
        """Test ingesting with invalid metric fails."""
        point = TelemetryPoint(
            device_id=device_id,
            metric="",
            value=22.5,
            timestamp=datetime.utcnow(),
        )

        with pytest.raises(TelemetryError):
            engine.ingest_telemetry(point)

    def test_ingest_future_timestamp(self, engine: TelemetryEngine, device_id) -> None:
        """Test ingesting future timestamp fails."""
        future_time = datetime.utcnow() + timedelta(minutes=5)

        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=22.5,
            timestamp=future_time,
        )

        with pytest.raises(TelemetryError):
            engine.ingest_telemetry(point)

    def test_ingest_batch(self, engine: TelemetryEngine, device_id) -> None:
        """Test batch ingestion."""
        points = [
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=20.0 + i,
                timestamp=datetime.utcnow() - timedelta(minutes=i),
            )
            for i in range(5)
        ]

        count = engine.ingest_batch(points)

        assert count == 5
        assert engine.get_data_point_count() == 5

    def test_query_by_device(self, engine: TelemetryEngine, device_id) -> None:
        """Test querying by device ID."""
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=22.5,
            timestamp=datetime.utcnow(),
        )

        engine.ingest_telemetry(point)

        results = engine.query(device_id)

        assert len(results) == 1
        assert results[0].metric == "temperature"

    def test_query_by_metric(self, engine: TelemetryEngine, device_id) -> None:
        """Test querying by metric name."""
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.5,
                timestamp=datetime.utcnow(),
            )
        )
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="humidity",
                value=65.0,
                timestamp=datetime.utcnow(),
            )
        )

        results = engine.query(device_id, metric="temperature")

        assert len(results) == 1
        assert results[0].metric == "temperature"

    def test_query_by_time_range(self, engine: TelemetryEngine, device_id) -> None:
        """Test querying by time range."""
        now = datetime.utcnow()

        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=20.0,
                timestamp=now - timedelta(hours=2),
            )
        )
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.0,
                timestamp=now,
            )
        )

        start = now - timedelta(hours=1)
        results = engine.query(device_id, metric="temperature", start_time=start)

        assert len(results) == 1
        assert results[0].value == 22.0

    def test_get_latest(self, engine: TelemetryEngine, device_id) -> None:
        """Test getting latest telemetry point."""
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=20.0,
                timestamp=datetime.utcnow() - timedelta(minutes=1),
            )
        )
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.0,
                timestamp=datetime.utcnow(),
            )
        )

        latest = engine.get_latest(device_id, metric="temperature")

        assert latest is not None
        assert latest.value == 22.0

    def test_aggregate_average(self, engine: TelemetryEngine, device_id) -> None:
        """Test aggregation with average."""
        for i in range(5):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=datetime.utcnow(),
                )
            )

        avg = engine.aggregate(device_id, "temperature", "avg")

        assert avg == 22.0

    def test_aggregate_min_max(self, engine: TelemetryEngine, device_id) -> None:
        """Test aggregation with min and max."""
        for i in range(5):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=datetime.utcnow(),
                )
            )

        min_val = engine.aggregate(device_id, "temperature", "min")
        max_val = engine.aggregate(device_id, "temperature", "max")

        assert min_val == 20.0
        assert max_val == 24.0

    def test_aggregate_count(self, engine: TelemetryEngine, device_id) -> None:
        """Test aggregation with count."""
        for i in range(5):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=datetime.utcnow(),
                )
            )

        count = engine.aggregate(device_id, "temperature", "count")

        assert count == 5.0

    def test_aggregate_invalid_type(self, engine: TelemetryEngine, device_id) -> None:
        """Test aggregation with invalid type fails."""
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.5,
                timestamp=datetime.utcnow(),
            )
        )

        with pytest.raises(TelemetryError):
            engine.aggregate(device_id, "temperature", "invalid")

    def test_downsample(self, engine: TelemetryEngine, device_id) -> None:
        """Test downsampling telemetry data."""
        now = datetime.utcnow()

        for i in range(12):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=now - timedelta(minutes=12 - i),
                )
            )

        downsampled = engine.downsample(
            device_id,
            "temperature",
            interval_minutes=5,
        )

        assert len(downsampled) > 0

    def test_get_statistics(self, engine: TelemetryEngine, device_id) -> None:
        """Test getting metric statistics."""
        for i in range(10):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=datetime.utcnow(),
                )
            )

        stats = engine.get_statistics(device_id, "temperature")

        assert stats["count"] == 10.0
        assert stats["min"] == 20.0
        assert stats["max"] == 29.0
        assert "avg" in stats

    def test_cleanup_old_data(self, engine: TelemetryEngine, device_id) -> None:
        """Test cleanup of old data."""
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.5,
                timestamp=datetime.utcnow() - timedelta(days=60),
            )
        )
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.5,
                timestamp=datetime.utcnow(),
            )
        )

        deleted = engine.cleanup_old_data()

        assert deleted == 1
        assert engine.get_data_point_count() == 1

    def test_clear_device_data(self, engine: TelemetryEngine, device_id) -> None:
        """Test clearing all data for a device."""
        for i in range(5):
            engine.ingest_telemetry(
                TelemetryPoint(
                    device_id=device_id,
                    metric="temperature",
                    value=20.0 + i,
                    timestamp=datetime.utcnow(),
                )
            )

        cleared = engine.clear_device_data(device_id)

        assert cleared == 5
        assert engine.get_data_point_count() == 0

    def test_get_metrics_for_device(self, engine: TelemetryEngine, device_id) -> None:
        """Test getting unique metrics for device."""
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="temperature",
                value=22.5,
                timestamp=datetime.utcnow(),
            )
        )
        engine.ingest_telemetry(
            TelemetryPoint(
                device_id=device_id,
                metric="humidity",
                value=65.0,
                timestamp=datetime.utcnow(),
            )
        )

        metrics = engine.get_metrics_for_device(device_id)

        assert "temperature" in metrics
        assert "humidity" in metrics
        assert len(metrics) == 2

    def test_telemetry_with_tags(self, engine: TelemetryEngine, device_id) -> None:
        """Test telemetry points with tags."""
        point = TelemetryPoint(
            device_id=device_id,
            metric="temperature",
            value=22.5,
            timestamp=datetime.utcnow(),
            tags={"room": "bedroom", "floor": "2"},
        )

        engine.ingest_telemetry(point)

        retrieved = engine.query(device_id, metric="temperature")[0]

        assert retrieved.tags["room"] == "bedroom"
