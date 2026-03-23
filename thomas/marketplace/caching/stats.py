"""Cache statistics collection and analysis."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class LatencyMetrics:
    """Latency statistics in milliseconds.

    Attributes:
        p50: 50th percentile (median).
        p95: 95th percentile.
        p99: 99th percentile.
        max: Maximum observed latency.
        avg: Average latency.
    """

    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    max: float = 0.0
    avg: float = 0.0

    def __str__(self) -> str:
        """String representation."""
        return (
            f"LatencyMetrics(p50={self.p50:.2f}ms, p95={self.p95:.2f}ms, "
            f"p99={self.p99:.2f}ms, max={self.max:.2f}ms, avg={self.avg:.2f}ms)"
        )


class StatsCollector:
    """Collects and analyzes cache statistics.

    Tracks hit rates, miss rates, eviction rates, latency percentiles,
    and memory usage. Supports rolling window statistics.

    Attributes:
        window_size: Number of operations to track in rolling window.
    """

    def __init__(self, window_size: int = 1000) -> None:
        """Initialize the statistics collector.

        Args:
            window_size: Size of the rolling window for percentile calculations.
        """
        self.window_size = window_size
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._ttl_expirations = 0
        self._latencies: deque[float] = deque(maxlen=window_size)
        self._hit_latencies: deque[float] = deque(maxlen=window_size)
        self._miss_latencies: deque[float] = deque(maxlen=window_size)
        self._memory_usage: deque[int] = deque(maxlen=window_size)
        self._entry_counts: deque[int] = deque(maxlen=window_size)
        self._timestamps: deque[datetime] = deque(maxlen=window_size)
        self._lock = threading.RLock()

    def record_hit(self, latency_ms: float) -> None:
        """Record a cache hit.

        Args:
            latency_ms: Hit latency in milliseconds.
        """
        with self._lock:
            self._hits += 1
            self._latencies.append(latency_ms)
            self._hit_latencies.append(latency_ms)
            self._timestamps.append(datetime.utcnow())

    def record_miss(self, latency_ms: float) -> None:
        """Record a cache miss.

        Args:
            latency_ms: Miss latency in milliseconds.
        """
        with self._lock:
            self._misses += 1
            self._latencies.append(latency_ms)
            self._miss_latencies.append(latency_ms)
            self._timestamps.append(datetime.utcnow())

    def record_eviction(self) -> None:
        """Record a cache eviction."""
        with self._lock:
            self._evictions += 1

    def record_ttl_expiration(self) -> None:
        """Record a TTL expiration."""
        with self._lock:
            self._ttl_expirations += 1

    def record_memory_usage(self, size_bytes: int, entry_count: int) -> None:
        """Record current memory usage.

        Args:
            size_bytes: Current cache size in bytes.
            entry_count: Current number of entries.
        """
        with self._lock:
            self._memory_usage.append(size_bytes)
            self._entry_counts.append(entry_count)

    def hit_rate(self) -> float:
        """Calculate the current hit rate.

        Returns:
            Hit rate between 0.0 and 1.0.
        """
        with self._lock:
            total = self._hits + self._misses
            return self._hits / total if total > 0 else 0.0

    def miss_rate(self) -> float:
        """Calculate the current miss rate.

        Returns:
            Miss rate between 0.0 and 1.0.
        """
        return 1.0 - self.hit_rate()

    def eviction_rate(self) -> float:
        """Calculate evictions per operation.

        Returns:
            Eviction rate as a ratio.
        """
        with self._lock:
            total_ops = self._hits + self._misses
            return self._evictions / total_ops if total_ops > 0 else 0.0

    def get_hit_count(self) -> int:
        """Get total hit count."""
        with self._lock:
            return self._hits

    def get_miss_count(self) -> int:
        """Get total miss count."""
        with self._lock:
            return self._misses

    def get_eviction_count(self) -> int:
        """Get total eviction count."""
        with self._lock:
            return self._evictions

    def get_ttl_expiration_count(self) -> int:
        """Get total TTL expiration count."""
        with self._lock:
            return self._ttl_expirations

    def get_latency_metrics(self) -> LatencyMetrics:
        """Calculate latency statistics.

        Returns:
            LatencyMetrics with percentiles and averages.
        """
        with self._lock:
            if not self._latencies:
                return LatencyMetrics()

            sorted_latencies = sorted(self._latencies)
            n = len(sorted_latencies)

            p50_idx = int(n * 0.50)
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)

            return LatencyMetrics(
                p50=sorted_latencies[p50_idx],
                p95=sorted_latencies[p95_idx],
                p99=sorted_latencies[p99_idx],
                max=max(sorted_latencies),
                avg=sum(sorted_latencies) / n,
            )

    def get_hit_latency_metrics(self) -> LatencyMetrics:
        """Calculate latency statistics for hits only.

        Returns:
            LatencyMetrics for hit operations.
        """
        with self._lock:
            if not self._hit_latencies:
                return LatencyMetrics()

            sorted_latencies = sorted(self._hit_latencies)
            n = len(sorted_latencies)

            p50_idx = int(n * 0.50)
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)

            return LatencyMetrics(
                p50=sorted_latencies[p50_idx],
                p95=sorted_latencies[p95_idx],
                p99=sorted_latencies[p99_idx],
                max=max(sorted_latencies),
                avg=sum(sorted_latencies) / n,
            )

    def get_miss_latency_metrics(self) -> LatencyMetrics:
        """Calculate latency statistics for misses only.

        Returns:
            LatencyMetrics for miss operations.
        """
        with self._lock:
            if not self._miss_latencies:
                return LatencyMetrics()

            sorted_latencies = sorted(self._miss_latencies)
            n = len(sorted_latencies)

            p50_idx = int(n * 0.50)
            p95_idx = int(n * 0.95)
            p99_idx = int(n * 0.99)

            return LatencyMetrics(
                p50=sorted_latencies[p50_idx],
                p95=sorted_latencies[p95_idx],
                p99=sorted_latencies[p99_idx],
                max=max(sorted_latencies),
                avg=sum(sorted_latencies) / n,
            )

    def get_average_memory_usage(self) -> int:
        """Get average memory usage from the window.

        Returns:
            Average size in bytes.
        """
        with self._lock:
            if not self._memory_usage:
                return 0
            return sum(self._memory_usage) // len(self._memory_usage)

    def get_average_entry_count(self) -> int:
        """Get average number of entries from the window.

        Returns:
            Average entry count.
        """
        with self._lock:
            if not self._entry_counts:
                return 0
            return sum(self._entry_counts) // len(self._entry_counts)

    def reset(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._ttl_expirations = 0
            self._latencies.clear()
            self._hit_latencies.clear()
            self._miss_latencies.clear()
            self._memory_usage.clear()
            self._entry_counts.clear()
            self._timestamps.clear()
            logger.info("Statistics reset")

    def summary(self) -> str:
        """Get a summary of statistics.

        Returns:
            Formatted statistics summary.
        """
        with self._lock:
            latency_metrics = self.get_latency_metrics()
            avg_mem = self.get_average_memory_usage()

            return (
                f"Stats: hits={self._hits}, misses={self._misses}, "
                f"hit_rate={self.hit_rate():.2%}, evictions={self._evictions}, "
                f"ttl_expirations={self._ttl_expirations}, "
                f"avg_memory={avg_mem} bytes, "
                f"latency={latency_metrics}"
            )
