"""
Scheduler monitoring and metrics collection.

Tracks job execution statistics, health metrics, and performance data.
"""

import statistics
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from thomas.marketplace.scheduler_deep._types import Job, JobHistory, JobStatus


class HealthStatus(Enum):
    """Scheduler health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class JobStats:
    """Statistics for a single job."""

    job_id: str
    job_name: str
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_duration_seconds: float = 0.0
    min_duration_seconds: float = float("inf")
    max_duration_seconds: float = 0.0
    last_run_time: datetime | None = None
    last_status: JobStatus | None = None
    error_rate: float = 0.0
    avg_duration_seconds: float = 0.0
    next_run_time: datetime | None = None

    def update_from_history(self, history: list[JobHistory]) -> None:
        """Update stats from history records.

        Args:
            history: List of history records
        """
        self.total_runs = len(history)
        self.successful_runs = sum(1 for h in history if h.status == JobStatus.SUCCESS)
        self.failed_runs = sum(1 for h in history if h.status == JobStatus.FAILED)

        if self.total_runs > 0:
            self.error_rate = self.failed_runs / self.total_runs

        durations = [h.duration_seconds for h in history]
        if durations:
            self.total_duration_seconds = sum(durations)
            self.min_duration_seconds = min(durations)
            self.max_duration_seconds = max(durations)
            self.avg_duration_seconds = statistics.mean(durations)

        if history:
            latest = sorted(history, key=lambda h: h.executed_at)[-1]
            self.last_run_time = latest.executed_at
            self.last_status = latest.status

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "job_id": self.job_id,
            "job_name": self.job_name,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "error_rate": round(self.error_rate, 4),
            "avg_duration_seconds": round(self.avg_duration_seconds, 2),
            "min_duration_seconds": round(self.min_duration_seconds, 2),
            "max_duration_seconds": round(self.max_duration_seconds, 2),
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "last_status": self.last_status.value if self.last_status else None,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
        }


@dataclass
class SchedulerMetrics:
    """Overall scheduler metrics."""

    total_jobs: int = 0
    active_jobs: int = 0
    idle_jobs: int = 0
    paused_jobs: int = 0
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    execution_time_seconds: float = 0.0
    avg_job_duration: float = 0.0
    uptime_seconds: float = 0.0
    health_status: HealthStatus = HealthStatus.HEALTHY
    last_check_time: datetime | None = None
    job_stats: dict[str, JobStats] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "total_jobs": self.total_jobs,
            "active_jobs": self.active_jobs,
            "idle_jobs": self.idle_jobs,
            "paused_jobs": self.paused_jobs,
            "total_executions": self.total_executions,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "execution_time_seconds": round(self.execution_time_seconds, 2),
            "avg_job_duration": round(self.avg_job_duration, 2),
            "uptime_seconds": round(self.uptime_seconds, 2),
            "health_status": self.health_status.value,
            "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
        }


class SchedulerMonitor:
    """Monitor scheduler health and collect metrics."""

    def __init__(self, check_interval_seconds: int = 60) -> None:
        """Initialize monitor.

        Args:
            check_interval_seconds: Interval for health checks
        """
        self.check_interval = check_interval_seconds
        self.metrics = SchedulerMetrics()
        self._lock = threading.RLock()
        self._start_time = datetime.now(timezone.utc)
        self._failed_check_count = 0

    def record_execution(
        self,
        job: Job,
        history: JobHistory,
    ) -> None:
        """Record job execution.

        Args:
            job: Job that was executed
            history: Execution history record
        """
        with self._lock:
            self.metrics.total_executions += 1

            if history.status == JobStatus.SUCCESS:
                self.metrics.successful_executions += 1
            else:
                self.metrics.failed_executions += 1

            self.metrics.execution_time_seconds += history.duration_seconds

    def update_job_stats(self, job_id: str, history: list[JobHistory]) -> None:
        """Update statistics for a job.

        Args:
            job_id: Job ID
            history: Job execution history
        """
        with self._lock:
            if job_id not in self.metrics.job_stats:
                stats = JobStats(job_id=job_id, job_name=job_id)
            else:
                stats = self.metrics.job_stats[job_id]

            stats.update_from_history(history)
            self.metrics.job_stats[job_id] = stats

    def check_health(self, jobs: list[Job]) -> HealthStatus:
        """Check scheduler health.

        Args:
            jobs: List of all jobs

        Returns:
            Health status
        """
        with self._lock:
            self.metrics.total_jobs = len(jobs)
            self.metrics.active_jobs = sum(1 for j in jobs if j.status in (JobStatus.RUNNING,))
            self.metrics.idle_jobs = sum(1 for j in jobs if j.status == JobStatus.IDLE)
            self.metrics.paused_jobs = sum(1 for j in jobs if j.status == JobStatus.PAUSED)

            # Calculate health status
            if self.metrics.total_executions > 0:
                error_rate = self.metrics.failed_executions / self.metrics.total_executions
                if error_rate > 0.5:
                    status = HealthStatus.UNHEALTHY
                elif error_rate > 0.2:
                    status = HealthStatus.DEGRADED
                else:
                    status = HealthStatus.HEALTHY
            else:
                status = HealthStatus.HEALTHY

            self.metrics.health_status = status
            self.metrics.last_check_time = datetime.now(timezone.utc)

            # Calculate uptime
            self.metrics.uptime_seconds = (datetime.now(timezone.utc) - self._start_time).total_seconds()

            # Calculate avg duration
            if self.metrics.total_executions > 0:
                self.metrics.avg_job_duration = self.metrics.execution_time_seconds / self.metrics.total_executions

            return status

    def get_metrics(self) -> SchedulerMetrics:
        """Get current metrics.

        Returns:
            Current metrics snapshot
        """
        with self._lock:
            return self.metrics

    def get_job_stats(self, job_id: str) -> JobStats | None:
        """Get stats for specific job.

        Args:
            job_id: Job ID

        Returns:
            Job stats or None
        """
        with self._lock:
            return self.metrics.job_stats.get(job_id)

    def get_overdue_jobs(self, jobs: list[Job]) -> list[Job]:
        """Get jobs that should have run but haven't.

        Args:
            jobs: List of all jobs

        Returns:
            List of overdue jobs
        """
        now = datetime.now(timezone.utc)
        return [j for j in jobs if j.next_run and j.next_run < now and j.status != JobStatus.RUNNING]

    def get_upcoming_schedule(
        self,
        jobs: list[Job],
        hours_ahead: int = 24,
    ) -> list[tuple[str, datetime]]:
        """Get upcoming job schedule.

        Args:
            jobs: List of all jobs
            hours_ahead: Hours to look ahead

        Returns:
            List of (job_id, run_time) tuples
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)

        upcoming = [(j.id, j.next_run) for j in jobs if j.next_run and now < j.next_run < cutoff]

        return sorted(upcoming, key=lambda x: x[1])

    def export_metrics(self) -> dict[str, Any]:
        """Export all metrics.

        Returns:
            Dictionary of all metrics
        """
        with self._lock:
            return {
                "metrics": self.metrics.to_dict(),
                "job_stats": {jid: stats.to_dict() for jid, stats in self.metrics.job_stats.items()},
            }
