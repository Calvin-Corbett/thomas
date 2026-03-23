"""ETL monitoring with job tracking, SLA alerts, and data freshness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Job status values."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class JobMetrics:
    """Job execution metrics."""

    job_id: str
    start_time: datetime
    end_time: datetime | None = None
    status: JobStatus = JobStatus.PENDING
    rows_processed: int = 0
    rows_failed: int = 0
    error_message: str | None = None

    @property
    def duration_seconds(self) -> float:
        """Get job duration in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()

    @property
    def throughput(self) -> float:
        """Get rows per second."""
        duration = self.duration_seconds
        return self.rows_processed / duration if duration > 0 else 0.0


@dataclass
class SLAPolicy:
    """Service Level Agreement policy."""

    name: str
    max_duration_minutes: int
    min_throughput_rps: float = 0.0
    max_failures_per_run: int = 0
    data_freshness_hours: int = 24


class ETLJob:
    """ETL job with metadata and lineage."""

    def __init__(self, job_id: str, name: str, source: str, target: str):
        self.job_id = job_id
        self.name = name
        self.source = source
        self.target = target
        self.executions: list[JobMetrics] = []
        self.sla: SLAPolicy | None = None
        self.last_success: datetime | None = None
        self.lineage_deps: list[str] = []

    def add_execution(self, metrics: JobMetrics) -> None:
        """Record job execution."""
        self.executions.append(metrics)
        if metrics.status == JobStatus.SUCCESS:
            self.last_success = metrics.end_time

    def get_latest_execution(self) -> JobMetrics | None:
        """Get most recent execution."""
        return self.executions[-1] if self.executions else None

    def check_sla(self) -> dict[str, bool]:
        """Check if job meets SLA."""
        if not self.sla or not self.executions:
            return {"meets_sla": True}

        latest = self.get_latest_execution()
        if not latest:
            return {"meets_sla": True}

        checks = {
            "duration_ok": latest.duration_seconds <= self.sla.max_duration_minutes * 60,
            "throughput_ok": latest.throughput >= self.sla.min_throughput_rps,
            "failures_ok": latest.rows_failed <= self.sla.max_failures_per_run,
        }
        checks["meets_sla"] = all(checks.values())
        return checks

    def get_stats(self) -> dict[str, Any]:
        """Get job statistics."""
        if not self.executions:
            return {"executions": 0}

        successful = [e for e in self.executions if e.status == JobStatus.SUCCESS]
        failed = [e for e in self.executions if e.status == JobStatus.FAILED]

        return {
            "total_executions": len(self.executions),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": len(successful) / len(self.executions) if self.executions else 0.0,
            "total_rows": sum(e.rows_processed for e in self.executions),
            "avg_duration": sum(e.duration_seconds for e in self.executions) / len(self.executions)
            if self.executions
            else 0.0,
            "last_success": self.last_success.isoformat() if self.last_success else None,
        }


@dataclass
class DataFreshness:
    """Data freshness metrics."""

    dataset_id: str
    last_updated: datetime
    max_age_hours: int

    @property
    def age_hours(self) -> float:
        """Get age of data in hours."""
        return (datetime.now() - self.last_updated).total_seconds() / 3600

    @property
    def is_fresh(self) -> bool:
        """Check if data is fresh."""
        return self.age_hours <= self.max_age_hours

    @property
    def freshness_percentage(self) -> float:
        """Get freshness as percentage (100 = fresh, 0 = stale)."""
        freshness = max(0, 1.0 - (self.age_hours / self.max_age_hours))
        return freshness * 100


class MonitoringStore:
    """Store for monitoring data."""

    def __init__(self):
        self.jobs: dict[str, ETLJob] = {}
        self.freshness: dict[str, DataFreshness] = {}
        self.alerts: list[dict[str, Any]] = []

    def register_job(self, job: ETLJob) -> None:
        """Register an ETL job."""
        self.jobs[job.job_id] = job

    def record_execution(self, job_id: str, metrics: JobMetrics) -> None:
        """Record job execution metrics."""
        if job_id in self.jobs:
            self.jobs[job_id].add_execution(metrics)
            self._check_alerts(job_id)

    def register_dataset(self, dataset_id: str, max_age_hours: int) -> None:
        """Register a dataset for freshness monitoring."""
        self.freshness[dataset_id] = DataFreshness(
            dataset_id=dataset_id, last_updated=datetime.now(), max_age_hours=max_age_hours
        )

    def update_freshness(self, dataset_id: str) -> None:
        """Update dataset freshness timestamp."""
        if dataset_id in self.freshness:
            self.freshness[dataset_id].last_updated = datetime.now()

    def get_stale_datasets(self) -> list[str]:
        """Get datasets older than max age."""
        stale = []
        for dataset_id, freshness in self.freshness.items():
            if not freshness.is_fresh:
                stale.append(dataset_id)
        return stale

    def _check_alerts(self, job_id: str) -> None:
        """Check if job should trigger alerts."""
        job = self.jobs.get(job_id)
        if not job or not job.sla:
            return

        sla_check = job.check_sla()
        if not sla_check.get("meets_sla", True):
            self.alerts.append(
                {
                    "timestamp": datetime.now().isoformat(),
                    "job_id": job_id,
                    "type": "sla_violation",
                    "details": sla_check,
                }
            )

    def get_alerts(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent alerts."""
        return self.alerts[-limit:]

    def get_job_lineage(self, job_id: str) -> dict[str, Any]:
        """Get job lineage information."""
        job = self.jobs.get(job_id)
        if not job:
            return {}

        return {"job_id": job.job_id, "source": job.source, "target": job.target, "dependencies": job.lineage_deps}

    def get_summary(self) -> dict[str, Any]:
        """Get monitoring summary."""
        return {
            "total_jobs": len(self.jobs),
            "total_datasets": len(self.freshness),
            "stale_datasets": len(self.get_stale_datasets()),
            "recent_alerts": len(self.alerts[-10:]),
            "job_stats": {jid: job.get_stats() for jid, job in self.jobs.items()},
        }
