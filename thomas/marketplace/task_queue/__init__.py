"""
Thomas Task Queue - A distributed task queue with priority, scheduling, and retry management.

This module provides a complete task queue system with:
- Priority-based task queuing
- Scheduled task execution with cron support
- Automatic retry with configurable backoff strategies
- Workflow/DAG support with task dependencies
- Result storage and retrieval
- Rate limiting and monitoring
- Worker management with graceful shutdown
"""

from thomas.marketplace.task_queue._exceptions import (
    InvalidTaskError,
    RetryExhaustedError,
    SchedulerError,
    TaskNotFoundError,
    TaskQueueException,
    WorkerError,
)
from thomas.marketplace.task_queue._types import (
    QueueConfig,
    RetryPolicy,
    Schedule,
    Task,
    TaskResult,
    TaskStatus,
    WorkerConfig,
)
from thomas.marketplace.task_queue.batching import BatchExecutor, BatchTask
from thomas.marketplace.task_queue.middleware import MiddlewareManager, TaskMiddleware
from thomas.marketplace.task_queue.monitoring import QueueMonitor
from thomas.marketplace.task_queue.queue import TaskQueue
from thomas.marketplace.task_queue.rate_limiter import RateLimiter
from thomas.marketplace.task_queue.results import ResultStore
from thomas.marketplace.task_queue.retry import RetryManager
from thomas.marketplace.task_queue.scheduler import TaskScheduler
from thomas.marketplace.task_queue.worker import Worker, WorkerPool
from thomas.marketplace.task_queue.workflows import Workflow, WorkflowNode

__version__ = "0.1.0"
__all__ = [
    "Task",
    "TaskStatus",
    "TaskResult",
    "WorkerConfig",
    "QueueConfig",
    "RetryPolicy",
    "Schedule",
    "TaskQueue",
    "Worker",
    "WorkerPool",
    "TaskScheduler",
    "Workflow",
    "WorkflowNode",
    "RetryManager",
    "ResultStore",
    "MiddlewareManager",
    "TaskMiddleware",
    "QueueMonitor",
    "RateLimiter",
    "BatchTask",
    "BatchExecutor",
    "TaskQueueException",
    "TaskNotFoundError",
    "InvalidTaskError",
    "WorkerError",
    "SchedulerError",
    "RetryExhaustedError",
]
