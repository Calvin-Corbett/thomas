"""
Tests for sagas and long-running workflows.

Tests saga execution, compensation, timeouts, and state tracking.
"""

import asyncio

import pytest

from . import Event, EventTriggeredSaga, Saga, SagaBuilder, SagaExecutor, SagaStatus


class OrderEvent(Event):
    """Base order event."""

    def __init__(self, event_type: str, order_id: str):
        super().__init__(event_type, f"order-{order_id}")
        self.order_id = order_id


class OrderPlaced(OrderEvent):
    """Order placed event."""

    def __init__(self, order_id: str, amount: float):
        super().__init__("OrderPlaced", order_id)
        self.amount = amount


class OrderConfirmed(OrderEvent):
    """Order confirmed event."""

    def __init__(self, order_id: str):
        super().__init__("OrderConfirmed", order_id)


@pytest.fixture
def executor():
    """Create saga executor."""
    return SagaExecutor()


@pytest.mark.asyncio
async def test_saga_execution(executor):
    """Test basic saga execution."""
    execution_log = []

    async def step1():
        execution_log.append("step1")

    async def step2():
        execution_log.append("step2")

    saga = Saga("test-saga")
    saga.add_step("charge_card", step1)
    saga.add_step("send_confirmation", step2)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPLETED
    assert len(execution_log) == 2


@pytest.mark.asyncio
async def test_saga_step_failure(executor):
    """Test saga failure handling."""

    async def step1():
        pass

    async def step2():
        raise ValueError("Step failed")

    async def compensation1():
        pass

    saga = Saga("test-saga")
    saga.add_step("charge_card", step1, compensation1)
    saga.add_step("send_confirmation", step2)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPENSATED
    assert state.failed_step == "send_confirmation"


@pytest.mark.asyncio
async def test_saga_compensation(executor):
    """Test compensation execution."""
    log = []

    async def step():
        log.append("action")

    async def compensate():
        log.append("compensation")

    saga = Saga("test-saga")
    saga.add_step("action", step, compensate)

    async def failing_step():
        raise Exception("Fail")

    saga.add_step("failing", failing_step)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPENSATED
    assert "compensation" in log


@pytest.mark.asyncio
async def test_saga_step_timeout(executor):
    """Test step timeout."""

    async def slow_step():
        await asyncio.sleep(10)

    saga = Saga("test-saga")
    saga.add_step("slow", slow_step, timeout=0.1)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPENSATED


@pytest.mark.asyncio
async def test_saga_state_tracking(executor):
    """Test saga state."""

    async def step1():
        pass

    async def step2():
        pass

    saga = Saga("order-123")
    saga.add_step("charge", step1)
    saga.add_step("reserve", step2)

    state = await executor.execute(saga)

    assert state.saga_id == "order-123"
    assert len(state.completed_steps) == 2


@pytest.mark.asyncio
async def test_saga_context(executor):
    """Test saga with context data."""

    async def step():
        pass

    saga = Saga("test-saga")
    saga.state.context = {"order_id": "123", "amount": 100.0}
    saga.add_step("process", step)

    state = await executor.execute(saga)

    assert state.context["order_id"] == "123"


@pytest.mark.asyncio
async def test_saga_duration():
    """Test saga duration tracking."""
    executor = SagaExecutor()

    async def step():
        await asyncio.sleep(0.1)

    saga = Saga("test-saga")
    saga.add_step("wait", step)

    state = await executor.execute(saga)

    assert state.duration().total_seconds() >= 0.1


def test_saga_builder():
    """Test saga builder."""

    async def step1():
        pass

    async def step2():
        pass

    async def undo():
        pass

    saga = SagaBuilder("order-123").add_step("charge", step1, undo).add_step("reserve", step2).build()

    assert len(saga.get_steps()) == 2


@pytest.mark.asyncio
async def test_event_triggered_saga():
    """Test event triggered saga."""
    saga_executed = False

    manager = EventTriggeredSaga(SagaExecutor())

    @manager.on_event_type("OrderPlaced")
    async def handle_order_placed(event: OrderEvent) -> Saga:
        nonlocal saga_executed

        async def process():
            nonlocal saga_executed
            saga_executed = True

        saga = Saga(f"order-{event.order_id}")
        saga.add_step("process", process)
        return saga

    event = OrderPlaced("123", 100.0)
    state = await manager.handle_event(event)

    assert saga_executed
    assert state.status == SagaStatus.COMPLETED


@pytest.mark.asyncio
async def test_saga_get_state(executor):
    """Test retrieving saga state."""

    async def step():
        pass

    saga = Saga("test-saga")
    saga.add_step("step", step)

    state = await executor.execute(saga)
    retrieved = executor.get_saga_state("test-saga")

    assert retrieved is not None
    assert retrieved.saga_id == "test-saga"


@pytest.mark.asyncio
async def test_saga_get_all_states(executor):
    """Test getting all saga states."""

    async def step():
        pass

    for i in range(3):
        saga = Saga(f"saga-{i}")
        saga.add_step("step", step)
        await executor.execute(saga)

    all_states = executor.get_all_sagas()

    assert len(all_states) == 3


@pytest.mark.asyncio
async def test_compensation_order():
    """Test compensation runs in reverse."""
    execution_order = []

    async def step1():
        execution_order.append("step1")

    async def step2():
        execution_order.append("step2")

    async def undo1():
        execution_order.append("undo1")

    async def undo2():
        execution_order.append("undo2")

    async def failing():
        execution_order.append("fail")
        raise Exception("Failed")

    executor = SagaExecutor()

    saga = Saga("test")
    saga.add_step("action1", step1, undo1)
    saga.add_step("action2", step2, undo2)
    saga.add_step("failing", failing)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPENSATED

    undo_indices = [i for i, x in enumerate(execution_order) if "undo" in x]
    assert execution_order[undo_indices[0]] == "undo2"
    assert execution_order[undo_indices[1]] == "undo1"


@pytest.mark.asyncio
async def test_saga_no_compensation():
    """Test saga step without compensation."""

    async def step():
        pass

    async def failing():
        raise Exception("Fail")

    executor = SagaExecutor()

    saga = Saga("test")
    saga.add_step("no_undo", step)
    saga.add_step("fail", failing)

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPENSATED


@pytest.mark.asyncio
async def test_event_triggered_saga_no_handler():
    """Test event with no saga handler."""
    manager = EventTriggeredSaga(SagaExecutor())

    event = OrderPlaced("123", 100.0)
    result = await manager.handle_event(event)

    assert result is None


@pytest.mark.asyncio
async def test_saga_multiple_steps_success():
    """Test saga with multiple successful steps."""
    log = []

    executor = SagaExecutor()

    saga = Saga("test")
    saga.add_step("step1", lambda: asyncio.coroutine(lambda: log.append(1))())
    saga.add_step("step2", lambda: asyncio.coroutine(lambda: log.append(2))())
    saga.add_step("step3", lambda: asyncio.coroutine(lambda: log.append(3))())

    state = await executor.execute(saga)

    assert state.status == SagaStatus.COMPLETED
    assert len(state.completed_steps) == 3
