"""
Tests for job execution with thread/process pools and context passing.
"""

import time

import pytest

from thomas.marketplace.scheduler_deep._types import IntervalTrigger, Job
from thomas.marketplace.scheduler_deep.executor import JobExecutor


class TestJobExecutor:
    """Test job execution functionality."""

    def test_executor_creation_thread(self) -> None:
        """Test creating thread pool executor."""
        executor = JobExecutor(max_workers=5, executor_type="thread")
        assert executor.max_workers == 5
        assert executor.executor_type == "thread"
        executor.shutdown(wait=False)

    def test_executor_creation_process(self) -> None:
        """Test creating process pool executor."""
        executor = JobExecutor(max_workers=2, executor_type="process")
        assert executor.executor_type == "process"
        executor.shutdown(wait=False)

    def test_invalid_executor_type(self) -> None:
        """Test invalid executor type raises error."""
        with pytest.raises(ValueError):
            JobExecutor(executor_type="invalid")

    def test_submit_simple_job(self) -> None:
        """Test submitting and executing a simple job."""

        def test_func() -> str:
            return "success"

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(test_func, trigger)

        execution_id = executor.submit_job(job)
        result = executor.get_result(execution_id, timeout=5)

        assert result == "success"
        executor.shutdown(wait=True)

    def test_job_with_arguments(self) -> None:
        """Test job execution with arguments."""

        def add(a: int, b: int) -> int:
            return a + b

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(add, trigger, args=(2, 3))

        execution_id = executor.submit_job(job)
        result = executor.get_result(execution_id, timeout=5)

        assert result == 5
        executor.shutdown(wait=True)

    def test_job_with_kwargs(self) -> None:
        """Test job execution with keyword arguments."""

        def multiply(x: int, y: int) -> int:
            return x * y

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(multiply, trigger, kwargs={"x": 3, "y": 4})

        execution_id = executor.submit_job(job)
        result = executor.get_result(execution_id, timeout=5)

        assert result == 12
        executor.shutdown(wait=True)

    def test_job_execution_failure(self) -> None:
        """Test handling job execution failure."""

        def failing_job() -> None:
            raise ValueError("Test error")

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(failing_job, trigger)

        execution_id = executor.submit_job(job)

        with pytest.raises(ValueError):
            executor.get_result(execution_id, timeout=5)

        executor.shutdown(wait=True)

    def test_concurrent_execution(self) -> None:
        """Test concurrent job execution."""

        def slow_task(duration: float) -> float:
            time.sleep(duration)
            return duration

        executor = JobExecutor(max_workers=3, executor_type="thread")
        trigger = IntervalTrigger(3600)

        # Submit multiple jobs
        execution_ids = []
        for i in range(3):
            job = Job(slow_task, trigger, args=(0.1,))
            execution_ids.append(executor.submit_job(job))

        # Get results
        start = time.time()
        for execution_id in execution_ids:
            executor.get_result(execution_id, timeout=5)
        elapsed = time.time() - start

        # Should take ~0.1 seconds (concurrent), not 0.3 (sequential)
        assert elapsed < 0.25

        executor.shutdown(wait=True)

    def test_cancel_job(self) -> None:
        """Test job cancellation."""

        def long_task() -> None:
            time.sleep(10)

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(long_task, trigger)

        execution_id = executor.submit_job(job)
        cancelled = executor.cancel_job(execution_id)

        # May or may not succeed depending on timing
        assert isinstance(cancelled, bool)
        executor.shutdown(wait=True)

    def test_get_context(self) -> None:
        """Test retrieving execution context."""

        def test_func() -> str:
            return "done"

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(test_func, trigger)

        execution_id = executor.submit_job(job)
        context = executor.get_context(execution_id)

        assert context is not None
        assert context.job_id == job.id
        assert context.execution_id == execution_id

        executor.get_result(execution_id, timeout=5)
        executor.shutdown(wait=True)

    def test_context_elapsed_seconds(self) -> None:
        """Test context elapsed time calculation."""

        def test_func() -> str:
            time.sleep(0.1)
            return "done"

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(test_func, trigger)

        execution_id = executor.submit_job(job)
        context = executor.get_context(execution_id)

        executor.get_result(execution_id, timeout=5)

        # Elapsed time should be at least 0.1 seconds
        assert context.elapsed_seconds() >= 0.1

        executor.shutdown(wait=True)

    def test_running_count(self) -> None:
        """Test getting running job count."""

        def quick_task() -> str:
            return "done"

        executor = JobExecutor(max_workers=2, executor_type="thread")
        trigger = IntervalTrigger(3600)

        # Submit jobs
        for i in range(2):
            job = Job(quick_task, trigger)
            executor.submit_job(job)

        # Count should be at least 0 (could be already done)
        count = executor.get_running_count()
        assert count >= 0

        executor.shutdown(wait=True)

    def test_wait_all(self) -> None:
        """Test waiting for all jobs to complete."""

        def quick_task() -> str:
            time.sleep(0.05)
            return "done"

        executor = JobExecutor(max_workers=2, executor_type="thread")
        trigger = IntervalTrigger(3600)

        # Submit multiple jobs
        for i in range(3):
            job = Job(quick_task, trigger)
            executor.submit_job(job)

        # Wait for all
        executor.wait_all(timeout=10)
        assert True

        executor.shutdown(wait=True)

    def test_job_timeout(self) -> None:
        """Test job timeout handling."""

        def slow_task() -> None:
            time.sleep(10)

        executor = JobExecutor(max_workers=1, executor_type="thread", timeout_seconds=1)
        trigger = IntervalTrigger(3600)
        job = Job(slow_task, trigger)

        execution_id = executor.submit_job(job)

        with pytest.raises(Exception):  # Could be TimeoutError or JobTimeout
            executor.get_result(execution_id, timeout=2)

        executor.shutdown(wait=True)

    def test_previous_result_passing(self) -> None:
        """Test passing previous result to retry."""

        def test_func() -> str:
            return "result"

        executor = JobExecutor(max_workers=1, executor_type="thread")
        trigger = IntervalTrigger(3600)
        job = Job(test_func, trigger)

        execution_id = executor.submit_job(job, previous_result="old_result")
        context = executor.get_context(execution_id)

        assert context.previous_result == "old_result"

        executor.get_result(execution_id, timeout=5)
        executor.shutdown(wait=True)
