"""
Core type definitions for the task queue system.

Defines task data structures, enums, and configuration classes used throughout
the distributed task queue.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class TaskStatus(Enum):
    """Enumeration of possible task states."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class TaskResult:
    """Result of a task execution."""

    def __init__(
        self,
        task_id: str | UUID,
        status: TaskStatus,
        output: Any | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """
        Initialize a TaskResult.

        Args:
            task_id: The ID of the completed task.
            status: The final status of the task.
            output: The return value of the task function.
            error: Error message if task failed.
            completed_at: Timestamp when task completed.
        """
        self.task_id: str | UUID = task_id
        self.status: TaskStatus = status
        self.output: Any | None = output
        self.error: str | None = error
        self.completed_at: datetime = completed_at or datetime.utcnow()

    def is_success(self) -> bool:
        """Check if task completed successfully."""
        return self.status == TaskStatus.COMPLETED

    def is_failure(self) -> bool:
        """Check if task failed."""
        return self.status == TaskStatus.FAILED

    def __repr__(self) -> str:
        return (
            f"TaskResult(task_id={self.task_id}, status={self.status.value}, "
            f"has_output={self.output is not None}, has_error={self.error is not None})"
        )


@dataclass
class RetryPolicy:
    """Configuration for task retry behavior."""

    max_retries: int = 3
    backoff_type: str = "exponential"  # exponential, linear, fibonacci
    initial_delay: float = 1.0  # seconds
    max_delay: float = 300.0  # seconds
    jitter: bool = True
    retry_on: list[type] = field(default_factory=list)  # exception types to retry on

    def __post_init__(self) -> None:
        """Validate retry policy."""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must be non-negative")
        if self.max_delay < self.initial_delay:
            raise ValueError("max_delay must be >= initial_delay")
        if self.backoff_type not in ("exponential", "linear", "fibonacci"):
            raise ValueError("Invalid backoff_type")


@dataclass
class Schedule:
    """Task scheduling configuration."""

    cron_expression: str | None = None
    interval_seconds: int | None = None
    one_shot_at: datetime | None = None
    timezone: str = "UTC"
    max_instances: int = 1  # max concurrent instances of this scheduled task

    def __post_init__(self) -> None:
        """Validate schedule configuration."""
        count = sum(
            [
                self.cron_expression is not None,
                self.interval_seconds is not None,
                self.one_shot_at is not None,
            ]
        )
        if count != 1:
            raise ValueError("Exactly one schedule type must be specified")


@dataclass
class Task:
    """Represents a task in the queue."""

    name: str
    func: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    status: TaskStatus = TaskStatus.PENDING
    retries: int = 0
    max_retries: int = 3
    timeout: float = 300.0  # seconds
    scheduled_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: TaskResult | None = None
    task_id: str | UUID = field(default_factory=lambda: str(uuid4()))
    parent_task_id: str | UUID | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    schedule: Schedule | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        """Make task hashable."""
        return hash(self.task_id)

    def __eq__(self, other: Any) -> bool:
        """Check task equality."""
        if not isinstance(other, Task):
            return False
        return self.task_id == other.task_id

    def __lt__(self, other: "Task") -> bool:
        """Compare tasks for priority queue (higher priority first)."""
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.created_at < other.created_at

    def is_expired(self) -> bool:
        """Check if task has exceeded its timeout."""
        if self.status not in (TaskStatus.RUNNING, TaskStatus.RETRYING):
            return False
        if self.started_at is None:
            return False
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        return elapsed > self.timeout

    def is_scheduled(self) -> bool:
        """Check if task is scheduled for future execution."""
        if self.scheduled_at is None:
            return False
        return datetime.utcnow() < self.scheduled_at

    def __repr__(self) -> str:
        return (
            f"Task(id={self.task_id}, name={self.name}, status={self.status.value}, "
            f"priority={self.priority}, retries={self.retries}/{self.max_retries})"
        )


@dataclass
class WorkerConfig:
    """Configuration for worker processes."""

    worker_id: str = field(default_factory=lambda: str(uuid4()))
    max_concurrent_tasks: int = 4
    poll_interval: float = 0.1  # seconds
    heartbeat_interval: float = 5.0  # seconds
    graceful_shutdown_timeout: float = 30.0  # seconds
    prefetch_count: int = 2
    enable_metrics: bool = True

    def __post_init__(self) -> None:
        """Validate worker configuration."""
        if self.max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be >= 1")
        if self.poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if self.heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be positive")


@dataclass
class QueueConfig:
    """Configuration for the task queue."""

    name: str = "default"
    max_size: int = 10000
    enable_persistence: bool = False
    persistence_path: str | None = None
    result_ttl_seconds: int = 86400  # 24 hours
    enable_dead_letter_queue: bool = True
    dead_letter_ttl_seconds: int = 604800  # 7 days
    enable_monitoring: bool = True

    def __post_init__(self) -> None:
        """Validate queue configuration."""
        if self.max_size < 1:
            raise ValueError("max_size must be >= 1")
        if self.result_ttl_seconds < 0:
            raise ValueError("result_ttl_seconds must be non-negative")
        if self.enable_persistence and not self.persistence_path:
            raise ValueError("persistence_path required when persistence enabled")
