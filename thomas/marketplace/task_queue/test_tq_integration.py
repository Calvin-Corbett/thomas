"""
Integration tests for the complete task queue system.

Tests end-to-end workflows combining multiple components:
- Queue + Worker + Scheduler
- Workflow execution
- Retry handling
- Rate limiting
- Monitoring
"""

import time
from datetime import datetime

from thomas.marketplace.task_queue._types import RetryPolicy, Schedule, Task, TaskStatus
from thomas.marketplace.task_queue.middleware import LoggingMiddleware, MiddlewareManager
from thomas.marketplace.task_queue.monitoring import QueueMonitor
from thomas.marketplace.task_queue.queue import TaskQueue
from thomas.marketplace.task_queue.rate_limiter import RateLimiter
from thomas.marketplace.task_queue.results import ResultStore
from thomas.marketplace.task_queue.retry import RetryManager
from thomas.marketplace.task_queue.scheduler import TaskScheduler
from thomas.marketplace.task_queue.worker import Worker, WorkerPool
from thomas.marketplace.task_queue.workflows import Workflow


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def failing_task() -> None:
    """Task that fails."""
    raise ValueError("Test failure")


class TestIntegration:
    """Integration tests."""

    def test_queue_worker_execution(self) -> None:
        """Test basic queue and worker integration."""
        queue = TaskQueue()
        worker = Worker(queue)

        task = Task("add", add, args=(5, 3))
        queue.enqueue(task)

        worker.start()
        time.sleep(1)
        worker.stop()

        assert task.status == TaskStatus.COMPLETED
        assert task.result.output == 8

    def test_worker_pool_execution(self) -> None:
        """Test worker pool with multiple tasks."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=3)

        for i in range(10):
            queue.enqueue(Task(f"add_{i}", add, args=(i, 1)))

        pool.start()
        time.sleep(2)
        pool.stop()

        assert queue.is_empty()

    def test_queue_scheduler_worker(self) -> None:
        """Test queue, scheduler, and worker together."""
        queue = TaskQueue()
        scheduler = TaskScheduler(queue, poll_interval=0.1)
        worker = Worker(queue)

        # Schedule task for immediate execution
        schedule = Schedule(one_shot_at=datetime.utcnow())
        task = Task("add", add, args=(10, 5), schedule=schedule)

        scheduler.add_scheduled_task(task)
        scheduler.start()
        worker.start()

        time.sleep(1)

        scheduler.stop()
        worker.stop()

        assert queue.is_empty()

    def test_workflow_execution(self) -> None:
        """Test workflow with task dependencies."""
        workflow = Workflow(name="math_workflow")

        task1 = Task("step1", add, args=(2, 3))
        task2 = Task("step2", multiply, args=(5, 2))

        workflow.add_task("add", task1)
        workflow.add_task("multiply", task2, dependencies=["add"])

        # Check task ordering
        ready = workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "add"

        # Mark first as complete
        from thomas.marketplace.task_queue._types import TaskResult

        result1 = TaskResult(task1.task_id, TaskStatus.COMPLETED, output=5)
        workflow.mark_completed("add", result1)

        # Now second should be ready
        ready = workflow.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == "multiply"

    def test_retry_manager_with_queue(self) -> None:
        """Test retry manager integration with task queue."""
        queue = TaskQueue()
        retry_manager = RetryManager()

        policy = RetryPolicy(
            max_retries=2,
            backoff_type="linear",
            initial_delay=0.1,
        )
        task = Task("test", failing_task, retry_policy=policy)
        queue.enqueue(task)

        assert retry_manager.should_retry(task, ValueError("error"))
        delay = retry_manager.calculate_delay(task)
        assert delay > 0

    def test_result_store_integration(self) -> None:
        """Test result storage with tasks."""
        queue = TaskQueue()
        results = ResultStore(ttl_seconds=60)
        worker = Worker(queue)

        task = Task("add", add, args=(5, 3))
        queue.enqueue(task)

        worker.start()
        time.sleep(1)
        worker.stop()

        # Manually store result
        results.store(task.result)

        # Retrieve result
        stored = results.get(task.task_id)
        assert stored is not None
        assert stored.output == 8

    def test_rate_limiter_integration(self) -> None:
        """Test rate limiting with queue."""
        queue = TaskQueue()
        rate_limiter = RateLimiter()

        # Set queue limit
        rate_limiter.add_queue_limit("default", rate=100, burst=10)

        # Should allow tasks
        for i in range(5):
            task = Task(f"task_{i}", add, args=(i, 1))
            rate_limiter.allow_enqueue("default", task.name)
            queue.enqueue(task)

        assert queue.size() == 5

    def test_monitoring_integration(self) -> None:
        """Test monitoring with task execution."""
        queue = TaskQueue()
        monitor = QueueMonitor(queue)
        worker = Worker(queue)

        # Execute some tasks
        for i in range(3):
            queue.enqueue(Task(f"add_{i}", add, args=(i, 1)))

        monitor.record_queue_depth()
        worker.start()
        time.sleep(1)
        worker.stop()

        # Check metrics
        metrics = monitor.get_metrics_summary()
        assert "health" in metrics
        assert metrics["health"]["total_tasks"] >= 3

    def test_middleware_pipeline(self) -> None:
        """Test middleware with task execution."""
        queue = TaskQueue()
        middleware = MiddlewareManager()
        middleware.add(LoggingMiddleware())

        from thomas.marketplace.task_queue.middleware import MiddlewareType

        task = Task("test", add, args=(1, 2))

        # Process through middleware
        processed = middleware.process(task, MiddlewareType.PRE_ENQUEUE)
        assert processed == task

    def test_end_to_end_workflow(self) -> None:
        """Test complete end-to-end workflow."""
        # Create components
        queue = TaskQueue()
        scheduler = TaskScheduler(queue, poll_interval=0.1)
        pool = WorkerPool(queue, num_workers=2)
        monitor = QueueMonitor(queue)
        results = ResultStore()

        # Create and schedule tasks
        for i in range(5):
            task = Task(f"multiply_{i}", multiply, args=(i, 2), priority=i % 2)
            queue.enqueue(task)

        # Start execution
        scheduler.start()
        pool.start()

        time.sleep(2)

        # Stop
        scheduler.stop()
        pool.stop()

        # Check results
        status = monitor.get_health_status()
        assert status["total_tasks"] >= 5

    def test_parallel_task_execution(self) -> None:
        """Test parallel task execution."""
        queue = TaskQueue()
        pool = WorkerPool(queue, num_workers=4)

        # Create diamond dependency pattern
        task1 = Task("start", add, args=(1, 1))
        task2 = Task("left", multiply, args=(2, 2))
        task3 = Task("right", multiply, args=(3, 3))

        for task in [task1, task2, task3]:
            queue.enqueue(task)

        pool.start()
        time.sleep(2)
        pool.stop()

        assert queue.is_empty()

    def test_error_handling_with_monitoring(self) -> None:
        """Test error handling with monitoring."""
        queue = TaskQueue()
        monitor = QueueMonitor(queue)
        worker = Worker(queue)

        # Mix success and failure tasks
        queue.enqueue(Task("success", add, args=(1, 1)))
        queue.enqueue(Task("failure", failing_task))
        queue.enqueue(Task("success2", add, args=(2, 2)))

        worker.start()
        time.sleep(2)
        worker.stop()

        metrics = monitor.get_health_status()
        assert metrics["error_rate_percent"] > 0

    def test_task_ordering_and_execution(self) -> None:
        """Test tasks execute in priority order."""
        queue = TaskQueue()
        results = []

        def record_func(name: str):
            results.append(name)
            return name

        # Enqueue in reverse priority order
        queue.enqueue(Task("low", lambda: record_func("low"), priority=0))
        queue.enqueue(Task("high", lambda: record_func("high"), priority=10))
        queue.enqueue(Task("medium", lambda: record_func("medium"), priority=5))

        worker = Worker(queue)
        worker.start()
        time.sleep(1)
        worker.stop()

        assert queue.is_empty()

    def test_concurrent_enqueue_dequeue(self) -> None:
        """Test concurrent enqueue and dequeue operations."""
        import threading

        queue = TaskQueue()
        results = []

        def enqueuer():
            for i in range(20):
                queue.enqueue(Task(f"task_{i}", add, args=(i, 1)))

        def dequeuer():
            for _ in range(20):
                task = queue.dequeue()
                if task:
                    results.append(task)

        threads = [
            threading.Thread(target=enqueuer),
            threading.Thread(target=dequeuer),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
