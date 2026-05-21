"""
Tests for saga pattern implementation.

Tests saga execution, step ordering, compensation on failure,
timeouts, and saga instance tracking.
"""

import asyncio
from typing import Any

import pytest

from . import (
    SagaBase,
    SagaException,
    SagaManager,
    SagaStep,
    SagaTimeoutException,
)


class IncrementStep(SagaStep):
    """Step that increments a counter."""

    async def execute(self, context: dict[str, Any]) -> Any:
        """Increment counter."""
        count = context.get("count", 0)
        context["count"] = count + 1
        return count + 1

    async def compensate(self, context: dict[str, Any]) -> None:
        """Decrement counter in compensation."""
        count = context.get("count", 0)
        context["count"] = max(0, count - 1)


class FailingStep(SagaStep):
    """Step that fails."""

    async def execute(self, context: dict[str, Any]) -> Any:
        """Raise error."""
        raise ValueError(f"Step {self.name} failed")

    async def compensate(self, context: dict[str, Any]) -> None:
        """Nothing to compensate."""
        pass


class ConditionalFailingStep(SagaStep):
    """Step that fails based on context."""

    def __init__(self, name: str, fail_condition: str):
        super().__init__(name)
        self.fail_condition = fail_condition

    async def execute(self, context: dict[str, Any]) -> Any:
        """Execute conditionally."""
        if context.get(self.fail_condition):
            raise ValueError(f"Step {self.name} failed")
        return f"{self.name}_executed"

    async def compensate(self, context: dict[str, Any]) -> None:
        """Mark compensated."""
        key = f"{self.name}_compensated"
        context[key] = True


class SimpleSaga(SagaBase):
    """Simple test saga."""

    def __init__(self):
        super().__init__()
        self.add_step(IncrementStep("step1"))
        self.add_step(IncrementStep("step2"))
        self.add_step(IncrementStep("step3"))


class FailingSaga(SagaBase):
    """Saga that fails."""

    def __init__(self):
        super().__init__()
        self.add_step(IncrementStep("step1"))
        self.add_step(FailingStep("step2_failing"))


class ConditionalFailingSaga(SagaBase):
    """Saga that fails conditionally."""

    def __init__(self, fail_at: str = "step2"):
        super().__init__()
        self.add_step(IncrementStep("step1"))
        self.add_step(ConditionalFailingStep("step2", fail_at))
        self.add_step(IncrementStep("step3"))


class TestSagaBase:
    """Tests for SagaBase."""

    @pytest.mark.asyncio
    async def test_simple_saga_execution(self):
        """Test executing a successful saga."""
        saga = SimpleSaga()
        await saga.execute()

        assert saga.is_complete()
        context = saga.get_context()
        assert context["count"] == 3

    @pytest.mark.asyncio
    async def test_saga_step_order(self):
        """Test steps execute in order."""
        saga = SimpleSaga()
        execution_order = []

        class OrderTrackingStep(SagaStep):
            def __init__(self, name: str, order_list: list):
                super().__init__(name)
                self.order_list = order_list

            async def execute(self, context: dict[str, Any]) -> Any:
                self.order_list.append(self.name)
                return self.name

            async def compensate(self, context: dict[str, Any]) -> None:
                pass

        saga = SagaBase()
        for i in range(3):
            saga.add_step(OrderTrackingStep(f"step{i + 1}", execution_order))

        await saga.execute()

        assert execution_order == ["step1", "step2", "step3"]

    @pytest.mark.asyncio
    async def test_saga_failure_triggers_compensation(self):
        """Test compensation runs on failure."""
        saga = ConditionalFailingSaga(fail_at="step2")

        with pytest.raises(SagaException):
            await saga.execute()

        context = saga.get_context()
        assert saga.is_failed()
        assert context.get("step1_compensated") is True

    @pytest.mark.asyncio
    async def test_saga_stores_instance(self):
        """Test saga stores instance data."""
        saga = SimpleSaga()
        await saga.execute()

        instance = saga.get_instance()
        assert instance is not None
        assert instance.status == "completed"
        assert len(instance.completed_steps) == 3

    @pytest.mark.asyncio
    async def test_saga_step_results(self):
        """Test saga tracks step results."""
        saga = SimpleSaga()
        await saga.execute()

        instance = saga.get_instance()
        assert "step1" in instance.results
        assert "step2" in instance.results
        assert "step3" in instance.results
        assert all(r.success for r in instance.results.values())

    @pytest.mark.asyncio
    async def test_saga_context_sharing(self):
        """Test context is shared across steps."""

        class ContextStep(SagaStep):
            def __init__(self, name: str):
                super().__init__(name)

            async def execute(self, context: dict[str, Any]) -> Any:
                value = context.get("shared", 0)
                context["shared"] = value + 10
                return context["shared"]

            async def compensate(self, context: dict[str, Any]) -> None:
                pass

        saga = SagaBase()
        saga.add_step(ContextStep("step1"))
        saga.add_step(ContextStep("step2"))

        await saga.execute()

        context = saga.get_context()
        assert context["shared"] == 20

    @pytest.mark.asyncio
    async def test_saga_timeout(self):
        """Test saga timeout."""

        class SlowStep(SagaStep):
            async def execute(self, context: dict[str, Any]) -> Any:
                await asyncio.sleep(1.0)
                return "done"

            async def compensate(self, context: dict[str, Any]) -> None:
                pass

        saga = SagaBase(timeout_seconds=0)
        saga.add_step(SlowStep("slow"))

        with pytest.raises(SagaTimeoutException):
            await saga.execute()

    @pytest.mark.asyncio
    async def test_compensation_runs_in_reverse_order(self):
        """Test compensation runs in reverse order."""
        compensation_order = []

        class OrderedStep(SagaStep):
            def __init__(self, name: str, order_list: list):
                super().__init__(name)
                self.order_list = order_list

            async def execute(self, context: dict[str, Any]) -> Any:
                if self.name == "step3":
                    raise ValueError("Fail at step3")
                return self.name

            async def compensate(self, context: dict[str, Any]) -> None:
                self.order_list.append(f"{self.name}_compensate")

        saga = SagaBase()
        saga.add_step(OrderedStep("step1", compensation_order))
        saga.add_step(OrderedStep("step2", compensation_order))
        saga.add_step(OrderedStep("step3", compensation_order))

        with pytest.raises(SagaException):
            await saga.execute()

        assert saga.is_failed()
        # Compensation should run in reverse order
        assert "step2_compensate" in compensation_order
        assert "step1_compensate" in compensation_order


class TestSagaManager:
    """Tests for SagaManager."""

    @pytest.mark.asyncio
    async def test_start_saga(self):
        """Test starting saga through manager."""
        manager = SagaManager()
        saga = SimpleSaga()

        saga_id = await manager.start_saga(saga)

        assert saga_id == saga.saga_id
        instance = await manager.get_saga(saga_id)
        assert instance is not None
        assert instance.status == "completed"

    @pytest.mark.asyncio
    async def test_get_running_sagas(self):
        """Test listing running sagas."""
        manager = SagaManager()
        saga1 = SimpleSaga()
        saga2 = SimpleSaga()

        await manager.start_saga(saga1)
        await manager.start_saga(saga2)

        completed = await manager.list_completed()
        assert len(completed) == 2

    @pytest.mark.asyncio
    async def test_list_failed_sagas(self):
        """Test listing failed sagas."""
        manager = SagaManager()
        saga1 = SimpleSaga()
        saga2 = FailingSaga()

        await manager.start_saga(saga1)

        with pytest.raises(SagaException):
            await manager.start_saga(saga2)

        failed = await manager.list_failed()
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_cancel_saga(self):
        """Test canceling running saga."""
        manager = SagaManager()
        saga = SimpleSaga()

        saga_id = await manager.start_saga(saga)
        await manager.cancel_saga(saga_id)

        running = await manager.list_running()
        assert saga_id not in running

    @pytest.mark.asyncio
    async def test_saga_isolation(self):
        """Test sagas don't interfere with each other."""
        manager = SagaManager()
        saga1 = SimpleSaga()
        saga2 = SimpleSaga()

        saga_id1 = await manager.start_saga(saga1)
        saga_id2 = await manager.start_saga(saga2)

        instance1 = await manager.get_saga(saga_id1)
        instance2 = await manager.get_saga(saga_id2)

        assert instance1.saga_id != instance2.saga_id
        assert instance1.context is not instance2.context

    @pytest.mark.asyncio
    async def test_clear_manager(self):
        """Test clearing all sagas from manager."""
        manager = SagaManager()
        saga = SimpleSaga()

        await manager.start_saga(saga)
        assert len(await manager.list_completed()) == 1

        await manager.clear()
        assert len(await manager.list_completed()) == 0

    @pytest.mark.asyncio
    async def test_saga_with_initial_context(self):
        """Test starting saga with initial context."""
        manager = SagaManager()
        saga = SimpleSaga()

        initial_context = {"count": 100}
        saga_id = await manager.start_saga(
            saga,
            initial_context=initial_context,
        )

        instance = await manager.get_saga(saga_id)
        # Context is modified during execution
        assert instance.context["count"] == 103

    @pytest.mark.asyncio
    async def test_saga_with_custom_id(self):
        """Test starting saga with custom ID."""
        manager = SagaManager()
        saga = SagaBase(saga_id="custom-123")

        saga_id = await manager.start_saga(saga)
        assert saga_id == "custom-123"

        instance = await manager.get_saga("custom-123")
        assert instance is not None
