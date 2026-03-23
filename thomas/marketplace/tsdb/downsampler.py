"""Downsampling and rollup engine for the Thomas TSDB.

Automatically creates and manages downsampled versions of data
at multiple time resolutions.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from ._types import AggregationType, DownsampleConfig
from .aggregator import AggregationEngine


@dataclass
class RollupConfig:
    """Configuration for a specific rollup level."""

    name: str  # e.g., "1m", "5m", "1h"
    interval_ms: int  # Interval in milliseconds
    aggregations: list[AggregationType]
    retention_days: int


@dataclass
class RollupPoint:
    """A single point in a downsampled series."""

    timestamp: int
    metric_name: str
    aggregation: str  # e.g., "avg", "sum", "max"
    value: float | None
    count: int = 0


class RollupEngine:
    """Manages downsampling and rollup operations."""

    def __init__(self) -> None:
        """Initialize rollup engine."""
        self.rollups: dict[str, RollupConfig] = {}
        self.rollup_data: dict[str, list[RollupPoint]] = defaultdict(list)
        self.aggregation_engine = AggregationEngine()
        self.scheduler_running = False
        self.scheduler_thread: threading.Thread | None = None

    def add_rollup_config(self, config: DownsampleConfig, name: str = None) -> str:
        """Add a rollup configuration.

        Args:
            config: DownsampleConfig to add
            name: Optional name for rollup (e.g., "5m", "1h")

        Returns:
            Name of the rollup
        """
        if name is None:
            name = f"{config.interval_minutes}m"

        rollup = RollupConfig(
            name=name,
            interval_ms=config.interval_ms,
            aggregations=config.aggregations,
            retention_days=config.retention_days,
        )

        self.rollups[name] = rollup
        return name

    def downsample_points(
        self,
        metric_name: str,
        timestamps: list[int],
        values: list[float],
        rollup_name: str,
    ) -> list[RollupPoint]:
        """Downsample points to a rollup level.

        Args:
            metric_name: Name of metric
            timestamps: List of timestamps
            values: List of values
            rollup_name: Name of rollup config to use

        Returns:
            List of RollupPoints at downsampled resolution

        Raises:
            ValueError: If rollup not found
        """
        if rollup_name not in self.rollups:
            raise ValueError(f"Unknown rollup: {rollup_name}")

        rollup = self.rollups[rollup_name]
        result: list[RollupPoint] = []

        if not timestamps:
            return result

        # Group points by interval
        intervals: dict[int, tuple[list[int], list[float]]] = {}
        for ts, val in zip(timestamps, values):
            interval_start = (ts // rollup.interval_ms) * rollup.interval_ms
            if interval_start not in intervals:
                intervals[interval_start] = ([], [])
            intervals[interval_start][0].append(ts)
            intervals[interval_start][1].append(val)

        # Compute aggregations for each interval
        for interval_start in sorted(intervals.keys()):
            interval_timestamps, interval_values = intervals[interval_start]

            for agg_type in rollup.aggregations:
                agg_str = str(agg_type)
                agg_value = self.aggregation_engine.aggregate(agg_str, interval_values)

                result.append(
                    RollupPoint(
                        timestamp=interval_start + rollup.interval_ms,
                        metric_name=metric_name,
                        aggregation=agg_str,
                        value=agg_value,
                        count=len(interval_values),
                    )
                )

        return result

    def select_best_rollup(self, time_range_ms: int) -> str | None:
        """Select the best rollup for a query time range.

        Uses a heuristic to choose rollup that gives ~100-1000 points.

        Args:
            time_range_ms: Time range in milliseconds

        Returns:
            Name of best rollup or None if raw data is better
        """
        target_points = 500
        target_interval = max(1000, time_range_ms // target_points)

        best_rollup = None
        best_interval_diff = float("inf")

        for rollup_name, rollup in self.rollups.items():
            diff = abs(rollup.interval_ms - target_interval)
            if diff < best_interval_diff:
                best_interval_diff = diff
                best_rollup = rollup_name

        return best_rollup

    def merge_rollups(
        self, rollup_points_list: list[list[RollupPoint]], metric_name: str
    ) -> dict[str, list[RollupPoint]]:
        """Merge results from multiple rollup levels.

        Args:
            rollup_points_list: Lists of rollup points from different metrics/rollups
            metric_name: Metric name for result grouping

        Returns:
            Dictionary mapping aggregation type to list of points
        """
        merged: dict[str, list[RollupPoint]] = defaultdict(list)

        for rollup_points in rollup_points_list:
            for point in rollup_points:
                key = f"{point.aggregation}"
                merged[key].append(point)

        return dict(merged)

    def start_scheduler(self, interval_seconds: int = 300) -> None:
        """Start background rollup scheduler.

        Args:
            interval_seconds: How often to run rollups (default 5 min)
        """
        if self.scheduler_running:
            return

        self.scheduler_running = True

        def scheduler_loop():
            while self.scheduler_running:
                time.sleep(interval_seconds)
                if self.scheduler_running:
                    # Actual rollup would be triggered here
                    pass

        self.scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def stop_scheduler(self) -> None:
        """Stop the background scheduler."""
        self.scheduler_running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)

    def list_rollups(self) -> list[str]:
        """List all configured rollups.

        Returns:
            List of rollup names
        """
        return list(self.rollups.keys())

    def get_rollup_info(self, rollup_name: str) -> dict | None:
        """Get information about a rollup.

        Args:
            rollup_name: Name of rollup

        Returns:
            Dictionary with rollup details or None
        """
        rollup = self.rollups.get(rollup_name)
        if not rollup:
            return None

        return {
            "name": rollup.name,
            "interval_ms": rollup.interval_ms,
            "aggregations": [str(agg) for agg in rollup.aggregations],
            "retention_days": rollup.retention_days,
        }

    def get_stats(self) -> dict:
        """Get statistics about rollups.

        Returns:
            Dictionary of statistics
        """
        total_points = sum(len(points) for points in self.rollup_data.values())

        return {
            "rollup_count": len(self.rollups),
            "total_rollup_points": total_points,
            "configured_rollups": self.list_rollups(),
        }


class RollupScheduler:
    """Schedules automatic rollup of data from raw to downsampled."""

    def __init__(self, rollup_engine: RollupEngine) -> None:
        """Initialize rollup scheduler.

        Args:
            rollup_engine: RollupEngine instance to use
        """
        self.rollup_engine = rollup_engine
        self.pending_rollups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.processed_up_to: dict[str, int] = {}

    def schedule_metric_rollup(self, metric_name: str, start_time: int, end_time: int) -> None:
        """Schedule a metric to be rolled up.

        Args:
            metric_name: Name of metric
            start_time: Start time to rollup in milliseconds
            end_time: End time to rollup in milliseconds
        """
        self.pending_rollups[metric_name].append((start_time, end_time))

    def process_pending_rollups(self, data_getter: callable, rollup_writer: callable) -> int:
        """Process pending rollups.

        Args:
            data_getter: Callback to get raw data for metric/time range
            rollup_writer: Callback to write rollup points

        Returns:
            Number of rollups processed
        """
        processed_count = 0

        for metric_name, ranges in list(self.pending_rollups.items()):
            for start_time, end_time in ranges:
                # Get raw data
                timestamps, values = data_getter(metric_name, start_time, end_time)

                # Create rollup for each configured rollup level
                for rollup_name in self.rollup_engine.list_rollups():
                    rollup_points = self.rollup_engine.downsample_points(metric_name, timestamps, values, rollup_name)

                    # Write rollup points
                    for point in rollup_points:
                        rollup_writer(point)

                processed_count += 1

            del self.pending_rollups[metric_name]

        return processed_count
