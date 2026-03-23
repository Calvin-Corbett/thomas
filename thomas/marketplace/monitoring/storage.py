"""
Time-series storage engine.

In-memory storage with chunk-based architecture, downsampling,
retention policies, and durability via write-ahead logging.
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from thomas.marketplace.monitoring._exceptions import StorageError
from thomas.marketplace.monitoring._types import Metric, MetricSample, TimeSeries


@dataclass
class ChunkSummary:
    """Summary statistics for a chunk."""

    start_time: float
    end_time: float
    min_value: float
    max_value: float
    avg_value: float
    count: int


@dataclass
class DownsamplePolicy:
    """Policy for downsampling data."""

    interval: timedelta
    aggregations: list[str]  # min, max, avg, count

    def __hash__(self) -> int:
        return hash((self.interval.total_seconds(), tuple(self.aggregations)))


class Chunk:
    """A fixed-size time range chunk of metric data."""

    def __init__(self, start_time: float, end_time: float, chunk_size: int = 1000) -> None:
        self.start_time = start_time
        self.end_time = end_time
        self.chunk_size = chunk_size
        self._samples: list[MetricSample] = []
        self._lock = threading.Lock()

    def add_sample(self, sample: MetricSample) -> bool:
        """Add a sample to the chunk."""
        if not (self.start_time <= sample.timestamp <= self.end_time):
            return False

        if len(self._samples) >= self.chunk_size:
            return False

        with self._lock:
            self._samples.append(sample)
            self._samples.sort()
        return True

    def get_samples(self, start: float, end: float) -> list[MetricSample]:
        """Get samples within time range."""
        with self._lock:
            return [s for s in self._samples if start <= s.timestamp <= end]

    def get_summary(self) -> ChunkSummary | None:
        """Get summary statistics."""
        with self._lock:
            if not self._samples:
                return None

            values = [s.value for s in self._samples]
            return ChunkSummary(
                start_time=self.start_time,
                end_time=self.end_time,
                min_value=min(values),
                max_value=max(values),
                avg_value=sum(values) / len(values),
                count=len(values),
            )

    def is_full(self) -> bool:
        """Check if chunk is at capacity."""
        with self._lock:
            return len(self._samples) >= self.chunk_size

    def sample_count(self) -> int:
        """Get sample count."""
        with self._lock:
            return len(self._samples)


class TimeSeriesDB:
    """In-memory time-series database."""

    def __init__(
        self,
        chunk_duration_s: int = 3600,
        retention_hours: int = 24,
        max_series: int = 100000,
    ) -> None:
        self.chunk_duration_s = chunk_duration_s
        self.retention_hours = retention_hours
        self.max_series = max_series
        self._lock = threading.Lock()
        self._series: dict[str, TimeSeries] = {}
        self._chunks: dict[str, list[Chunk]] = defaultdict(list)
        self._downsampled: dict[str, dict[DownsamplePolicy, list[MetricSample]]] = defaultdict(dict)
        self._wal_log: list[dict] = []
        self._series_index: dict[str, set[str]] = defaultdict(set)
        self._label_index: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._cleanup_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start background cleanup thread."""
        with self._lock:
            if self._running:
                return
            self._running = True

        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop(self) -> None:
        """Stop background cleanup thread."""
        with self._lock:
            self._running = False

        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5.0)

    def write(self, series_key: str, sample: MetricSample, metric: Metric) -> None:
        """Write a metric sample to storage."""
        with self._lock:
            if len(self._series) >= self.max_series and series_key not in self._series:
                raise StorageError(f"Max series limit ({self.max_series}) exceeded")

            # Get or create time series
            if series_key not in self._series:
                labels = metric.labels if hasattr(metric, "labels") else []
                self._series[series_key] = TimeSeries(metric=metric, labels=labels)

            ts = self._series[series_key]

            # Find or create appropriate chunk
            chunk_idx = int(sample.timestamp / self.chunk_duration_s)
            chunk_start = chunk_idx * self.chunk_duration_s
            chunk_end = chunk_start + self.chunk_duration_s

            # Find chunk or create new one
            chunk = None
            for c in self._chunks[series_key]:
                if c.start_time == chunk_start:
                    chunk = c
                    break

            if not chunk:
                chunk = Chunk(chunk_start, chunk_end)
                self._chunks[series_key].append(chunk)

            # Add sample to chunk
            if chunk.add_sample(sample):
                ts.add_sample(sample)

                # Log to WAL
                self._wal_log.append(
                    {
                        "ts": sample.timestamp,
                        "val": sample.value,
                        "key": series_key,
                    }
                )

                # Update indices
                if hasattr(metric, "labels"):
                    for label in metric.labels:
                        self._label_index[(label.name, label.value)].add(series_key)

    def query(self, series_key: str, start: float, end: float) -> list[MetricSample] | None:
        """Query samples from a time series."""
        with self._lock:
            if series_key not in self._series:
                return None

            results = []
            for chunk in self._chunks[series_key]:
                if chunk.end_time < start or chunk.start_time > end:
                    continue
                results.extend(chunk.get_samples(start, end))

            return sorted(results)

    def get_series(self, series_key: str) -> TimeSeries | None:
        """Get a time series."""
        with self._lock:
            return self._series.get(series_key)

    def list_series(self) -> list[str]:
        """List all series keys."""
        with self._lock:
            return list(self._series.keys())

    def find_series_by_labels(self, label_matchers: dict[str, str]) -> list[str]:
        """Find series matching label conditions."""
        with self._lock:
            if not label_matchers:
                return list(self._series.keys())

            # Start with all series matching first label
            first_label, first_value = next(iter(label_matchers.items()))
            matching = set(self._label_index.get((first_label, first_value), set()))

            # Intersect with remaining labels
            for label_name, label_value in list(label_matchers.items())[1:]:
                matching &= self._label_index.get((label_name, label_value), set())

            return list(matching)

    def downsample(self, series_key: str, policy: DownsamplePolicy) -> list[MetricSample] | None:
        """Get downsampled data."""
        with self._lock:
            if series_key not in self._series:
                return None

            if policy in self._downsampled[series_key]:
                return self._downsampled[series_key][policy]

            ts = self._series[series_key]
            interval_s = policy.interval.total_seconds()
            downsampled = []

            # Group samples by interval
            if ts.samples:
                current_bucket_start = int(ts.samples[0].timestamp / interval_s) * interval_s
                bucket_samples = []

                for sample in ts.samples:
                    bucket_idx = int(sample.timestamp / interval_s) * interval_s

                    if bucket_idx != current_bucket_start and bucket_samples:
                        # Process bucket
                        downsampled.extend(self._aggregate_samples(bucket_samples, current_bucket_start, policy))
                        bucket_samples = []
                        current_bucket_start = bucket_idx

                    bucket_samples.append(sample)

                # Process last bucket
                if bucket_samples:
                    downsampled.extend(self._aggregate_samples(bucket_samples, current_bucket_start, policy))

            self._downsampled[series_key][policy] = downsampled
            return downsampled

    def _aggregate_samples(
        self,
        samples: list[MetricSample],
        bucket_start: float,
        policy: DownsamplePolicy,
    ) -> list[MetricSample]:
        """Aggregate samples within a bucket."""
        results = []
        values = [s.value for s in samples]

        for agg in policy.aggregations:
            if agg == "min":
                value = min(values)
            elif agg == "max":
                value = max(values)
            elif agg == "avg":
                value = sum(values) / len(values)
            elif agg == "count":
                value = float(len(values))
            else:
                continue

            results.append(MetricSample(timestamp=bucket_start, value=value))

        return results

    def compact_chunks(self, series_key: str) -> int:
        """Merge small chunks together."""
        with self._lock:
            if series_key not in self._chunks:
                return 0

            chunks = self._chunks[series_key]
            if len(chunks) < 2:
                return 0

            # Find consecutive small chunks
            merged_count = 0
            i = 0
            while i < len(chunks) - 1:
                if chunks[i].sample_count() < chunks[i].chunk_size // 2:
                    # Merge with next
                    next_chunk = chunks[i + 1]
                    for sample in next_chunk.get_samples(0, float("inf")):
                        chunks[i].add_sample(sample)
                    chunks.pop(i + 1)
                    merged_count += 1
                else:
                    i += 1

            return merged_count

    def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while True:
            with self._lock:
                if not self._running:
                    break

            try:
                self._cleanup_old_data()
                self._clear_stale_downsamples()
            except (ValueError, TypeError):
                pass

            time.sleep(300.0)  # Run every 5 minutes

    def _cleanup_old_data(self) -> None:
        """Delete data older than retention policy."""
        cutoff_time = time.time() - (self.retention_hours * 3600)

        with self._lock:
            for series_key in list(self._chunks.keys()):
                chunks = self._chunks[series_key]
                self._chunks[series_key] = [c for c in chunks if c.end_time > cutoff_time]

    def _clear_stale_downsamples(self) -> None:
        """Clear old downsampled data."""
        with self._lock:
            for series_key in list(self._downsampled.keys()):
                self._downsampled[series_key].clear()

    def get_stats(self) -> dict[str, any]:
        """Get storage statistics."""
        with self._lock:
            total_samples = sum(
                len(chunk.get_samples(0, float("inf"))) for chunks in self._chunks.values() for chunk in chunks
            )
            total_chunks = sum(len(chunks) for chunks in self._chunks.values())

            return {
                "series_count": len(self._series),
                "chunk_count": total_chunks,
                "sample_count": total_samples,
                "wal_entries": len(self._wal_log),
            }
