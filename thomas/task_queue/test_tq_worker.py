"""
Tests for the Worker implementation.

Tests task execution, retries, timeouts, and worker pool management.
"""

import time

import pytest

from thomas.task_queue._exceptions import WorkerError
from thomas.task_queue._types import Task, TaskStatus, WorkerConfig
from thomas.task_queue.queue import TaskQueue
from thomas.task_queue.worker import Worker, WorkerPool


def slow_func(x: int) -> int:
    """Function that takes time to execute."""
    time.sleep(0.1)
    return x * 2


def fast_func(x: int) -> int:
    """Quick function."""
    return x * 2


def failing_func() -> None:
    """Function that raises an error."""
    raise ValueError("Test error")


class TestWorker:
    """Tests for Worker."""

    def test_worker_initialization(self) -> None:
        """Test worker can be initialized."""
        queue = TaskQueue()
        worker = Worker(queue)

        assert worker.is_alive() is False
        assert worker.config.max_concurrent_tasks == 4

    def test_worker_start_stop(self) -> None:
        """Test worker start and stop."""
        queue = TaskQueue()
        worker = Worker(queue)

        worker.start()
        assert worker.is_alive()

        worker.stop(timeout=1)
        assert not worker.is_alive()

    def test_worker_cannot_start_twice(self) -> None:
        """Test worker cannot be started twice."""
        queue = TaskQueue()
        worker = Worker(queue)

        worker.start()
        with pytest.raises(WorkerError):
            worker.start()

        worker.stop()

    def test_worker_executes_tasks(self) -> None:
        """Test worker executes enqueued tasks."""
        queue = TaskQueue()
        worker = Worker(queue)

        task = Task("test", fast_func, args=(5,))
        queue.enqueue(task)

        worker.start()
        time.sleep(1)
        worker.stop()

        assert task.status == TaskStatus.COMPLETED
        assert task.result is not None
        assert task.result.output == 10

    def test_worker_metrics(self) -> None:
        """Test worker metrics collection."""
        queue = TaskQueue()
        worker = Worker(queue)
        worker.start()

        queue.enqueue(Task("test", fast_func, args=(5,)))
        time.sleep(1)

        metrics = worker.get_metrics()
        assert metrics["worker_id"] == worker.config.worker_id
        assert metrics["task_count"] >= 1

        worker.stop()

    def test_task_timeout_enforcement(self) -> None:
        """Test task timeout is enforced."""
        queue = TaskQueue()
        worker = Worker(queue)

        def timeout_func():
            time.sleep(10)

        task = Task("test", timeout_func, timeout=0.5)
        queue.enqueue(task)

        worker.start()
        time.sleep(2)
        worker.stop()

        assert task.status == TaskStatus.FAILED

    def test_retry_on_failure(self) -> None:
        """Test task retry on failure."""
        from thomas.task_queue._types import RetryPolicy

        queue = TaskQueue()
        worker = Worker(queue)

        retry_policy = RetryPolicy(max_retries=2, initial_delay=0.1)
        task = Task("test", failing_func, retry_policy=retry_policy)
        queue.enqueue(task)

        worker.start()
        time.sleep(2)
        worker.stop()

        # Task should be retried but eventually fail
        assert task.retries > 0

    def test_worker_graceful_shutdown(self) -> None:
        """Test graceful shutdown waits for tasks."""
        queue = TaskQueue()
        worker = Worker(queue)

        queue.enqueue(Task("test1", slow_func, args=(1,)))
        queue.enqueue(Task("test2", slow_func, args=(2,)))

        worker.start()
        time.sleep(0.5)
        worker.stop(timeout=5)

        assert not worker.is_alive()

    def test_worker_prefetch(self) -> None:
        """Test worker prefetches tasks."""
        config = WorkerConfig(prefetch_count=2)
        queue = TaskQueue()
        worker = Worker(queue, config)

        queue.enqueue(Task("t1", fast_func, args=(1,)))
        queue.enqueue(Task("t2", fast_func, args=(2,)))
        queue.enqueue(Task("t3", fast_func, args=(3,)))

        worker.start()
        time.sleep(1)
        worker.stop()

        # All tasks should be executed
        assert queue.size() == 0

    def test_fibonacci_backoff(self) -> None:
        """Test fibonacci backoff calculation."""
        worker = Worker(TaskQueue())

        fib_0 = worker._fibonacci(0)
        fib_1 = worker._fibonacci(1)
        fib_2 = worker._fibonacci(2)
        fib_3 = worker._fibonacci(3)

        assert fib_0 == 1
        assert fib_1 == 1
        assert fib_2 == 2
        assert fib_3 == 3


class TestWorkerPool:
    """Tests for WorkerPool."""

    def test_pool_initialization(self) -> None:
        """Test worker pool initialization."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=4)

        assert len(pool._workers) == 4

    def test_pool_start_stop(self) -> None:
        """Test pool start and stop."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=2)

        pool.start()
        assert pool.is_alive()

        pool.stop()
        assert not pool.is_alive()

    def test_pool_executes_tasks(self) -> None:
        """Test pool executes multiple tasks concurrently."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=2)

        for i in range(5):
            queue.enqueue(Task(f"test_{i}", fast_func, args=(i,)))

        pool.start()
        time.sleep(2)
        pool.stop()

        assert queue.size() == 0

    def test_pool_metrics(self) -> None:
        """Test pool metrics collection."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=2)

        pool.start()
        queue.enqueue(Task("test", fast_func, args=(5,)))
        time.sleep(1)
        pool.stop()

        metrics = pool.get_metrics()
        assert "total_workers" in metrics
        assert "workers" in metrics
        assert len(metrics["workers"]) == 2

    def test_pool_repr(self) -> None:
        """Test pool string representation."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=3)

        repr_str = repr(pool)
        assert "WorkerPool" in repr_str
        assert "3" in repr_str
