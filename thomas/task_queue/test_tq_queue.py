"""
Tests for the TaskQueue implementation.

Tests priority ordering, scheduled tasks, dead-letter queue,
and queue persistence.
"""

import time
from datetime import datetime, timedelta

import pytest

from thomas.task_queue._exceptions import (
    InvalidTaskError,
    QueueFullError,
)
from thomas.task_queue._types import QueueConfig, Task, TaskStatus
from thomas.task_queue.queue import TaskQueue


def dummy_func(x: int) -> int:
    """Simple test function."""
    return x * 2


class TestTaskQueue:
    """Tests for TaskQueue."""

    def test_enqueue_dequeue_fifo(self) -> None:
        """Test basic FIFO ordering."""
        queue = TaskQueue()

        task1 = Task("test1", dummy_func, args=(1,))
        task2 = Task("test2", dummy_func, args=(2,))

        queue.enqueue(task1)
        queue.enqueue(task2)

        assert queue.dequeue() == task1
        assert queue.dequeue() == task2

    def test_priority_ordering(self) -> None:
        """Test tasks are ordered by priority."""
        queue = TaskQueue()

        task_low = Task("low", dummy_func, priority=0)
        task_high = Task("high", dummy_func, priority=10)
        task_medium = Task("medium", dummy_func, priority=5)

        queue.enqueue(task_low)
        queue.enqueue(task_high)
        queue.enqueue(task_medium)

        assert queue.dequeue() == task_high
        assert queue.dequeue() == task_medium
        assert queue.dequeue() == task_low

    def test_queue_size(self) -> None:
        """Test queue size tracking."""
        queue = TaskQueue()
        assert queue.size() == 0

        task = Task("test", dummy_func)
        queue.enqueue(task)
        assert queue.size() == 1

        queue.dequeue()
        assert queue.size() == 0

    def test_queue_full(self) -> None:
        """Test queue max size enforcement."""
        config = QueueConfig(max_size=2)
        queue = TaskQueue(config)

        queue.enqueue(Task("t1", dummy_func))
        queue.enqueue(Task("t2", dummy_func))

        with pytest.raises(QueueFullError):
            queue.enqueue(Task("t3", dummy_func))

    def test_peek_without_removing(self) -> None:
        """Test peek returns task without removing."""
        queue = TaskQueue()
        task = Task("test", dummy_func)
        queue.enqueue(task)

        peeked = queue.peek()
        assert peeked == task
        assert queue.size() == 1

    def test_get_task(self) -> None:
        """Test retrieving task by ID."""
        queue = TaskQueue()
        task = Task("test", dummy_func)
        queue.enqueue(task)

        retrieved = queue.get_task(task.task_id)
        assert retrieved == task

    def test_remove_task(self) -> None:
        """Test removing task from queue."""
        queue = TaskQueue()
        task = Task("test", dummy_func)
        queue.enqueue(task)

        assert queue.remove_task(task.task_id)
        assert queue.size() == 0
        assert queue.get_task(task.task_id) is None

    def test_scheduled_tasks(self) -> None:
        """Test scheduled task execution."""
        queue = TaskQueue()

        future_time = datetime.utcnow() + timedelta(seconds=1)
        task = Task("scheduled", dummy_func)
        task.scheduled_at = future_time

        queue.enqueue(task)
        assert queue.size() == 0  # Scheduled tasks don't count

        time.sleep(1.1)
        # Promote scheduled tasks on next dequeue
        queue.dequeue()
        # After promotion, task should be accessible
        assert queue.get_task(task.task_id) is not None

    def test_dead_letter_queue(self) -> None:
        """Test dead-letter queue functionality."""
        config = QueueConfig(enable_dead_letter_queue=True)
        queue = TaskQueue(config)

        task = Task("test", dummy_func)
        queue.add_to_dead_letter(task, "Test failure")

        dlq = queue.get_dead_letter_queue()
        assert len(dlq) == 1
        assert dlq[0].task_id == task.task_id
        assert task.status == TaskStatus.DEAD_LETTERED

    def test_update_task(self) -> None:
        """Test updating task state."""
        queue = TaskQueue()
        task = Task("test", dummy_func)
        queue.enqueue(task)

        task.status = TaskStatus.RUNNING
        queue.update_task(task)

        retrieved = queue.get_task(task.task_id)
        assert retrieved.status == TaskStatus.RUNNING

    def test_clear_queue(self) -> None:
        """Test clearing all tasks."""
        queue = TaskQueue()
        queue.enqueue(Task("t1", dummy_func))
        queue.enqueue(Task("t2", dummy_func))

        queue.clear()
        assert queue.is_empty()
        assert queue.size() == 0

    def test_invalid_task_raises_error(self) -> None:
        """Test enqueueing invalid task raises error."""
        queue = TaskQueue()

        with pytest.raises(InvalidTaskError):
            queue.enqueue("not a task")

    def test_is_empty(self) -> None:
        """Test is_empty method."""
        queue = TaskQueue()
        assert queue.is_empty()

        queue.enqueue(Task("test", dummy_func))
        assert not queue.is_empty()

    def test_task_expiration(self) -> None:
        """Test that expired tasks are removed."""
        config = QueueConfig(result_ttl_seconds=1)
        queue = TaskQueue(config)

        task = Task("test", dummy_func)
        task.completed_at = datetime.utcnow() - timedelta(seconds=2)
        queue._tasks[task.task_id] = task

        queue._expire_tasks()
        assert task.task_id not in queue._tasks

    def test_persistence_disabled(self) -> None:
        """Test queue with persistence disabled."""
        config = QueueConfig(enable_persistence=False)
        queue = TaskQueue(config)

        queue.enqueue(Task("test", dummy_func))
        assert queue.size() == 1

    def test_repr(self) -> None:
        """Test string representation."""
        queue = TaskQueue()
        assert "TaskQueue" in repr(queue)

    def test_multiple_threads(self) -> None:
        """Test thread-safe enqueue/dequeue."""
        import threading

        queue = TaskQueue()

        def enqueue_tasks():
            for i in range(10):
                queue.enqueue(Task(f"task_{i}", dummy_func))

        def dequeue_tasks():
            for _ in range(10):
                queue.dequeue()

        threads = [
            threading.Thread(target=enqueue_tasks),
            threading.Thread(target=dequeue_tasks),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert queue.is_empty()
