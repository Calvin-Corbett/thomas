"""
Metrics engine for collecting and exposing metrics.

Implements counter, gauge, histogram, and summary metric types with full
label support and Prometheus-compatible exposition format.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from thomas.monitoring._exceptions import (
    MetricError,
)
from thomas.monitoring._types import (
    Label,
    MetricType,
)


@dataclass
class HistogramBucket:
    """A bucket in a histogram."""

    le: float  # le = less than or equal
    count: int = 0

    def __lt__(self, other: "HistogramBucket") -> bool:
        return self.le < other.le


@dataclass
class HistogramSample:
    """Internal sample data for histograms."""

    value: float
    timestamp: float


@dataclass
class TDigest:
    """T-Digest algorithm for streaming percentile calculation."""

    centroids: list[tuple[float, int]] = field(default_factory=list)
    max_size: int = 200

    def add(self, value: float, weight: int = 1) -> None:
        """Add a value to the digest."""
        new_centroid = (value, weight)
        self.centroids.append(new_centroid)
        self.centroids.sort()

        if len(self.centroids) > self.max_size:
            self._compress()

    def _compress(self) -> None:
        """Compress centroids by merging nearby ones."""
        if len(self.centroids) <= self.max_size:
            return

        new_centroids: list[tuple[float, int]] = []
        i = 0

        while i < len(self.centroids):
            value, weight = self.centroids[i]
            merged_weight = weight

            # Merge with next centroids if within compression ratio
            j = i + 1
            while j < len(self.centroids):
                next_value, next_weight = self.centroids[j]
                if abs(next_value - value) < 1e-6:
                    merged_weight += next_weight
                    j += 1
                else:
                    break

            new_centroids.append((value, merged_weight))
            i = j

        # Keep only max_size centroids
        if len(new_centroids) > self.max_size:
            # Collapse contiguous centroids into weighted groups so we preserve
            # distribution mass instead of dropping every Nth centroid.
            step = max(1, (len(new_centroids) + self.max_size - 1) // self.max_size)
            compressed: list[tuple[float, int]] = []
            for i in range(0, len(new_centroids), step):
                group = new_centroids[i : i + step]
                total_weight = sum(weight for _, weight in group)
                if total_weight <= 0:
                    continue
                weighted_mean = sum(value * weight for value, weight in group) / total_weight
                compressed.append((weighted_mean, total_weight))
            new_centroids = compressed

        self.centroids = new_centroids

    def quantile(self, q: float) -> float:
        """Calculate quantile value."""
        if not self.centroids:
            return 0.0
        if q <= 0:
            return self.centroids[0][0]
        if q >= 1:
            return self.centroids[-1][0]

        total_weight = sum(w for _, w in self.centroids)
        target_weight = q * total_weight
        cumulative = 0.0

        for i, (value, weight) in enumerate(self.centroids):
            cumulative += weight
            if cumulative >= target_weight:
                if i == 0:
                    return value
                prev_value, prev_weight = self.centroids[i - 1]
                fraction = (target_weight - (cumulative - weight)) / weight
                return prev_value + fraction * (value - prev_value)

        return self.centroids[-1][0]


class Counter:
    """A monotonically increasing metric."""

    def __init__(
        self,
        name: str,
        help: str,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> None:
        self.name = name
        self.help = help
        self.labelnames = labelnames or []
        self.unit = unit
        self._lock = threading.Lock()
        self._values: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment the counter by amount."""
        if amount < 0:
            raise MetricError("Counter can only increase, not decrease")

        with self._lock:
            key = self._make_key(labels or {})
            self._values[key] += amount

    def _make_key(self, labels: dict[str, str]) -> tuple[str, ...]:
        """Create a hashable key from label dict."""
        values = []
        for name in sorted(self.labelnames):
            values.append(labels.get(name, ""))
        return tuple(values)

    def collect(self) -> list[tuple[list[Label], float]]:
        """Collect all current counter values."""
        with self._lock:
            results = []
            for key, value in self._values.items():
                labels = [Label(name, val) for name, val in zip(sorted(self.labelnames), key)]
                results.append((labels, value))
            return results


class Gauge:
    """A metric that can go up or down."""

    def __init__(
        self,
        name: str,
        help: str,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> None:
        self.name = name
        self.help = help
        self.labelnames = labelnames or []
        self.unit = unit
        self._lock = threading.Lock()
        self._values: dict[tuple[str, ...], float] = defaultdict(float)

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Set the gauge to a specific value."""
        with self._lock:
            key = self._make_key(labels or {})
            self._values[key] = value

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment the gauge by amount."""
        with self._lock:
            key = self._make_key(labels or {})
            self._values[key] += amount

    def dec(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Decrement the gauge by amount."""
        with self._lock:
            key = self._make_key(labels or {})
            self._values[key] -= amount

    def _make_key(self, labels: dict[str, str]) -> tuple[str, ...]:
        """Create a hashable key from label dict."""
        values = []
        for name in sorted(self.labelnames):
            values.append(labels.get(name, ""))
        return tuple(values)

    def collect(self) -> list[tuple[list[Label], float]]:
        """Collect all current gauge values."""
        with self._lock:
            results = []
            for key, value in self._values.items():
                labels = [Label(name, val) for name, val in zip(sorted(self.labelnames), key)]
                results.append((labels, value))
            return results


class Histogram:
    """A metric that tracks value distribution with configurable buckets."""

    def __init__(
        self,
        name: str,
        help: str,
        buckets: list[float] | None = None,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> None:
        self.name = name
        self.help = help
        self.labelnames = labelnames or []
        self.unit = unit
        self.buckets = sorted(buckets or self._default_buckets())
        self._lock = threading.Lock()
        self._observations: dict[tuple[str, ...], list[HistogramSample]] = defaultdict(list)
        self._bucket_counts: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0] * (len(self.buckets) + 1))
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)

    def _default_buckets(self) -> list[float]:
        """Default histogram buckets (similar to Prometheus)."""
        return [
            0.005,
            0.01,
            0.025,
            0.05,
            0.075,
            0.1,
            0.25,
            0.5,
            0.75,
            1.0,
            2.5,
            5.0,
            7.5,
            10.0,
        ]

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Record an observation."""
        with self._lock:
            key = self._make_key(labels or {})
            self._observations[key].append(HistogramSample(value=value, timestamp=time.time()))
            self._sums[key] += value
            self._counts[key] += 1

            # Update bucket counts
            for i, bucket in enumerate(self.buckets):
                if value <= bucket:
                    self._bucket_counts[key][i] += 1
            self._bucket_counts[key][-1] += 1  # +Inf bucket

    def _make_key(self, labels: dict[str, str]) -> tuple[str, ...]:
        """Create a hashable key from label dict."""
        values = []
        for name in sorted(self.labelnames):
            values.append(labels.get(name, ""))
        return tuple(values)

    def collect(
        self,
    ) -> list[tuple[list[Label], list[HistogramBucket], float, int]]:
        """Collect histogram data: labels, buckets, sum, count."""
        with self._lock:
            results = []
            for key in self._observations:
                labels = [Label(name, val) for name, val in zip(sorted(self.labelnames), key)]
                buckets = []
                for i, bound in enumerate(self.buckets):
                    bucket = HistogramBucket(le=bound, count=self._bucket_counts[key][i])
                    buckets.append(bucket)
                buckets.append(HistogramBucket(le=float("inf"), count=self._bucket_counts[key][-1]))

                results.append((labels, buckets, self._sums[key], self._counts[key]))
            return results


class Summary:
    """A metric with count and sum, plus streaming percentiles."""

    def __init__(
        self,
        name: str,
        help: str,
        percentiles: list[float] | None = None,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> None:
        self.name = name
        self.help = help
        self.labelnames = labelnames or []
        self.unit = unit
        self.percentiles = sorted(percentiles or [0.5, 0.9, 0.99])
        self._lock = threading.Lock()
        self._digests: dict[tuple[str, ...], TDigest] = defaultdict(TDigest)
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)
        self._counts: dict[tuple[str, ...], int] = defaultdict(int)
        self._observations: dict[tuple[str, ...], list[HistogramSample]] = defaultdict(list)

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        """Record an observation."""
        with self._lock:
            key = self._make_key(labels or {})
            self._digests[key].add(value)
            self._sums[key] += value
            self._counts[key] += 1
            self._observations[key].append(HistogramSample(value=value, timestamp=time.time()))

    def _make_key(self, labels: dict[str, str]) -> tuple[str, ...]:
        """Create a hashable key from label dict."""
        values = []
        for name in sorted(self.labelnames):
            values.append(labels.get(name, ""))
        return tuple(values)

    def collect(
        self,
    ) -> list[tuple[list[Label], dict[float, float], float, int]]:
        """Collect summary data: labels, percentiles dict, sum, count."""
        with self._lock:
            results = []
            for key in self._digests:
                labels = [Label(name, val) for name, val in zip(sorted(self.labelnames), key)]
                percentile_values = {}
                for p in self.percentiles:
                    percentile_values[p] = self._digests[key].quantile(p)

                results.append((labels, percentile_values, self._sums[key], self._counts[key]))
            return results


class MetricsRegistry:
    """Registry for all metrics in the system."""

    def __init__(self, max_cardinality: int = 100000) -> None:
        self.max_cardinality = max_cardinality
        self._lock = threading.Lock()
        self._metrics: dict[str, dict[str, any]] = {}
        self._cardinality_count = 0

    def counter(
        self,
        name: str,
        help: str,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> Counter:
        """Register or retrieve a counter metric."""
        with self._lock:
            if name in self._metrics:
                metric = self._metrics[name]
                if metric["type"] != MetricType.COUNTER:
                    raise MetricError(f"Metric {name} is already registered as {metric['type']}")
                return metric["instance"]

            counter = Counter(name, help, labelnames, unit)
            self._metrics[name] = {
                "type": MetricType.COUNTER,
                "instance": counter,
                "help": help,
            }
            return counter

    def gauge(
        self,
        name: str,
        help: str,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> Gauge:
        """Register or retrieve a gauge metric."""
        with self._lock:
            if name in self._metrics:
                metric = self._metrics[name]
                if metric["type"] != MetricType.GAUGE:
                    raise MetricError(f"Metric {name} is already registered as {metric['type']}")
                return metric["instance"]

            gauge = Gauge(name, help, labelnames, unit)
            self._metrics[name] = {
                "type": MetricType.GAUGE,
                "instance": gauge,
                "help": help,
            }
            return gauge

    def histogram(
        self,
        name: str,
        help: str,
        buckets: list[float] | None = None,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> Histogram:
        """Register or retrieve a histogram metric."""
        with self._lock:
            if name in self._metrics:
                metric = self._metrics[name]
                if metric["type"] != MetricType.HISTOGRAM:
                    raise MetricError(f"Metric {name} is already registered as {metric['type']}")
                return metric["instance"]

            histogram = Histogram(name, help, buckets, labelnames, unit)
            self._metrics[name] = {
                "type": MetricType.HISTOGRAM,
                "instance": histogram,
                "help": help,
            }
            return histogram

    def summary(
        self,
        name: str,
        help: str,
        percentiles: list[float] | None = None,
        labelnames: list[str] | None = None,
        unit: str = "",
    ) -> Summary:
        """Register or retrieve a summary metric."""
        with self._lock:
            if name in self._metrics:
                metric = self._metrics[name]
                if metric["type"] != MetricType.SUMMARY:
                    raise MetricError(f"Metric {name} is already registered as {metric['type']}")
                return metric["instance"]

            summary = Summary(name, help, percentiles, labelnames, unit)
            self._metrics[name] = {
                "type": MetricType.SUMMARY,
                "instance": summary,
                "help": help,
            }
            return summary

    def unregister(self, name: str) -> bool:
        """Unregister a metric."""
        with self._lock:
            if name in self._metrics:
                del self._metrics[name]
                return True
            return False

    def lookup(self, name: str) -> any | None:
        """Look up a metric by name."""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]["instance"]
            return None

    def get_all(self) -> dict[str, any]:
        """Get all registered metrics."""
        with self._lock:
            return {name: metric["instance"] for name, metric in self._metrics.items()}

    def exposition_format(self) -> str:
        """Generate Prometheus-compatible exposition format."""
        lines = []

        with self._lock:
            for name, metric_meta in sorted(self._metrics.items()):
                metric_type = metric_meta["type"]
                help_text = metric_meta["help"].replace("\\", "\\\\").replace("\n", "\\n")
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {metric_type.value}")

                instance = metric_meta["instance"]

                if isinstance(instance, Counter) or isinstance(instance, Gauge):
                    for labels, value in instance.collect():
                        label_str = self._format_labels(labels)
                        lines.append(f"{name}{label_str} {value}")

                elif isinstance(instance, Histogram):
                    for labels, buckets, sum_val, count in instance.collect():
                        base_name = name
                        label_str = self._format_labels(labels)
                        for bucket in buckets:
                            lines.append(f'{base_name}_bucket{{le="{bucket.le}"{label_str}}} {bucket.count}')
                        lines.append(f"{base_name}_sum{label_str} {sum_val}")
                        lines.append(f"{base_name}_count{label_str} {count}")

                elif isinstance(instance, Summary):
                    for labels, percentiles_dict, sum_val, count in instance.collect():
                        base_name = name
                        label_str = self._format_labels(labels)
                        for quantile, value in percentiles_dict.items():
                            lines.append(f'{base_name}{{quantile="{quantile}"{label_str}}} {value}')
                        lines.append(f"{base_name}_sum{label_str} {sum_val}")
                        lines.append(f"{base_name}_count{label_str} {count}")

        return "\n".join(lines) + "\n"

    def _format_labels(self, labels: list[Label]) -> str:
        """Format labels for exposition format."""
        if not labels:
            return ""
        label_pairs = [f'{label.name}="{label.value}"' for label in labels]
        return "{" + ",".join(label_pairs) + "}"
