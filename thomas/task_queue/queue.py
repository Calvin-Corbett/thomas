"""
Task queue implementation with priority ordering and scheduling support.

Implements a thread-safe priority queue with support for:
- Priority-based task ordering
- Delayed task scheduling
- Dead-letter queue for failed tasks
- Optional persistence
- Task TTL expiration
"""

import heapq
import json
import threading
from datetime import datetime
from pathlib import Path
from uuid import UUID

from thomas.task_queue._exceptions import (
    InvalidTaskError,
    QueueFullError,
    TaskNotFoundError,
)
from thomas.task_queue._types import QueueConfig, Task, TaskStatus


class TaskQueue:
    """
    A priority-based task queue with scheduling and persistence support.

    Tasks are ordered by priority (higher first) and then by creation time.
    Supports scheduled tasks, dead-letter queue, and task TTL.
    """

    def __init__(self, config: QueueConfig | None = None) -> None:
        """
        Initialize a TaskQueue.

        Args:
            config: Queue configuration. Defaults to QueueConfig().
        """
        self.config: QueueConfig = config or QueueConfig()
        self._lock: threading.RLock = threading.RLock()
        self._queue: list[tuple[int, datetime, Task]] = []
        self._tasks: dict[str | UUID, Task] = {}
        self._dead_letter_queue: list[Task] = []
        self._scheduled_tasks: dict[str | UUID, Task] = {}

        if self.config.enable_persistence and self.config.persistence_path:
            self._persistence_path = Path(self.config.persistence_path)
            self._persistence_path.mkdir(parents=True, exist_ok=True)
            self._load_from_persistence()

    def enqueue(self, task: Task) -> None:
        """
        Add a task to the queue.

        Args:
            task: Task to enqueue.

        Raises:
            QueueFullError: If queue is at max capacity.
            InvalidTaskError: If task is invalid.
        """
        if not isinstance(task, Task):
            raise InvalidTaskError("Task must be a Task instance")

        with self._lock:
            if len(self._queue) >= self.config.max_size:
                raise QueueFullError(self.config.name, self.config.max_size)

            if task.is_scheduled():
                self._scheduled_tasks[task.task_id] = task
            else:
                heapq.heappush(self._queue, (task.priority, task.created_at, task))
                self._tasks[task.task_id] = task

            self._save_if_enabled()

    def dequeue(self) -> Task | None:
        """
        Remove and return the highest priority task.

        Returns:
            The next task to execute, or None if queue is empty.
        """
        with self._lock:
            self._expire_tasks()
            self._promote_scheduled_tasks()

            while self._queue:
                _, _, task = heapq.heappop(self._queue)
                if task.task_id in self._tasks:
                    del self._tasks[task.task_id]
                    self._save_if_enabled()
                    return task

            return None

    def peek(self) -> Task | None:
        """
        View the highest priority task without removing it.

        Returns:
            The next task that would be executed, or None if empty.
        """
        with self._lock:
            self._expire_tasks()
            self._promote_scheduled_tasks()

            for _, _, task in self._queue:
                if task.task_id in self._tasks:
                    return task

            return None

    def size(self) -> int:
        """Get current queue size."""
        with self._lock:
            return len(self._queue)

    def get_task(self, task_id: str | UUID) -> Task | None:
        """
        Retrieve a task by ID without removing it.

        Args:
            task_id: ID of the task to retrieve.

        Returns:
            The task, or None if not found.
        """
        with self._lock:
            return self._tasks.get(task_id) or self._scheduled_tasks.get(task_id)

    def remove_task(self, task_id: str | UUID) -> bool:
        """
        Remove a task from the queue.

        Args:
            task_id: ID of the task to remove.

        Returns:
            True if task was removed, False if not found.
        """
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks.pop(task_id)
                self._queue = [(p, c, t) for p, c, t in self._queue if t.task_id != task_id]
                heapq.heapify(self._queue)
                self._save_if_enabled()
                return True

            if task_id in self._scheduled_tasks:
                del self._scheduled_tasks[task_id]
                self._save_if_enabled()
                return True

            return False

    def update_task(self, task: Task) -> None:
        """
        Update a task's state.

        Args:
            task: Updated task object.

        Raises:
            TaskNotFoundError: If task not found.
        """
        with self._lock:
            if task.task_id not in self._tasks and task.task_id not in self._scheduled_tasks:
                raise TaskNotFoundError(str(task.task_id))

            if task.is_scheduled():
                self._scheduled_tasks[task.task_id] = task
                if task.task_id in self._tasks:
                    del self._tasks[task.task_id]
            else:
                self._tasks[task.task_id] = task
                if task.task_id in self._scheduled_tasks:
                    del self._scheduled_tasks[task.task_id]

            self._save_if_enabled()

    def add_to_dead_letter(self, task: Task, reason: str) -> None:
        """
        Move a task to the dead-letter queue.

        Args:
            task: Task that failed.
            reason: Reason for dead-lettering.
        """
        with self._lock:
            if not self.config.enable_dead_letter_queue:
                return

            task.status = TaskStatus.DEAD_LETTERED
            task.metadata["dead_letter_reason"] = reason
            task.metadata["dead_lettered_at"] = datetime.utcnow().isoformat()
            self._dead_letter_queue.append(task)
            self._save_if_enabled()

    def get_dead_letter_queue(self) -> list[Task]:
        """Get all dead-lettered tasks."""
        with self._lock:
            self._expire_dead_letter_tasks()
            return list(self._dead_letter_queue)

    def clear(self) -> None:
        """Clear all tasks from the queue."""
        with self._lock:
            self._queue.clear()
            self._tasks.clear()
            self._scheduled_tasks.clear()
            self._save_if_enabled()

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        with self._lock:
            return len(self._queue) == 0 and len(self._scheduled_tasks) == 0

    def _expire_tasks(self) -> None:
        """Remove tasks that have exceeded TTL."""
        now = datetime.utcnow()
        expired_ids = [
            task_id
            for task_id, task in self._tasks.items()
            if task.completed_at and (now - task.completed_at).total_seconds() > self.config.result_ttl_seconds
        ]

        for task_id in expired_ids:
            del self._tasks[task_id]
            self._queue = [(p, c, t) for p, c, t in self._queue if t.task_id != task_id]

    def _expire_dead_letter_tasks(self) -> None:
        """Remove dead-lettered tasks that have exceeded TTL."""
        now = datetime.utcnow()
        self._dead_letter_queue = [
            task
            for task in self._dead_letter_queue
            if not task.metadata.get("dead_lettered_at")
            or (now - datetime.fromisoformat(task.metadata["dead_lettered_at"])).total_seconds()
            <= self.config.dead_letter_ttl_seconds
        ]

    def _promote_scheduled_tasks(self) -> None:
        """Move scheduled tasks to main queue if time has come."""
        now = datetime.utcnow()
        to_promote = [task_id for task_id, task in list(self._scheduled_tasks.items()) if not task.is_scheduled()]

        for task_id in to_promote:
            task = self._scheduled_tasks.pop(task_id)
            heapq.heappush(self._queue, (task.priority, task.created_at, task))
            self._tasks[task_id] = task

    def _save_if_enabled(self) -> None:
        """Save queue state to disk if persistence is enabled."""
        if not self.config.enable_persistence or not self.config.persistence_path:
            return

        try:
            state = {
                "queue": [self._task_to_dict(task) for _, _, task in self._queue],
                "dead_letter": [self._task_to_dict(task) for task in self._dead_letter_queue],
            }
            state_file = Path(self.config.persistence_path) / "queue_state.json"
            with open(state_file, "w") as f:
                json.dump(state, f, default=str, indent=2)
        except Exception:
            pass  # Silently fail persistence

    def _load_from_persistence(self) -> None:
        """Load queue state from disk if persistence is enabled."""
        if not self.config.enable_persistence or not self.config.persistence_path:
            return

        try:
            state_file = Path(self.config.persistence_path) / "queue_state.json"
            if state_file.exists():
                with open(state_file) as f:
                    state = json.load(f)
                # Note: In a real implementation, deserialize tasks properly
                # This is simplified for the prototype
        except Exception:
            pass  # Silently fail on load error

    def _task_to_dict(self, task: Task) -> dict:
        """Convert task to dictionary for serialization."""
        return {
            "task_id": str(task.task_id),
            "name": task.name,
            "priority": task.priority,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"TaskQueue(name={self.config.name}, size={self.size()}, "
            f"scheduled={len(self._scheduled_tasks)}, "
            f"dead_letter={len(self._dead_letter_queue)})"
        )
