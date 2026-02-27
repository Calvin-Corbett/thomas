"""
Middleware pipeline for task processing.

Implements middleware support for:
- Task logging and metrics
- Rate limiting
- Timeout enforcement
- Task serialization
- Custom middleware chains
"""

import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any

from thomas.task_queue._exceptions import MiddlewareError
from thomas.task_queue._types import Task


class MiddlewareType(Enum):
    """Types of middleware hooks."""

    PRE_ENQUEUE = "pre_enqueue"
    POST_ENQUEUE = "post_enqueue"
    PRE_EXECUTE = "pre_execute"
    POST_EXECUTE = "post_execute"
    ON_ERROR = "on_error"


class TaskMiddleware(ABC):
    """Base class for task middleware."""

    @abstractmethod
    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """
        Process a task through middleware.

        Args:
            task: Task being processed.
            hook_type: Type of middleware hook.
            **kwargs: Additional context.

        Returns:
            Modified task, or None to skip processing.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


class LoggingMiddleware(TaskMiddleware):
    """Middleware for task logging."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """
        Initialize LoggingMiddleware.

        Args:
            logger: Optional logger instance. Defaults to root logger.
        """
        self.logger: logging.Logger = logger or logging.getLogger(__name__)

    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """Log task events."""
        if hook_type == MiddlewareType.PRE_ENQUEUE:
            self.logger.info(f"Enqueueing task: {task.name} (id={task.task_id})")
        elif hook_type == MiddlewareType.PRE_EXECUTE:
            self.logger.info(f"Executing task: {task.name} (id={task.task_id})")
        elif hook_type == MiddlewareType.POST_EXECUTE:
            result = kwargs.get("result")
            if result and result.is_success():
                self.logger.info(f"Task completed: {task.name} (id={task.task_id})")
        elif hook_type == MiddlewareType.ON_ERROR:
            error = kwargs.get("error")
            self.logger.error(f"Task failed: {task.name} (id={task.task_id}): {error}")

        return task


class MetricsMiddleware(TaskMiddleware):
    """Middleware for collecting task metrics."""

    def __init__(self) -> None:
        """Initialize MetricsMiddleware."""
        self._metrics: dict[str, Any] = {
            "tasks_enqueued": 0,
            "tasks_executed": 0,
            "tasks_failed": 0,
            "total_execution_time": 0.0,
            "task_times": {},
        }
        self._lock: threading.Lock = threading.Lock()

    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """Collect metrics on task execution."""
        with self._lock:
            if hook_type == MiddlewareType.PRE_ENQUEUE:
                self._metrics["tasks_enqueued"] += 1
            elif hook_type == MiddlewareType.PRE_EXECUTE:
                task.metadata["_start_time"] = time.time()
            elif hook_type == MiddlewareType.POST_EXECUTE:
                self._metrics["tasks_executed"] += 1
                start_time = task.metadata.get("_start_time")
                if start_time:
                    execution_time = time.time() - start_time
                    self._metrics["total_execution_time"] += execution_time
                    if task.name not in self._metrics["task_times"]:
                        self._metrics["task_times"][task.name] = []
                    self._metrics["task_times"][task.name].append(execution_time)
            elif hook_type == MiddlewareType.ON_ERROR:
                self._metrics["tasks_failed"] += 1

        return task

    def get_metrics(self) -> dict[str, Any]:
        """Get collected metrics."""
        with self._lock:
            return dict(self._metrics)


class RateLimitingMiddleware(TaskMiddleware):
    """Middleware for per-queue rate limiting."""

    def __init__(self, tasks_per_second: float = 100.0) -> None:
        """
        Initialize RateLimitingMiddleware.

        Args:
            tasks_per_second: Maximum tasks per second.
        """
        self.tasks_per_second: float = tasks_per_second
        self._tokens: float = tasks_per_second
        self._last_refill: datetime = datetime.utcnow()
        self._lock: threading.Lock = threading.Lock()

    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """Apply rate limiting using token bucket."""
        if hook_type != MiddlewareType.PRE_ENQUEUE:
            return task

        with self._lock:
            self._refill_tokens()
            if self._tokens >= 1:
                self._tokens -= 1
                return task
            else:
                # Would block - return None to indicate task should be requeued
                return None

    def _refill_tokens(self) -> None:
        """Refill token bucket based on elapsed time."""
        now = datetime.utcnow()
        elapsed = (now - self._last_refill).total_seconds()
        tokens_to_add = elapsed * self.tasks_per_second
        self._tokens = min(self.tasks_per_second, self._tokens + tokens_to_add)
        self._last_refill = now


class TimeoutMiddleware(TaskMiddleware):
    """Middleware for task timeout enforcement."""

    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """Enforce timeout on task execution."""
        if hook_type == MiddlewareType.PRE_EXECUTE:
            if task.timeout:
                task.metadata["_timeout_enforced"] = True

        return task


class MiddlewareManager:
    """
    Manages a pipeline of middleware for task processing.

    Applies middleware in order and supports different hook types.
    """

    def __init__(self) -> None:
        """Initialize MiddlewareManager."""
        self._middleware: list[TaskMiddleware] = []
        self._lock: threading.RLock = threading.RLock()

    def add(self, middleware: TaskMiddleware) -> None:
        """
        Add middleware to the pipeline.

        Args:
            middleware: TaskMiddleware instance to add.
        """
        with self._lock:
            self._middleware.append(middleware)

    def remove(self, middleware: TaskMiddleware) -> bool:
        """
        Remove middleware from the pipeline.

        Args:
            middleware: TaskMiddleware instance to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if middleware in self._middleware:
                self._middleware.remove(middleware)
                return True
            return False

    def process(
        self,
        task: Task,
        hook_type: MiddlewareType,
        **kwargs: Any,
    ) -> Task | None:
        """
        Process a task through all middleware.

        Args:
            task: Task to process.
            hook_type: Type of hook to apply.
            **kwargs: Additional context.

        Returns:
            Modified task, or None if processing was halted.
        """
        with self._lock:
            middleware_list = list(self._middleware)

        for middleware in middleware_list:
            try:
                task = middleware.process(task, hook_type, **kwargs)
                if task is None:
                    return None
            except Exception as e:
                raise MiddlewareError(
                    middleware.__class__.__name__,
                    f"Error processing task: {e}",
                )

        return task

    def clear(self) -> None:
        """Clear all middleware."""
        with self._lock:
            self._middleware.clear()

    def count(self) -> int:
        """Get number of registered middleware."""
        with self._lock:
            return len(self._middleware)

    def get_middleware(self) -> list[TaskMiddleware]:
        """Get list of registered middleware."""
        with self._lock:
            return list(self._middleware)

    def __repr__(self) -> str:
        return f"MiddlewareManager(count={self.count()})"
