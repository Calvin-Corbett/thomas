"""Job scheduling system with cron, one-shot, recurring, dependencies, and retries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Job execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class JobExecution:
    """Single job execution."""

    execution_id: str
    job_id: str
    status: JobStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    output: Any = None
    error: str | None = None
    retry_count: int = 0

    @property
    def duration_seconds(self) -> float:
        """Get execution duration."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0


@dataclass
class JobDefinition:
    """Job definition."""

    job_id: str
    name: str
    job_type: str  # "one_shot", "recurring", "cron"
    handler: Callable | None = None
    schedule: str | None = None  # Cron expression or frequency
    max_retries: int = 0
    timeout_seconds: int = 300
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Job:
    """Scheduled job."""

    def __init__(self, definition: JobDefinition):
        self.definition = definition
        self.executions: list[JobExecution] = []
        self.next_run: datetime | None = None
        self.last_run: datetime | None = None

    def add_execution(self, execution: JobExecution) -> None:
        """Record execution."""
        self.executions.append(execution)
        self.last_run = execution.end_time

    def get_latest_execution(self) -> JobExecution | None:
        """Get most recent execution."""
        return self.executions[-1] if self.executions else None

    def get_success_rate(self) -> float:
        """Get job success rate."""
        if not self.executions:
            return 0.0
        successful = sum(1 for e in self.executions if e.status == JobStatus.SUCCESS)
        return successful / len(self.executions)

    def get_stats(self) -> dict[str, Any]:
        """Get job statistics."""
        return {
            "job_id": self.definition.job_id,
            "name": self.definition.name,
            "total_executions": len(self.executions),
            "success_rate": self.get_success_rate(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
        }


class JobDependencyResolver:
    """Resolve job dependencies."""

    def __init__(self, jobs: dict[str, Job]):
        self.jobs = jobs

    def get_dependency_order(self, job_id: str) -> list[str]:
        """Get execution order for job and its dependencies."""
        visited = set()
        order = []

        def visit(jid):
            if jid in visited:
                return
            visited.add(jid)

            job = self.jobs.get(jid)
            if job:
                for dep in job.definition.dependencies:
                    visit(dep)
                order.append(jid)

        visit(job_id)
        return order

    def is_ready(self, job_id: str) -> bool:
        """Check if job dependencies are satisfied."""
        job = self.jobs.get(job_id)
        if not job:
            return False

        for dep_id in job.definition.dependencies:
            dep_job = self.jobs.get(dep_id)
            if not dep_job:
                return False

            latest = dep_job.get_latest_execution()
            if not latest or latest.status != JobStatus.SUCCESS:
                return False

        return True

    def find_deadlock(self) -> list[str] | None:
        """Find circular dependencies."""
        for job_id in self.jobs:
            visited = set()
            current = job_id

            while current:
                if current in visited:
                    return [current, job_id]  # Cycle found
                visited.add(current)

                job = self.jobs.get(current)
                if not job or not job.definition.dependencies:
                    break
                current = job.definition.dependencies[0]

        return None


class Scheduler:
    """Job scheduler."""

    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.dependency_resolver: JobDependencyResolver | None = None
        self._job_counter = 0
        self._execution_counter = 0

    def register_job(self, definition: JobDefinition) -> str:
        """Register a job."""
        if definition.job_id in self.jobs:
            raise ValueError(f"Job {definition.job_id} already exists")

        job = Job(definition)
        self.jobs[definition.job_id] = job
        self.dependency_resolver = JobDependencyResolver(self.jobs)
        return definition.job_id

    def schedule_job(self, job_id: str, run_at: datetime | None = None) -> None:
        """Schedule job execution."""
        job = self.jobs.get(job_id)
        if not job:
            return

        if run_at is None:
            run_at = datetime.now()

        job.next_run = run_at

    def get_job(self, job_id: str) -> Job | None:
        """Get job by ID."""
        return self.jobs.get(job_id)

    def get_ready_jobs(self) -> list[str]:
        """Get jobs ready to execute."""
        ready = []
        now = datetime.now()

        for job_id, job in self.jobs.items():
            if not job.definition.enabled:
                continue

            if job.next_run and job.next_run <= now:
                if self.dependency_resolver and self.dependency_resolver.is_ready(job_id):
                    ready.append(job_id)

        return ready

    async def execute_job(self, job_id: str) -> JobExecution:
        """Execute a job."""
        job = self.jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        self._execution_counter += 1
        execution = JobExecution(
            execution_id=f"exec_{self._execution_counter}",
            job_id=job_id,
            status=JobStatus.RUNNING,
            start_time=datetime.now(),
        )

        try:
            if job.definition.handler:
                execution.output = await job.definition.handler()
            execution.status = JobStatus.SUCCESS
        except Exception as e:
            execution.error = str(e)
            execution.status = JobStatus.FAILED

        execution.end_time = datetime.now()
        job.add_execution(execution)

        # Schedule next run if recurring
        if job.definition.job_type == "recurring":
            job.next_run = datetime.now() + timedelta(minutes=5)

        return execution

    def get_scheduler_stats(self) -> dict[str, Any]:
        """Get scheduler statistics."""
        stats = {
            "total_jobs": len(self.jobs),
            "enabled_jobs": sum(1 for j in self.jobs.values() if j.definition.enabled),
            "total_executions": sum(len(j.executions) for j in self.jobs.values()),
            "job_stats": {jid: job.get_stats() for jid, job in self.jobs.items()},
        }
        return stats
