"""
Rate control and job throttling.

Manages concurrent job limits, per-job-type concurrency, and execution windows.
"""

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from thomas.scheduler_deep._exceptions import RateLimitExceeded


@dataclass
class ExecutionWindow:
    """Time window for job execution."""

    start_time: time
    end_time: time
    days_of_week: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4, 5, 6})

    def is_active(self, dt: datetime) -> bool:
        """Check if datetime is within window.

        Args:
            dt: Datetime to check

        Returns:
            True if within window
        """
        if dt.weekday() not in self.days_of_week:
            return False
        return self.start_time <= dt.time() < self.end_time


@dataclass
class BlackoutPeriod:
    """Period when jobs should not run."""

    start_time: datetime
    end_time: datetime
    reason: str = ""

    def is_active(self, dt: datetime) -> bool:
        """Check if datetime is within blackout.

        Args:
            dt: Datetime to check

        Returns:
            True if within blackout period
        """
        return self.start_time <= dt <= self.end_time


class RateControl:
    """Manages job execution rates and concurrency."""

    def __init__(
        self,
        max_concurrent_jobs: int = 10,
        max_queue_size: int | None = None,
    ) -> None:
        """Initialize rate control.

        Args:
            max_concurrent_jobs: Maximum concurrent jobs
            max_queue_size: Maximum queued jobs (None = unlimited)
        """
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_queue_size = max_queue_size
        self._running_jobs: set[str] = set()
        self._queued_jobs: dict[str, list[str]] = defaultdict(list)
        self._job_type_limits: dict[str, int] = {}
        self._job_type_running: dict[str, int] = defaultdict(int)
        self._execution_windows: dict[str, list[ExecutionWindow]] = {}
        self._blackout_periods: list[BlackoutPeriod] = []
        self._lock = threading.RLock()

    def set_job_type_limit(self, job_type: str, limit: int) -> None:
        """Set concurrent limit for job type.

        Args:
            job_type: Type identifier
            limit: Maximum concurrent instances
        """
        with self._lock:
            self._job_type_limits[job_type] = limit

    def set_execution_window(
        self,
        job_id: str,
        window: ExecutionWindow,
    ) -> None:
        """Set execution window for job.

        Args:
            job_id: Job ID
            window: Execution window
        """
        with self._lock:
            if job_id not in self._execution_windows:
                self._execution_windows[job_id] = []
            self._execution_windows[job_id].append(window)

    def add_blackout_period(self, period: BlackoutPeriod) -> None:
        """Add blackout period.

        Args:
            period: Blackout period to add
        """
        with self._lock:
            self._blackout_periods.append(period)

    def remove_blackout_period(self, period: BlackoutPeriod) -> None:
        """Remove blackout period.

        Args:
            period: Blackout period to remove
        """
        with self._lock:
            self._blackout_periods = [p for p in self._blackout_periods if p.start_time != period.start_time]

    def can_run(self, job_id: str, job_type: str | None = None) -> bool:
        """Check if job can run now.

        Args:
            job_id: Job ID
            job_type: Optional job type for type-specific limits

        Returns:
            True if job can run
        """
        with self._lock:
            # Check global concurrent limit
            if len(self._running_jobs) >= self.max_concurrent_jobs:
                return False

            # Check job-type limit
            if job_type and job_type in self._job_type_limits:
                if self._job_type_running[job_type] >= self._job_type_limits[job_type]:
                    return False

            # Check execution window
            if job_id in self._execution_windows:
                now = datetime.now(timezone.utc)
                if not any(w.is_active(now) for w in self._execution_windows[job_id]):
                    return False

            # Check blackout periods
            now = datetime.now(timezone.utc)
            if any(p.is_active(now) for p in self._blackout_periods):
                return False

            return True

    def acquire(
        self,
        job_id: str,
        job_type: str | None = None,
    ) -> bool:
        """Try to acquire execution slot.

        Args:
            job_id: Job ID
            job_type: Optional job type

        Returns:
            True if acquired

        Raises:
            RateLimitExceeded: If queued jobs exceed limit
        """
        with self._lock:
            if not self.can_run(job_id, job_type):
                # Check queue limit
                queue_size = sum(len(v) for v in self._queued_jobs.values())
                if self.max_queue_size and queue_size >= self.max_queue_size:
                    raise RateLimitExceeded(job_id, "queue_limit")

                # Add to queue
                self._queued_jobs[job_type or "default"].append(job_id)
                return False

            self._running_jobs.add(job_id)
            if job_type:
                self._job_type_running[job_type] += 1
            return True

    def release(
        self,
        job_id: str,
        job_type: str | None = None,
    ) -> None:
        """Release execution slot.

        Args:
            job_id: Job ID
            job_type: Optional job type
        """
        with self._lock:
            self._running_jobs.discard(job_id)
            if job_type:
                self._job_type_running[job_type] = max(0, self._job_type_running[job_type] - 1)

            # Try to run queued jobs
            for queue_type, queued in list(self._queued_jobs.items()):
                if queued and self.can_run(queued[0], queue_type):
                    next_job = queued.pop(0)
                    self._running_jobs.add(next_job)
                    if queue_type != "default":
                        self._job_type_running[queue_type] += 1

    def get_running_count(self) -> int:
        """Get count of running jobs.

        Returns:
            Number of running jobs
        """
        with self._lock:
            return len(self._running_jobs)

    def get_queued_count(self) -> int:
        """Get count of queued jobs.

        Returns:
            Number of queued jobs
        """
        with self._lock:
            return sum(len(v) for v in self._queued_jobs.values())

    def get_job_type_running(self, job_type: str) -> int:
        """Get count of running jobs of type.

        Args:
            job_type: Job type

        Returns:
            Count of running jobs
        """
        with self._lock:
            return self._job_type_running[job_type]

    def is_in_blackout(self) -> bool:
        """Check if currently in blackout period.

        Returns:
            True if in blackout
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            return any(p.is_active(now) for p in self._blackout_periods)

    def get_blackout_remaining(self) -> timedelta | None:
        """Get time until blackout ends.

        Returns:
            Time remaining or None if not in blackout
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            for period in self._blackout_periods:
                if period.is_active(now):
                    return period.end_time - now
            return None

    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return (
                f"RateControl("
                f"running={len(self._running_jobs)}/{self.max_concurrent_jobs}, "
                f"queued={self.get_queued_count()})"
            )
