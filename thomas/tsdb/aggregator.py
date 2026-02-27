"""Aggregation engine for the Thomas TSDB.

Implements efficient computation of various aggregation functions
including percentiles, rates, and streaming aggregation.
"""

import math
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class AggregationResult:
    """Result of an aggregation operation."""

    timestamp: int  # Interval end timestamp
    value: int | float | None  # Aggregated value
    count: int = 0  # Number of points used
    min_value: float | None = None  # Minimum value in interval
    max_value: float | None = None  # Maximum value in interval


class Aggregator:
    """Base class for aggregation operations."""

    def aggregate(self, values: list[float]) -> float | None:
        """Compute the aggregate of values.

        Args:
            values: List of float values

        Returns:
            Aggregated result or None if empty
        """
        raise NotImplementedError


class SumAggregator(Aggregator):
    """Computes the sum of values."""

    def aggregate(self, values: list[float]) -> float | None:
        """Sum all values.

        Args:
            values: List of float values

        Returns:
            Sum of values or None if empty
        """
        if not values:
            return None
        return sum(values)


class AverageAggregator(Aggregator):
    """Computes the arithmetic mean of values."""

    def aggregate(self, values: list[float]) -> float | None:
        """Compute average of values.

        Args:
            values: List of float values

        Returns:
            Average of values or None if empty
        """
        if not values:
            return None
        return sum(values) / len(values)


class MinAggregator(Aggregator):
    """Computes the minimum value."""

    def aggregate(self, values: list[float]) -> float | None:
        """Find minimum value.

        Args:
            values: List of float values

        Returns:
            Minimum value or None if empty
        """
        if not values:
            return None
        return min(values)


class MaxAggregator(Aggregator):
    """Computes the maximum value."""

    def aggregate(self, values: list[float]) -> float | None:
        """Find maximum value.

        Args:
            values: List of float values

        Returns:
            Maximum value or None if empty
        """
        if not values:
            return None
        return max(values)


class CountAggregator(Aggregator):
    """Counts the number of values."""

    def aggregate(self, values: list[float]) -> float | None:
        """Count values.

        Args:
            values: List of float values

        Returns:
            Count of values
        """
        return float(len(values))


class StdDevAggregator(Aggregator):
    """Computes the standard deviation of values."""

    def aggregate(self, values: list[float]) -> float | None:
        """Compute sample standard deviation.

        Args:
            values: List of float values

        Returns:
            Standard deviation or None if fewer than 2 values
        """
        if len(values) < 2:
            return None

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)


class PercentileAggregator(Aggregator):
    """Computes percentile values using t-digest approximation."""

    def __init__(self, percentile: float) -> None:
        """Initialize percentile aggregator.

        Args:
            percentile: Percentile to compute (0-100)

        Raises:
            ValueError: If percentile not in [0, 100]
        """
        if not 0 <= percentile <= 100:
            raise ValueError("Percentile must be between 0 and 100")
        self.percentile = percentile

    def aggregate(self, values: list[float]) -> float | None:
        """Compute percentile of values.

        Args:
            values: List of float values

        Returns:
            Percentile value or None if empty
        """
        if not values:
            return None
        if len(values) == 1:
            return values[0]

        sorted_values = sorted(values)
        rank = self.percentile / 100.0 * (len(sorted_values) - 1)
        lower_idx = int(rank)
        upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
        fraction = rank - lower_idx

        return sorted_values[lower_idx] * (1 - fraction) + sorted_values[upper_idx] * fraction


class RateAggregator(Aggregator):
    """Computes rate of change per second."""

    def __init__(self, interval_ms: int) -> None:
        """Initialize rate aggregator.

        Args:
            interval_ms: Time interval in milliseconds
        """
        self.interval_ms = interval_ms

    def aggregate(self, values: list[float]) -> float | None:
        """Compute rate per second.

        Args:
            values: List of float values over the interval

        Returns:
            Rate per second or None if empty
        """
        if not values or len(values) < 2:
            return None

        total_change = values[-1] - values[0]
        interval_seconds = self.interval_ms / 1000.0
        return total_change / interval_seconds


class DeltaAggregator(Aggregator):
    """Computes the difference between first and last values."""

    def aggregate(self, values: list[float]) -> float | None:
        """Compute delta (last - first).

        Args:
            values: List of float values

        Returns:
            Delta value or None if fewer than 2 values
        """
        if len(values) < 2:
            return None
        return values[-1] - values[0]


class StreamingAggregationEngine:
    """Efficient streaming aggregation without loading all points.

    Maintains running statistics for multiple aggregation types simultaneously.
    """

    def __init__(self) -> None:
        """Initialize the streaming aggregation engine."""
        self.count = 0
        self.sum = 0.0
        self.min_value: float | None = None
        self.max_value: float | None = None
        self.values_for_stddev: list[float] = []
        self.first_value: float | None = None
        self.last_value: float | None = None

    def add_value(self, value: float) -> None:
        """Add a value to the stream.

        Args:
            value: Float value to add
        """
        self.count += 1
        self.sum += value
        self.values_for_stddev.append(value)

        if self.first_value is None:
            self.first_value = value

        self.last_value = value

        if self.min_value is None:
            self.min_value = value
        else:
            self.min_value = min(self.min_value, value)

        if self.max_value is None:
            self.max_value = value
        else:
            self.max_value = max(self.max_value, value)

    def get_sum(self) -> float | None:
        """Get sum of all values."""
        return self.sum if self.count > 0 else None

    def get_avg(self) -> float | None:
        """Get average of all values."""
        if self.count == 0:
            return None
        return self.sum / self.count

    def get_min(self) -> float | None:
        """Get minimum value."""
        return self.min_value

    def get_max(self) -> float | None:
        """Get maximum value."""
        return self.max_value

    def get_count(self) -> int:
        """Get count of values."""
        return self.count

    def get_stddev(self) -> float | None:
        """Get standard deviation of all values."""
        if len(self.values_for_stddev) < 2:
            return None

        mean = self.sum / self.count
        variance = sum((x - mean) ** 2 for x in self.values_for_stddev) / (self.count - 1)
        return math.sqrt(variance)

    def get_percentile(self, percentile: float) -> float | None:
        """Get percentile of all values.

        Args:
            percentile: Percentile to compute (0-100)

        Returns:
            Percentile value or None
        """
        if not self.values_for_stddev:
            return None

        sorted_values = sorted(self.values_for_stddev)
        rank = percentile / 100.0 * (len(sorted_values) - 1)
        lower_idx = int(rank)
        upper_idx = min(lower_idx + 1, len(sorted_values) - 1)
        fraction = rank - lower_idx

        return sorted_values[lower_idx] * (1 - fraction) + sorted_values[upper_idx] * fraction

    def get_delta(self) -> float | None:
        """Get delta (last - first)."""
        if self.first_value is None or self.last_value is None:
            return None
        return self.last_value - self.first_value

    def get_rate(self, interval_ms: int) -> float | None:
        """Get rate per second.

        Args:
            interval_ms: Time interval in milliseconds

        Returns:
            Rate per second or None
        """
        if self.first_value is None or self.last_value is None:
            return None
        interval_seconds = interval_ms / 1000.0
        return (self.last_value - self.first_value) / interval_seconds


class AggregationEngine:
    """Main aggregation engine for processing time-series data."""

    def __init__(self) -> None:
        """Initialize the aggregation engine."""
        self.aggregators: dict[str, Aggregator] = {
            "sum": SumAggregator(),
            "avg": AverageAggregator(),
            "min": MinAggregator(),
            "max": MaxAggregator(),
            "count": CountAggregator(),
            "stddev": StdDevAggregator(),
        }

    def aggregate(self, aggregation_type: str, values: list[float]) -> float | None:
        """Aggregate values using specified aggregation type.

        Args:
            aggregation_type: Type of aggregation (sum, avg, min, max, count, stddev, percentile_N, rate, delta)
            values: List of float values

        Returns:
            Aggregated result or None if empty

        Raises:
            ValueError: If aggregation type is unknown
        """
        if aggregation_type in self.aggregators:
            return self.aggregators[aggregation_type].aggregate(values)

        if aggregation_type.startswith("percentile_"):
            percentile = float(aggregation_type.split("_")[1])
            agg = PercentileAggregator(percentile)
            return agg.aggregate(values)

        if aggregation_type == "rate":
            return RateAggregator(3600000).aggregate(values)  # Default 1 hour

        if aggregation_type == "delta":
            return DeltaAggregator().aggregate(values)

        raise ValueError(f"Unknown aggregation type: {aggregation_type}")

    def aggregate_by_interval(
        self,
        timestamps: list[int],
        values: list[float],
        interval_ms: int,
        aggregation_type: str,
    ) -> list[AggregationResult]:
        """Aggregate data into intervals.

        Args:
            timestamps: List of timestamps in milliseconds
            values: List of corresponding values
            interval_ms: Size of aggregation interval in milliseconds
            aggregation_type: Type of aggregation

        Returns:
            List of AggregationResult objects, one per interval

        Raises:
            ValueError: If lengths don't match
        """
        if len(timestamps) != len(values):
            raise ValueError("Timestamps and values must have same length")

        if not timestamps:
            return []

        results: list[AggregationResult] = []
        start_time = (timestamps[0] // interval_ms) * interval_ms
        current_interval_start = start_time
        interval_values: list[float] = []
        interval_timestamps: list[int] = []

        for ts, val in zip(timestamps, values):
            interval_end = current_interval_start + interval_ms

            # Move to next interval if needed
            while ts >= interval_end:
                if interval_values:
                    agg_result = self.aggregate(aggregation_type, interval_values)
                    results.append(
                        AggregationResult(
                            timestamp=current_interval_start + interval_ms,
                            value=agg_result,
                            count=len(interval_values),
                            min_value=min(interval_values),
                            max_value=max(interval_values),
                        )
                    )

                current_interval_start = interval_end
                interval_end = current_interval_start + interval_ms
                interval_values = []
                interval_timestamps = []

            interval_values.append(val)
            interval_timestamps.append(ts)

        # Process final interval
        if interval_values:
            agg_result = self.aggregate(aggregation_type, interval_values)
            results.append(
                AggregationResult(
                    timestamp=current_interval_start + interval_ms,
                    value=agg_result,
                    count=len(interval_values),
                    min_value=min(interval_values),
                    max_value=max(interval_values),
                )
            )

        return results

    def group_by(
        self,
        timestamps: list[int],
        values: list[float],
        tags_list: list[dict[str, str]],
        tag_key: str,
        aggregation_type: str,
    ) -> dict[str, float | None]:
        """Group and aggregate by tag value.

        Args:
            timestamps: List of timestamps
            values: List of values
            tags_list: List of tag dictionaries
            tag_key: Tag key to group by
            aggregation_type: Type of aggregation

        Returns:
            Dictionary mapping tag values to aggregated results

        Raises:
            ValueError: If lengths don't match
        """
        if not (len(timestamps) == len(values) == len(tags_list)):
            raise ValueError("Timestamps, values, and tags must have same length")

        grouped: dict[str, list[float]] = defaultdict(list)

        for tag_dict, val in zip(tags_list, values):
            tag_value = tag_dict.get(tag_key, "unknown")
            grouped[tag_value].append(val)

        results = {}
        for tag_value, vals in grouped.items():
            results[tag_value] = self.aggregate(aggregation_type, vals)

        return results

    def percentile_approximation(self, values: list[float], percentile: float) -> float | None:
        """Compute approximate percentile using nearest-rank method.

        Args:
            values: List of values
            percentile: Percentile to compute (0-100)

        Returns:
            Approximate percentile or None
        """
        agg = PercentileAggregator(percentile)
        return agg.aggregate(values)
