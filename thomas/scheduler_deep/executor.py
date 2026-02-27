"""
Job executor with thread pool and process pool support.

Handles job execution, timeouts, cancellation, and context passing.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from thomas.scheduler_deep._exceptions import JobTimeout
from thomas.scheduler_deep._types import Job, JobStatus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Execution context for a job."""

    job_id: str
    job_name: str
    execution_id: str
    started_at: datetime
    execution_number: int
    previous_result: Any = None
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def elapsed_seconds(self) -> float:
        """Get elapsed execution time in seconds.

        Returns:
            Elapsed time
        """
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()


class JobExecutor:
    """Executes jobs with configurable concurrency."""

    def __init__(
        self,
        max_workers: int = 10,
        executor_type: str = "thread",
        timeout_seconds: int | None = None,
    ) -> None:
        """Initialize job executor.

        Args:
            max_workers: Maximum concurrent workers
            executor_type: "thread" or "process"
            timeout_seconds: Default timeout for jobs

        Raises:
            ValueError: If executor_type is invalid
        """
        if executor_type not in ("thread", "process"):
            raise ValueError("executor_type must be 'thread' or 'process'")

        self.max_workers = max_workers
        self.executor_type = executor_type
        self.timeout_seconds = timeout_seconds
        self._running_jobs: dict[str, Future[Any]] = {}
        self._job_contexts: dict[str, ExecutionContext] = {}
        self._lock = threading.RLock()
        self._execution_counter = 0

        # Create executor based on type
        if executor_type == "thread":
            self.executor = ThreadPoolExecutor(max_workers=max_workers)
        else:
            self.executor = ProcessPoolExecutor(max_workers=max_workers)

    def submit_job(
        self,
        job: Job,
        previous_result: Any = None,
        retry_count: int = 0,
    ) -> str:
        """Submit job for execution.

        Args:
            job: Job to execute
            previous_result: Result from previous execution
            retry_count: Retry attempt count

        Returns:
            Execution ID

        Raises:
            RuntimeError: If executor is closed
        """
        with self._lock:
            execution_id = str(self._execution_counter)
            self._execution_counter += 1

            context = ExecutionContext(
                job_id=job.id,
                job_name=job.name,
                execution_id=execution_id,
                started_at=datetime.now(timezone.utc),
                execution_number=self._execution_counter,
                previous_result=previous_result,
                retry_count=retry_count,
            )

            # Create wrapper function
            timeout = job.timeout_seconds or self.timeout_seconds

            def job_wrapper() -> Any:
                try:
                    # Call job function with context
                    if self._accepts_context(job.func):
                        result = job.func(context, *job.args, **job.kwargs)
                    else:
                        result = job.func(*job.args, **job.kwargs)
                    return result
                except Exception as e:
                    logger.error(f"Job {job.id} failed: {e}")
                    raise

            # Submit to executor
            future = self.executor.submit(job_wrapper)
            self._running_jobs[execution_id] = future
            self._job_contexts[execution_id] = context

            return execution_id

    def cancel_job(self, execution_id: str) -> bool:
        """Cancel running job.

        Args:
            execution_id: Execution ID to cancel

        Returns:
            True if cancellation was successful
        """
        with self._lock:
            future = self._running_jobs.get(execution_id)
            if future is None:
                return False
            return future.cancel()

    def get_result(
        self,
        execution_id: str,
        timeout: float | None = None,
    ) -> Any:
        """Get job execution result.

        Args:
            execution_id: Execution ID
            timeout: Wait timeout in seconds

        Returns:
            Job result

        Raises:
            TimeoutError: If timeout exceeded
            Exception: If job failed
        """
        with self._lock:
            future = self._running_jobs.get(execution_id)
            if future is None:
                raise ValueError(f"Unknown execution ID: {execution_id}")

        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            raise JobTimeout(self._job_contexts[execution_id].job_id, int(timeout) if timeout else 0)

    def is_running(self, execution_id: str) -> bool:
        """Check if job is still running.

        Args:
            execution_id: Execution ID

        Returns:
            True if job is running
        """
        with self._lock:
            future = self._running_jobs.get(execution_id)
            return future is not None and not future.done()

    def get_context(self, execution_id: str) -> ExecutionContext | None:
        """Get execution context.

        Args:
            execution_id: Execution ID

        Returns:
            Execution context or None
        """
        with self._lock:
            return self._job_contexts.get(execution_id)

    def wait_all(self, timeout: float | None = None) -> None:
        """Wait for all jobs to complete.

        Args:
            timeout: Maximum wait time in seconds

        Raises:
            TimeoutError: If timeout exceeded
        """
        with self._lock:
            futures = list(self._running_jobs.values())

        if not futures:
            return

        for future in as_completed(futures, timeout=timeout):
            try:
                future.result()
            except Exception:
                pass

    def get_running_count(self) -> int:
        """Get count of running jobs.

        Returns:
            Number of currently running jobs
        """
        with self._lock:
            return sum(1 for f in self._running_jobs.values() if not f.done())

    def shutdown(self, wait: bool = True, timeout: int = 30) -> None:
        """Shutdown executor.

        Args:
            wait: Wait for jobs to complete
            timeout: Shutdown timeout in seconds
        """
        try:
            self.executor.shutdown(wait=wait)
        except Exception as e:
            logger.error(f"Error shutting down executor: {e}")

    def _accepts_context(self, func: Callable) -> bool:
        """Check if function accepts ExecutionContext parameter.

        Args:
            func: Function to check

        Returns:
            True if first parameter looks like a context
        """
        try:
            import inspect

            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if params:
                first_param = params[0]
                # Check if annotation matches ExecutionContext
                return first_param.annotation is ExecutionContext
            return False
        except Exception:
            return False

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"JobExecutor("
            f"type={self.executor_type}, "
            f"workers={self.max_workers}, "
            f"running={self.get_running_count()})"
        )


class PersistentExecutor:
    """Executor with persistent job state."""

    def __init__(
        self,
        executor: JobExecutor,
        state_dir: str | None = None,
    ) -> None:
        """Initialize persistent executor.

        Args:
            executor: Underlying job executor
            state_dir: Directory for persisting state
        """
        self.executor = executor
        self.state_dir = state_dir
        self._job_states: dict[str, dict[str, Any]] = {}

    def submit_job(
        self,
        job: Job,
        previous_result: Any = None,
        retry_count: int = 0,
    ) -> str:
        """Submit job and persist state.

        Args:
            job: Job to execute
            previous_result: Result from previous execution
            retry_count: Retry attempt count

        Returns:
            Execution ID
        """
        execution_id = self.executor.submit_job(job, previous_result, retry_count)
        self._save_state(execution_id, job)
        return execution_id

    def _save_state(self, execution_id: str, job: Job) -> None:
        """Save job state.

        Args:
            execution_id: Execution ID
            job: Job being executed
        """
        if not self.state_dir:
            return

        self._job_states[execution_id] = {
            "job_id": job.id,
            "execution_id": execution_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": JobStatus.RUNNING.value,
        }
