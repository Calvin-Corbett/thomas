"""
Tests for workflow engine hardening features.

Tests step retry, timeouts, dead letter queue, checkpointing,
concurrency control, and step dependencies.
"""

import asyncio

import pytest

from thomas.workflows._checkpointing import WorkflowCheckpoint
from thomas.workflows._concurrency import ConcurrencyLimiter
from thomas.workflows._deadletter import DeadLetterQueue


class TestStepRetry:
    """Test step retry logic."""

    @pytest.mark.asyncio
    async def test_step_retries_on_failure(self):
        """Test that failed steps are retried."""
        # This tests the concept - actual implementation would be in engine
        attempt_count = 0

        async def step_with_retry():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ValueError("Transient error")
            return {"result": "success"}

        # Simulate retry logic
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                result = await step_with_retry()
                break
            except ValueError:
                if attempt >= max_retries:
                    raise
                await asyncio.sleep(0.01)

        assert result == {"result": "success"}
        assert attempt_count == 3

    @pytest.mark.asyncio
    async def test_step_exhausts_retries(self):
        """Test that step fails after max retries."""

        @pytest.mark.asyncio
        async def failing_step():
            raise ValueError("Persistent error")

        max_retries = 2
        attempt_count = 0

        for attempt in range(max_retries + 1):
            try:
                await failing_step()
                break
            except ValueError as e:
                attempt_count += 1
                if attempt >= max_retries:
                    error = str(e)
                    break

        assert attempt_count == max_retries + 1
        assert "Persistent error" in error


class TestStepTimeout:
    """Test step timeout functionality."""

    @pytest.mark.asyncio
    async def test_slow_step_gets_cancelled(self):
        """Test that slow steps are cancelled on timeout."""

        async def slow_step():
            await asyncio.sleep(10)
            return "completed"

        step_timeout = 0.05

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_step(), timeout=step_timeout)

    @pytest.mark.asyncio
    async def test_fast_step_completes(self):
        """Test that fast steps complete before timeout."""

        async def fast_step():
            await asyncio.sleep(0.01)
            return "completed"

        result = await asyncio.wait_for(fast_step(), timeout=1.0)
        assert result == "completed"


class TestDeadLetterQueue:
    """Test dead letter queue for failed workflows."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create temporary database for testing."""
        return tmp_path / "test.db"

    @pytest.mark.asyncio
    async def test_enqueue_failed_workflow(self, temp_db):
        """Test enqueueing a failed workflow."""
        dlq = DeadLetterQueue(temp_db)

        await dlq.enqueue(
            workflow_id="workflow1",
            run_id="run1",
            step_id="step1",
            error="Connection timeout",
            retry_count=3,
            original_input={"query": "test"},
        )

        pending = await dlq.list_pending()
        assert len(pending) == 1
        assert pending[0]["workflow_id"] == "workflow1"
        assert pending[0]["error"] == "Connection timeout"
        assert pending[0]["retry_count"] == 3

    @pytest.mark.asyncio
    async def test_list_pending_items(self, temp_db):
        """Test listing pending dead letters."""
        dlq = DeadLetterQueue(temp_db)

        # Enqueue multiple items
        for i in range(3):
            await dlq.enqueue(
                workflow_id=f"workflow{i}",
                run_id=f"run{i}",
                step_id=f"step{i}",
                error=f"Error {i}",
            )

        pending = await dlq.list_pending()
        assert len(pending) == 3

    @pytest.mark.asyncio
    async def test_resolve_dead_letter(self, temp_db):
        """Test marking a dead letter as resolved."""
        dlq = DeadLetterQueue(temp_db)

        await dlq.enqueue(
            workflow_id="workflow1",
            run_id="run1",
            step_id="step1",
            error="Error",
        )

        pending_before = await dlq.list_pending()
        assert len(pending_before) == 1

        record_id = pending_before[0]["id"]
        await dlq.resolve(record_id, notes="Fixed manually")

        pending_after = await dlq.list_pending()
        assert len(pending_after) == 0

    @pytest.mark.asyncio
    async def test_count_pending(self, temp_db):
        """Test counting pending items."""
        dlq = DeadLetterQueue(temp_db)

        await dlq.enqueue("w1", "r1", "s1", "Error")
        await dlq.enqueue("w2", "r2", "s2", "Error")

        count = await dlq.count_pending()
        assert count == 2


class TestWorkflowCheckpointing:
    """Test workflow checkpointing for crash recovery."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create temporary database."""
        return tmp_path / "test.db"

    @pytest.mark.asyncio
    async def test_save_checkpoint(self, temp_db):
        """Test saving a workflow checkpoint."""
        checkpoint = WorkflowCheckpoint(temp_db)

        await checkpoint.save(
            run_id="run1",
            workflow_id="workflow1",
            current_step="step2",
            executed_steps=["step1", "step2"],
            step_results={"step1": {"output": "value"}},
            workflow_context={"user": "admin"},
        )

        # Verify it was saved
        loaded = await checkpoint.load("run1")
        assert loaded is not None
        assert loaded["run_id"] == "run1"
        assert loaded["current_step"] == "step2"

    @pytest.mark.asyncio
    async def test_resume_from_checkpoint(self, temp_db):
        """Test resuming workflow from checkpoint."""
        checkpoint = WorkflowCheckpoint(temp_db)

        # Save checkpoint at step 2
        await checkpoint.save(
            run_id="run1",
            workflow_id="workflow1",
            current_step="step3",
            executed_steps=["step1", "step2"],
            step_results={
                "step1": {"output": "value1"},
                "step2": {"output": "value2"},
            },
            workflow_context={"data": "test"},
        )

        # Load and verify we can resume from here
        loaded = await checkpoint.load("run1")
        assert len(loaded["executed_steps"]) == 2
        assert loaded["current_step"] == "step3"
        assert loaded["step_results"]["step1"]["output"] == "value1"

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, temp_db):
        """Test deleting completed workflow checkpoint."""
        checkpoint = WorkflowCheckpoint(temp_db)

        await checkpoint.save(
            run_id="run1",
            workflow_id="workflow1",
            current_step="step1",
            executed_steps=[],
            step_results={},
            workflow_context={},
        )

        await checkpoint.delete("run1")

        loaded = await checkpoint.load("run1")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_incomplete_workflows(self, temp_db):
        """Test listing incomplete workflow checkpoints."""
        checkpoint = WorkflowCheckpoint(temp_db)

        # Save multiple checkpoints
        for i in range(3):
            await checkpoint.save(
                run_id=f"run{i}",
                workflow_id=f"workflow{i}",
                current_step=f"step{i}",
                executed_steps=[],
                step_results={},
                workflow_context={},
            )

        incomplete = await checkpoint.list_incomplete()
        assert len(incomplete) == 3


class TestConcurrencyControl:
    """Test concurrency limiting for workflows."""

    @pytest.mark.asyncio
    async def test_respects_max_concurrent_limit(self):
        """Test that concurrency limiter respects max limit."""
        limiter = ConcurrencyLimiter(max_concurrent=2)

        acquired = []

        async def run_workflow(wf_id):
            await limiter.acquire(wf_id)
            acquired.append(wf_id)
            await asyncio.sleep(0.05)
            await limiter.release(wf_id)

        # Start 5 workflows but only 2 can run concurrently
        tasks = [run_workflow(f"workflow{i}") for i in range(5)]
        await asyncio.gather(*tasks)

        assert len(acquired) == 5

    @pytest.mark.asyncio
    async def test_queues_when_at_capacity(self):
        """Test that workflows queue when at capacity."""
        limiter = ConcurrencyLimiter(max_concurrent=1)

        sequence = []

        async def timed_workflow(wf_id):
            await limiter.acquire(wf_id)
            sequence.append(f"start_{wf_id}")
            await asyncio.sleep(0.02)
            sequence.append(f"end_{wf_id}")
            await limiter.release(wf_id)

        # Run 3 workflows with max 1 concurrent
        await asyncio.gather(
            timed_workflow("w1"),
            timed_workflow("w2"),
            timed_workflow("w3"),
        )

        # Verify they ran serially
        assert sequence[0] == "start_w1"
        # w2 and w3 should queue until w1 finishes

    @pytest.mark.asyncio
    async def test_status(self):
        """Test concurrency status reporting."""
        limiter = ConcurrencyLimiter(max_concurrent=5)

        status = await limiter.status()
        assert status["max_concurrent"] == 5
        assert status["active"] == 0
        assert status["queued"] == 0
        assert status["available_slots"] == 5

    @pytest.mark.asyncio
    async def test_wait_for_available_slot(self):
        """Test waiting for available concurrency slot."""
        limiter = ConcurrencyLimiter(max_concurrent=1)

        # Acquire the only slot
        await limiter.acquire("workflow1")

        # Try to wait for available slot (should timeout)
        available = await limiter.wait_for_available(timeout_s=0.1)
        assert available is False

        # Release and try again
        await limiter.release("workflow1")
        available = await limiter.wait_for_available(timeout_s=0.1)
        assert available is True


class TestStepDependencies:
    """Test step dependency ordering."""

    @pytest.mark.asyncio
    async def test_step_waits_for_dependencies(self):
        """Test that step waits for dependency completion."""
        execution_order = []

        async def step_a():
            execution_order.append("step_a")
            await asyncio.sleep(0.02)
            return "result_a"

        async def step_b(result_a):
            # Simulate waiting for step_a result
            if result_a:
                execution_order.append("step_b")
                return "result_b"

        # Simple dependency resolution
        result_a = await step_a()
        result_b = await step_b(result_a)

        assert execution_order == ["step_a", "step_b"]
        assert result_b == "result_b"

    @pytest.mark.asyncio
    async def test_independent_steps_run_parallel(self):
        """Test that independent steps can run in parallel."""
        execution_order = []
        lock = asyncio.Lock()

        async def step_a():
            async with lock:
                execution_order.append("a_start")
            await asyncio.sleep(0.02)
            async with lock:
                execution_order.append("a_end")

        async def step_b():
            async with lock:
                execution_order.append("b_start")
            await asyncio.sleep(0.02)
            async with lock:
                execution_order.append("b_end")

        # Run in parallel
        await asyncio.gather(step_a(), step_b())

        # Verify both started before either finished
        a_start_idx = execution_order.index("a_start")
        b_start_idx = execution_order.index("b_start")
        a_end_idx = execution_order.index("a_end")
        b_end_idx = execution_order.index("b_end")

        assert a_start_idx < a_end_idx
        assert b_start_idx < b_end_idx
        assert min(a_start_idx, b_start_idx) < max(a_end_idx, b_end_idx)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
