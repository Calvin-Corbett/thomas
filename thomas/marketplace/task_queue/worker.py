"""
Worker implementation for executing tasks from the queue.

Implements task execution with support for:
- Concurrent task execution
- Task timeout enforcement
- Automatic retry with exponential backoff
- Worker heartbeat and health monitoring
- Graceful shutdown
- Worker pool management
"""

import signal
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from thomas.marketplace.task_queue._exceptions import (
    TaskTimeoutError,
    WorkerError,
)
from thomas.marketplace.task_queue._types import Task, TaskResult, TaskStatus, WorkerConfig
from thomas.marketplace.task_queue.queue import TaskQueue


class Worker:
    """
    Executes tasks from a queue with support for concurrency, retries, and monitoring.

    Each worker polls the queue at regular intervals, executes tasks with
    timeout enforcement, and handles retries with exponential backoff.
    """

    def __init__(
        self,
        queue: TaskQueue,
        config: WorkerConfig | None = None,
        result_callback: Callable[[TaskResult], None] | None = None,
    ) -> None:
        """
        Initialize a Worker.

        Args:
            queue: TaskQueue to consume tasks from.
            config: Worker configuration. Defaults to WorkerConfig().
            result_callback: Optional callback for task results.
        """
        self.queue: TaskQueue = queue
        self.config: WorkerConfig = config or WorkerConfig()
        self.result_callback: Callable[[TaskResult], None] | None = result_callback

        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.config.max_concurrent_tasks,
            thread_name_prefix=f"worker-{self.config.worker_id}",
        )
        self._running: bool = False
        self._lock: threading.RLock = threading.RLock()
        self._active_tasks: dict[str, Future] = {}
        self._last_heartbeat: datetime = datetime.utcnow()
        self._task_count: int = 0
        self._error_count: int = 0

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def start(self) -> None:
        """Start the worker polling loop."""
        with self._lock:
            if self._running:
                raise WorkerError(self.config.worker_id, "Worker already running")
            self._running = True

        self._poll_thread: threading.Thread = threading.Thread(
            target=self._poll_loop,
            daemon=False,
            name=f"poll-{self.config.worker_id}",
        )
        self._poll_thread.start()

        self._heartbeat_thread: threading.Thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"heartbeat-{self.config.worker_id}",
        )
        self._heartbeat_thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """
        Stop the worker gracefully.

        Args:
            timeout: Seconds to wait for tasks to complete before forcing shutdown.
        """
        timeout = timeout or self.config.graceful_shutdown_timeout

        with self._lock:
            self._running = False

        # Wait for active tasks
        deadline = time.time() + timeout
        while self._active_tasks and time.time() < deadline:
            remaining = sum(1 for f in self._active_tasks.values() if not f.done())
            if remaining == 0:
                break
            time.sleep(0.1)

        # Force shutdown remaining tasks
        self._executor.shutdown(wait=False)

        if self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1)

    def is_alive(self) -> bool:
        """Check if worker is running."""
        with self._lock:
            return self._running

    def get_metrics(self) -> dict[str, Any]:
        """
        Get worker performance metrics.

        Returns:
            Dictionary with task_count, error_count, active_tasks, etc.
        """
        with self._lock:
            return {
                "worker_id": self.config.worker_id,
                "running": self._running,
                "task_count": self._task_count,
                "error_count": self._error_count,
                "active_tasks": len([f for f in self._active_tasks.values() if not f.done()]),
                "last_heartbeat": self._last_heartbeat.isoformat(),
            }

    def _poll_loop(self) -> None:
        """Main polling loop that fetches and executes tasks."""
        while self._running:
            try:
                # Check if we can prefetch more tasks
                active_count = sum(1 for f in self._active_tasks.values() if not f.done())
                if active_count < self.config.prefetch_count:
                    task = self.queue.dequeue()
                    if task:
                        self._execute_task(task)
                    else:
                        time.sleep(self.config.poll_interval)
                else:
                    time.sleep(self.config.poll_interval)

                # Clean up completed futures
                self._cleanup_completed_futures()

            except Exception as e:
                self._error_count += 1
                if self.config.enable_metrics:
                    self._log_error(f"Poll loop error: {e}")

    def _heartbeat_loop(self) -> None:
        """Periodic heartbeat to indicate worker is alive."""
        while self._running:
            with self._lock:
                self._last_heartbeat = datetime.utcnow()
            time.sleep(self.config.heartbeat_interval)

    def _execute_task(self, task: Task) -> None:
        """
        Schedule a task for execution.

        Args:
            task: Task to execute.
        """
        with self._lock:
            self._task_count += 1

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        self.queue.update_task(task)

        future = self._executor.submit(self._run_task, task)
        with self._lock:
            self._active_tasks[str(task.task_id)] = future

    def _run_task(self, task: Task) -> None:
        """
        Execute a single task with timeout and retry handling.

        Args:
            task: Task to execute.
        """
        try:
            result = self._execute_with_timeout(task)
            task.result = result
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.utcnow()

            if self.result_callback:
                self.result_callback(result)

        except TaskTimeoutError as e:
            self._handle_task_failure(task, str(e), should_retry=True)
        except Exception as e:
            self._handle_task_failure(task, str(e), should_retry=True)
        finally:
            self.queue.update_task(task)

    def _execute_with_timeout(self, task: Task) -> TaskResult:
        """
        Execute task with timeout enforcement.

        Args:
            task: Task to execute.

        Returns:
            TaskResult with execution outcome.

        Raises:
            TaskTimeoutError: If execution exceeds timeout.
        """
        result_holder: dict[Any | None, None] = {}
        exception_holder: list[Exception | None] = [None]

        def target() -> None:
            try:
                output = task.func(*task.args, **task.kwargs)
                result_holder["output"] = output
            except Exception as e:
                exception_holder[0] = e

        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout=task.timeout)

        if thread.is_alive():
            raise TaskTimeoutError(str(task.task_id), task.timeout)

        if exception_holder[0]:
            raise exception_holder[0]

        output = result_holder.get("output")
        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            output=output,
            completed_at=datetime.utcnow(),
        )

    def _handle_task_failure(self, task: Task, error: str, should_retry: bool = True) -> None:
        """
        Handle task failure with retry logic.

        Args:
            task: Failed task.
            error: Error message.
            should_retry: Whether to attempt retry.
        """
        task.metadata["last_error"] = error
        task.metadata["error_traceback"] = traceback.format_exc()

        if should_retry and task.retries < task.max_retries:
            retry_delay = self._calculate_retry_delay(task)
            task.retries += 1
            task.status = TaskStatus.RETRYING
            task.scheduled_at = datetime.utcnow() + timedelta(seconds=retry_delay)
            self.queue.update_task(task)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.result = TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                error=error,
                completed_at=datetime.utcnow(),
            )
            self.queue.add_to_dead_letter(task, error)

    def _calculate_retry_delay(self, task: Task) -> float:
        """
        Calculate delay before retry based on backoff strategy.

        Args:
            task: Task to retry.

        Returns:
            Delay in seconds.
        """
        policy = task.retry_policy
        base_delay = policy.initial_delay

        if policy.backoff_type == "exponential":
            delay = base_delay * (2**task.retries)
        elif policy.backoff_type == "linear":
            delay = base_delay * (task.retries + 1)
        elif policy.backoff_type == "fibonacci":
            delay = base_delay * self._fibonacci(task.retries)
        else:
            delay = base_delay

        delay = min(delay, policy.max_delay)

        if policy.jitter:
            import random

            delay *= random.uniform(0.8, 1.2)

        return delay

    @staticmethod
    def _fibonacci(n: int) -> int:
        """Calculate nth Fibonacci number."""
        if n <= 1:
            return 1
        a, b = 1, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b

    def _cleanup_completed_futures(self) -> None:
        """Remove completed futures from tracking."""
        with self._lock:
            completed = [task_id for task_id, future in list(self._active_tasks.items()) if future.done()]
            for task_id in completed:
                del self._active_tasks[task_id]

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        self.stop()

    def _log_error(self, message: str) -> None:
        """Log an error message."""
        print(f"[{self.config.worker_id}] {message}")

    def __repr__(self) -> str:
        return f"Worker(id={self.config.worker_id}, running={self.is_alive()}, tasks_executed={self._task_count})"


class WorkerPool:
    """
    Manages a pool of workers for distributed task execution.

    Coordinates multiple workers to execute tasks from a shared queue.
    """

    def __init__(
        self,
        queue: TaskQueue,
        num_workers: int = 4,
        config: WorkerConfig | None = None,
    ) -> None:
        """
        Initialize a WorkerPool.

        Args:
            queue: TaskQueue shared by all workers.
            num_workers: Number of worker threads to create.
            config: Optional WorkerConfig for all workers.
        """
        self.queue: TaskQueue = queue
        self.num_workers: int = num_workers
        self._workers: list[Worker] = []
        self._lock: threading.RLock = threading.RLock()

        base_config = config or WorkerConfig()
        for i in range(num_workers):
            worker_config = WorkerConfig(
                worker_id=f"{base_config.worker_id}-{i}",
                max_concurrent_tasks=base_config.max_concurrent_tasks,
                poll_interval=base_config.poll_interval,
            )
            worker = Worker(queue, worker_config)
            self._workers.append(worker)

    def start(self) -> None:
        """Start all workers."""
        with self._lock:
            for worker in self._workers:
                worker.start()

    def stop(self, timeout: float | None = None) -> None:
        """Stop all workers gracefully."""
        with self._lock:
            for worker in self._workers:
                worker.stop(timeout)

    def is_alive(self) -> bool:
        """Check if any worker is still running."""
        with self._lock:
            return any(worker.is_alive() for worker in self._workers)

    def get_metrics(self) -> dict[str, Any]:
        """Get metrics for all workers."""
        with self._lock:
            return {
                "total_workers": len(self._workers),
                "active_workers": sum(1 for w in self._workers if w.is_alive()),
                "workers": [w.get_metrics() for w in self._workers],
            }

    def __repr__(self) -> str:
        return f"WorkerPool(workers={len(self._workers)}, active={sum(1 for w in self._workers if w.is_alive())})"
