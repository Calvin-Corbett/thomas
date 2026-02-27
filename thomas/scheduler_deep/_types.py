"""
Core type definitions for the scheduler system.

Defines job, trigger, and configuration data structures with full type annotations.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class JobStatus(Enum):
    """Job execution status enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class JobHistory:
    """Record of a job execution attempt."""

    job_id: str
    executed_at: datetime
    status: JobStatus
    duration_seconds: float
    result: Any = None
    error: str | None = None
    node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert history record to dictionary."""
        return {
            "job_id": self.job_id,
            "executed_at": self.executed_at.isoformat(),
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "node_id": self.node_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobHistory":
        """Create history record from dictionary."""
        return cls(
            job_id=data["job_id"],
            executed_at=datetime.fromisoformat(data["executed_at"]),
            status=JobStatus(data["status"]),
            duration_seconds=data["duration_seconds"],
            result=data.get("result"),
            error=data.get("error"),
            node_id=data.get("node_id"),
        )


@dataclass
class Calendar:
    """Calendar configuration for business days/hours."""

    holidays: set[datetime] = field(default_factory=set)
    business_start_hour: int = 9
    business_end_hour: int = 17
    business_days: set[int] = field(default_factory=lambda: {0, 1, 2, 3, 4})
    timezone: str = "UTC"

    def is_business_day(self, date: datetime) -> bool:
        """Check if date is a business day."""
        if date.date() in {h.date() for h in self.holidays}:
            return False
        return date.weekday() in self.business_days

    def is_business_hours(self, dt: datetime) -> bool:
        """Check if datetime is during business hours."""
        if not self.is_business_day(dt):
            return False
        return self.business_start_hour <= dt.hour < self.business_end_hour


@dataclass
class SchedulerConfig:
    """Scheduler configuration."""

    max_concurrent_jobs: int = 10
    job_timeout_seconds: int = 3600
    persistence_enabled: bool = True
    persistence_path: str | None = None
    max_history_records: int = 10000
    timezone: str = "UTC"
    graceful_shutdown_timeout: int = 30
    enable_monitoring: bool = True
    distributed_mode: bool = False
    leader_election_interval: int = 10
    heartbeat_interval: int = 5
    heartbeat_timeout: int = 15

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return asdict(self)


class Trigger:
    """Base class for job triggers."""

    def __init__(self, name: str, timezone: str = "UTC") -> None:
        """Initialize trigger.

        Args:
            name: Unique trigger identifier
            timezone: Timezone for time calculations
        """
        self.name: str = name
        self.timezone: str = timezone

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if job should run now.

        Args:
            last_run: Last execution time or None

        Returns:
            True if job should run
        """
        raise NotImplementedError

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Calculate next run time.

        Args:
            from_time: Base time for calculation

        Returns:
            Next execution time or None if no future occurrence
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(name={self.name})"


@dataclass
class CronTrigger(Trigger):
    """Cron-based trigger for scheduled jobs."""

    expression: str = "0 0 * * *"
    use_utc: bool = False

    def __init__(
        self,
        expression: str = "0 0 * * *",
        name: str = "cron",
        timezone: str = "UTC",
        use_utc: bool = False,
    ) -> None:
        """Initialize cron trigger.

        Args:
            expression: 5-field cron expression
            name: Trigger name
            timezone: Timezone for scheduling
            use_utc: Use UTC instead of local time
        """
        super().__init__(name, timezone)
        self.expression = expression
        self.use_utc = use_utc

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if job should run based on cron expression."""
        # Imported here to avoid circular dependency
        from thomas.scheduler_deep.cron import CronExpression

        cron = CronExpression(self.expression, self.timezone)
        now = datetime.now(timezone.utc if self.use_utc else None)
        return cron.matches(now)

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next cron occurrence."""
        from thomas.scheduler_deep.cron import CronExpression

        cron = CronExpression(self.expression, self.timezone)
        return cron.next_occurrence(from_time)


@dataclass
class IntervalTrigger(Trigger):
    """Fixed interval trigger."""

    interval_seconds: int
    jitter_seconds: int = 0

    def __init__(
        self,
        interval_seconds: int,
        name: str = "interval",
        timezone: str = "UTC",
        jitter_seconds: int = 0,
    ) -> None:
        """Initialize interval trigger.

        Args:
            interval_seconds: Interval between runs in seconds
            name: Trigger name
            timezone: Timezone for scheduling
            jitter_seconds: Random jitter to add to interval
        """
        super().__init__(name, timezone)
        self.interval_seconds = interval_seconds
        self.jitter_seconds = jitter_seconds

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if interval has elapsed."""
        if last_run is None:
            return True
        elapsed = datetime.now(timezone.utc) - last_run
        return elapsed.total_seconds() >= self.interval_seconds

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Get next occurrence time."""
        return from_time + timedelta(seconds=self.interval_seconds)


@dataclass
class DateTrigger(Trigger):
    """One-shot trigger at specific datetime."""

    run_time: datetime

    def __init__(
        self,
        run_time: datetime,
        name: str = "date",
        timezone: str = "UTC",
    ) -> None:
        """Initialize date trigger.

        Args:
            run_time: Specific datetime to run
            name: Trigger name
            timezone: Timezone for scheduling
        """
        super().__init__(name, timezone)
        self.run_time = run_time

    def should_run(self, last_run: datetime | None) -> bool:
        """Check if scheduled time has been reached."""
        if last_run is not None:
            return False
        return datetime.now(timezone.utc) >= self.run_time

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """Return scheduled time if not yet reached."""
        if from_time < self.run_time:
            return self.run_time
        return None


@dataclass
class DependencyTrigger(Trigger):
    """Trigger based on other job completion."""

    dependency_job_ids: list[str]
    wait_all: bool = True

    def __init__(
        self,
        dependency_job_ids: list[str],
        name: str = "dependency",
        timezone: str = "UTC",
        wait_all: bool = True,
    ) -> None:
        """Initialize dependency trigger.

        Args:
            dependency_job_ids: Job IDs to wait for
            name: Trigger name
            timezone: Timezone for scheduling
            wait_all: If True, wait for all; if False, wait for any
        """
        super().__init__(name, timezone)
        self.dependency_job_ids = dependency_job_ids
        self.wait_all = wait_all

    def should_run(self, last_run: datetime | None) -> bool:
        """Dependencies checked by scheduler."""
        return False

    def next_occurrence(self, from_time: datetime) -> datetime | None:
        """No specific next occurrence."""
        return None


@dataclass
class Job:
    """Scheduled job definition."""

    id: str
    name: str
    func: Callable[..., Any]
    trigger: Trigger
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.IDLE
    last_run: datetime | None = None
    next_run: datetime | None = None
    result: Any = None
    error: str | None = None
    max_instances: int = 1
    tags: set[str] = field(default_factory=set)
    description: str = ""
    timeout_seconds: int | None = None
    retry_count: int = 0
    max_retries: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __init__(
        self,
        func: Callable[..., Any],
        trigger: Trigger,
        name: str | None = None,
        job_id: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        max_instances: int = 1,
        tags: set[str] | None = None,
        description: str = "",
        timeout_seconds: int | None = None,
        max_retries: int = 0,
    ) -> None:
        """Initialize job.

        Args:
            func: Callable to execute
            trigger: Trigger for scheduling
            name: Job name (defaults to function name)
            job_id: Unique job ID (auto-generated if None)
            args: Positional arguments for func
            kwargs: Keyword arguments for func
            max_instances: Max concurrent instances
            tags: Tags for categorization
            description: Job description
            timeout_seconds: Execution timeout
            max_retries: Maximum retry attempts
        """
        self.id = job_id or str(uuid4())
        self.name = name or func.__name__
        self.func = func
        self.trigger = trigger
        self.args = args
        self.kwargs = kwargs or {}
        self.status = JobStatus.IDLE
        self.last_run = None
        self.next_run = None
        self.result = None
        self.error = None
        self.max_instances = max_instances
        self.tags = tags or set()
        self.description = description
        self.timeout_seconds = timeout_seconds
        self.retry_count = 0
        self.max_retries = max_retries
        self.created_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """Convert job to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "trigger": str(self.trigger),
            "status": self.status.value,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "tags": list(self.tags),
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }
