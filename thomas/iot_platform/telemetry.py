"""
Telemetry data ingestion and querying engine.

Handles telemetry collection, validation, time-series storage,
querying, aggregation, downsampling, and retention policies.
"""

from __future__ import annotations

import statistics
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from thomas.iot_platform._exceptions import TelemetryError
from thomas.iot_platform._types import TelemetryPoint


class TelemetryEngine:
    """
    Manages telemetry data ingestion, storage, and queries.

    Provides validation, time-series storage, aggregation,
    downsampling, and configurable retention policies.
    """

    def __init__(self, retention_days: int = 30) -> None:
        """
        Initialize the telemetry engine.

        Args:
            retention_days: Number of days to retain telemetry data.
        """
        self._data: dict[UUID, list[TelemetryPoint]] = {}
        self._retention_days = retention_days
        self._processors: list[Callable[[TelemetryPoint], None]] = []
        self._lock = threading.RLock()

    def ingest_telemetry(self, point: TelemetryPoint) -> None:
        """
        Ingest a single telemetry data point.

        Args:
            point: TelemetryPoint to ingest.

        Raises:
            TelemetryError: If validation fails.
        """
        self._validate_telemetry(point)

        with self._lock:
            if point.device_id not in self._data:
                self._data[point.device_id] = []

            self._data[point.device_id].append(point)
            self._data[point.device_id].sort(key=lambda p: p.timestamp)

        # Notify processors
        for processor in self._processors:
            try:
                processor(point)
            except Exception:  # REVIEWED: broad catch
                pass  # Silently ignore processor errors

    def ingest_batch(self, points: list[TelemetryPoint]) -> int:
        """
        Ingest multiple telemetry points.

        Args:
            points: List of TelemetryPoint objects.

        Returns:
            Number of successfully ingested points.

        Raises:
            TelemetryError: If any validation fails.
        """
        valid_count = 0

        for point in points:
            try:
                self.ingest_telemetry(point)
                valid_count += 1
            except TelemetryError:
                pass  # Skip invalid points

        return valid_count

    def _validate_telemetry(self, point: TelemetryPoint) -> None:
        """
        Validate telemetry point data.

        Args:
            point: TelemetryPoint to validate.

        Raises:
            TelemetryError: If validation fails.
        """
        if not point.metric or len(point.metric.strip()) == 0:
            raise TelemetryError("Metric name cannot be empty")

        if not isinstance(point.value, (int, float, str)):
            raise TelemetryError("Value must be numeric or string")

        if point.timestamp > datetime.utcnow() + timedelta(seconds=60):
            raise TelemetryError("Timestamp cannot be in future")

    def query(
        self,
        device_id: UUID,
        metric: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[TelemetryPoint]:
        """
        Query telemetry data with filters.

        Args:
            device_id: Device to query.
            metric: Optional metric name filter.
            start_time: Optional start timestamp.
            end_time: Optional end timestamp.

        Returns:
            List of matching TelemetryPoint objects.
        """
        with self._lock:
            if device_id not in self._data:
                return []

            results = self._data[device_id]

            if metric:
                results = [p for p in results if p.metric == metric]

            if start_time:
                results = [p for p in results if p.timestamp >= start_time]

            if end_time:
                results = [p for p in results if p.timestamp <= end_time]

            return results

    def get_latest(self, device_id: UUID, metric: str | None = None) -> TelemetryPoint | None:
        """
        Get the most recent telemetry point.

        Args:
            device_id: Device to query.
            metric: Optional metric filter.

        Returns:
            Most recent TelemetryPoint or None if no data.
        """
        with self._lock:
            if device_id not in self._data:
                return None

            results = self._data[device_id]

            if metric:
                results = [p for p in results if p.metric == metric]

            return results[-1] if results else None

    def aggregate(
        self,
        device_id: UUID,
        metric: str,
        aggregation: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> float | None:
        """
        Calculate aggregation over telemetry data.

        Supported aggregations: 'avg', 'min', 'max', 'count', 'sum'.

        Args:
            device_id: Device to aggregate.
            metric: Metric name.
            aggregation: Type of aggregation.
            start_time: Optional start timestamp.
            end_time: Optional end timestamp.

        Returns:
            Aggregated value or None if no data.

        Raises:
            TelemetryError: If aggregation type invalid.
        """
        if aggregation not in ("avg", "min", "max", "count", "sum"):
            raise TelemetryError(f"Invalid aggregation: {aggregation}")

        points = self.query(device_id, metric, start_time, end_time)

        if not points:
            return None

        numeric_values = [float(p.value) for p in points if isinstance(p.value, (int, float))]

        if not numeric_values:
            return None

        if aggregation == "avg":
            return statistics.mean(numeric_values)
        elif aggregation == "min":
            return min(numeric_values)
        elif aggregation == "max":
            return max(numeric_values)
        elif aggregation == "count":
            return float(len(numeric_values))
        elif aggregation == "sum":
            return sum(numeric_values)

        return None

    def downsample(
        self,
        device_id: UUID,
        metric: str,
        interval_minutes: int,
        aggregation: str = "avg",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[tuple[datetime, float]]:
        """
        Downsample telemetry data into time buckets.

        Args:
            device_id: Device to downsample.
            metric: Metric name.
            interval_minutes: Time bucket size in minutes.
            aggregation: Aggregation function for buckets.
            start_time: Optional start timestamp.
            end_time: Optional end timestamp.

        Returns:
            List of (timestamp, aggregated_value) tuples.
        """
        points = self.query(device_id, metric, start_time, end_time)

        if not points:
            return []

        if not start_time:
            start_time = points[0].timestamp
        if not end_time:
            end_time = points[-1].timestamp

        bucket_delta = timedelta(minutes=interval_minutes)
        buckets: dict[datetime, list[float]] = {}

        for point in points:
            bucket_key = point.timestamp.replace(
                minute=(point.timestamp.minute // interval_minutes) * interval_minutes,
                second=0,
                microsecond=0,
            )

            if bucket_key not in buckets:
                buckets[bucket_key] = []

            if isinstance(point.value, (int, float)):
                buckets[bucket_key].append(float(point.value))

        result: list[tuple[datetime, float]] = []

        for bucket_time in sorted(buckets.keys()):
            values = buckets[bucket_time]

            if values:
                if aggregation == "avg":
                    agg_value = statistics.mean(values)
                elif aggregation == "min":
                    agg_value = min(values)
                elif aggregation == "max":
                    agg_value = max(values)
                elif aggregation == "sum":
                    agg_value = sum(values)
                else:
                    agg_value = statistics.mean(values)

                result.append((bucket_time, agg_value))

        return result

    def get_statistics(
        self,
        device_id: UUID,
        metric: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, float]:
        """
        Get statistics for a metric.

        Args:
            device_id: Device to analyze.
            metric: Metric name.
            start_time: Optional start timestamp.
            end_time: Optional end timestamp.

        Returns:
            Dictionary with statistics (min, max, avg, count, latest).
        """
        points = self.query(device_id, metric, start_time, end_time)

        if not points:
            return {}

        numeric_values = [float(p.value) for p in points if isinstance(p.value, (int, float))]

        if not numeric_values:
            return {}

        return {
            "count": float(len(numeric_values)),
            "min": min(numeric_values),
            "max": max(numeric_values),
            "avg": statistics.mean(numeric_values),
            "latest": float(points[-1].value) if isinstance(points[-1].value, (int, float)) else None,
        }

    def cleanup_old_data(self) -> int:
        """
        Remove telemetry data older than retention period.

        Returns:
            Number of data points deleted.
        """
        cutoff_time = datetime.utcnow() - timedelta(days=self._retention_days)
        deleted_count = 0

        with self._lock:
            for device_id in list(self._data.keys()):
                before = len(self._data[device_id])
                self._data[device_id] = [p for p in self._data[device_id] if p.timestamp >= cutoff_time]
                deleted_count += before - len(self._data[device_id])

                if not self._data[device_id]:
                    del self._data[device_id]

        return deleted_count

    def register_processor(self, processor: Callable[[TelemetryPoint], None]) -> None:
        """
        Register a processor to handle ingested telemetry.

        Args:
            processor: Callable that receives TelemetryPoint objects.
        """
        with self._lock:
            self._processors.append(processor)

    def get_device_count(self) -> int:
        """Get number of devices with telemetry data."""
        with self._lock:
            return len(self._data)

    def get_data_point_count(self) -> int:
        """Get total number of stored telemetry points."""
        with self._lock:
            return sum(len(points) for points in self._data.values())

    def clear_device_data(self, device_id: UUID) -> int:
        """
        Clear all telemetry data for a device.

        Args:
            device_id: Device to clear data for.

        Returns:
            Number of points deleted.
        """
        with self._lock:
            if device_id in self._data:
                count = len(self._data[device_id])
                del self._data[device_id]
                return count
            return 0

    def get_metrics_for_device(self, device_id: UUID) -> list[str]:
        """
        Get list of unique metrics for a device.

        Args:
            device_id: Device to analyze.

        Returns:
            List of metric names.
        """
        with self._lock:
            if device_id not in self._data:
                return []

            metrics = set(p.metric for p in self._data[device_id])
            return sorted(list(metrics))

    def set_retention_policy(self, days: int) -> None:
        """
        Update retention policy.

        Args:
            days: Number of days to retain data.
        """
        with self._lock:
            self._retention_days = days
