"""
Queue monitoring and health metrics collection.

Provides monitoring for:
- Queue depth and size metrics
- Worker utilization
- Task throughput and latency
- Failed task rate
- Stuck task detection
- Health checks
"""

import threading
from collections import deque
from datetime import datetime
from typing import Any

from thomas.marketplace.task_queue.queue import TaskQueue


class QueueMonitor:
    """
    Monitors queue and worker metrics.

    Tracks queue depth, task throughput, latency percentiles,
    worker utilization, and health status.
    """

    def __init__(
        self,
        queue: TaskQueue | None = None,
        window_size: int = 1000,
    ) -> None:
        """
        Initialize a QueueMonitor.

        Args:
            queue: Optional TaskQueue to monitor.
            window_size: Number of task executions to track for percentiles.
        """
        self.queue: TaskQueue | None = queue
        self.window_size: int = window_size

        self._lock: threading.RLock = threading.RLock()
        self._start_time: datetime = datetime.utcnow()

        # Execution metrics
        self._task_executions: deque[float] = deque(maxlen=window_size)
        self._task_failures: deque[tuple[str, str]] = deque(maxlen=window_size)
        self._task_count: int = 0
        self._error_count: int = 0

        # Queue metrics
        self._queue_depth_samples: deque[int] = deque(maxlen=60)
        self._timestamps: deque[datetime] = deque(maxlen=60)

        # Task timing
        self._task_start_times: dict[str, datetime] = {}

    def record_task_start(self, task_id: str) -> None:
        """
        Record the start of a task execution.

        Args:
            task_id: ID of the task.
        """
        with self._lock:
            self._task_start_times[task_id] = datetime.utcnow()

    def record_task_completion(
        self,
        task_id: str,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        """
        Record task completion.

        Args:
            task_id: ID of the task.
            success: Whether task succeeded.
            error: Error message if failed.
        """
        with self._lock:
            self._task_count += 1

            # Record execution time
            if task_id in self._task_start_times:
                start = self._task_start_times.pop(task_id)
                execution_time = (datetime.utcnow() - start).total_seconds()
                self._task_executions.append(execution_time)

            # Record failure
            if not success and error:
                self._error_count += 1
                self._task_failures.append((task_id, error))

    def record_queue_depth(self) -> None:
        """Sample current queue depth."""
        with self._lock:
            if self.queue:
                self._queue_depth_samples.append(self.queue.size())
                self._timestamps.append(datetime.utcnow())

    def get_task_throughput(self) -> float:
        """
        Get tasks per second throughput.

        Returns:
            Tasks executed per second.
        """
        with self._lock:
            elapsed = (datetime.utcnow() - self._start_time).total_seconds()
            if elapsed == 0:
                return 0.0
            return self._task_count / elapsed

    def get_error_rate(self) -> float:
        """
        Get percentage of failed tasks.

        Returns:
            Failure rate as percentage (0-100).
        """
        with self._lock:
            if self._task_count == 0:
                return 0.0
            return (self._error_count / self._task_count) * 100

    def get_latency_percentile(self, percentile: int) -> float:
        """
        Get latency at a specific percentile.

        Args:
            percentile: Percentile value (0-100).

        Returns:
            Latency in seconds at that percentile.
        """
        with self._lock:
            if not self._task_executions:
                return 0.0

            sorted_times = sorted(list(self._task_executions))
            idx = int(len(sorted_times) * percentile / 100)
            return sorted_times[min(idx, len(sorted_times) - 1)]

    def get_latency_stats(self) -> dict[str, float]:
        """
        Get latency statistics.

        Returns:
            Dictionary with min, max, avg, p50, p95, p99.
        """
        with self._lock:
            if not self._task_executions:
                return {
                    "min": 0.0,
                    "max": 0.0,
                    "avg": 0.0,
                    "p50": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                }

            times = list(self._task_executions)
            sorted_times = sorted(times)

            return {
                "min": sorted_times[0],
                "max": sorted_times[-1],
                "avg": sum(times) / len(times),
                "p50": sorted_times[len(sorted_times) // 2],
                "p95": sorted_times[int(len(sorted_times) * 0.95)],
                "p99": sorted_times[int(len(sorted_times) * 0.99)],
            }

    def get_avg_queue_depth(self) -> float:
        """Get average queue depth over recent samples."""
        with self._lock:
            if not self._queue_depth_samples:
                return 0.0
            return sum(self._queue_depth_samples) / len(self._queue_depth_samples)

    def get_recent_failures(self, limit: int = 10) -> list[tuple[str, str]]:
        """
        Get recent task failures.

        Args:
            limit: Maximum number to return.

        Returns:
            List of (task_id, error_message) tuples.
        """
        with self._lock:
            return list(self._task_failures)[-limit:]

    def get_stuck_tasks(self, timeout_seconds: float = 300.0) -> list[str]:
        """
        Get tasks that appear to be stuck/running too long.

        Args:
            timeout_seconds: Time after which a task is considered stuck.

        Returns:
            List of task IDs that have exceeded timeout.
        """
        with self._lock:
            now = datetime.utcnow()
            stuck = [
                task_id
                for task_id, start_time in self._task_start_times.items()
                if (now - start_time).total_seconds() > timeout_seconds
            ]
            return stuck

    def get_health_status(self) -> dict[str, Any]:
        """
        Get overall health status.

        Returns:
            Dictionary with health metrics.
        """
        with self._lock:
            return {
                "uptime_seconds": (datetime.utcnow() - self._start_time).total_seconds(),
                "total_tasks": self._task_count,
                "total_errors": self._error_count,
                "error_rate_percent": self.get_error_rate(),
                "throughput_tps": self.get_task_throughput(),
                "avg_queue_depth": self.get_avg_queue_depth(),
                "stuck_tasks": len(self.get_stuck_tasks()),
            }

    def get_metrics_summary(self) -> dict[str, Any]:
        """
        Get comprehensive metrics summary.

        Returns:
            Dictionary with all relevant metrics.
        """
        return {
            "health": self.get_health_status(),
            "latency": self.get_latency_stats(),
            "recent_failures": self.get_recent_failures(),
            "stuck_tasks": self.get_stuck_tasks(),
        }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            self._task_executions.clear()
            self._task_failures.clear()
            self._task_count = 0
            self._error_count = 0
            self._queue_depth_samples.clear()
            self._timestamps.clear()
            self._task_start_times.clear()
            self._start_time = datetime.utcnow()

    def __repr__(self) -> str:
        return (
            f"QueueMonitor(tasks={self._task_count}, errors={self._error_count}, "
            f"throughput={self.get_task_throughput():.2f} tps)"
        )
