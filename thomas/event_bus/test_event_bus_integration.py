"""
Full integration tests for complete CQRS pipeline.

Tests end-to-end workflows combining events, aggregates, projections, and sagas.
"""

import asyncio

import pytest

from . import (
    AggregateRepository,
    AggregateRoot,
    CatchUpProjection,
    Event,
    EventBusContext,
    EventStore,
    EventTriggeredSaga,
    InMemoryProjection,
    ProjectionManager,
    Saga,
    SagaExecutor,
    SagaStatus,
)


class OrderCreated(Event):
    """Order created event."""

    def __init__(self, order_id: str, customer_id: str, amount: float):
        super().__init__("OrderCreated", f"order-{order_id}")
        self.order_id = order_id
        self.customer_id = customer_id
        self.amount = amount


class PaymentProcessed(Event):
    """Payment processed event."""

    def __init__(self, order_id: str):
        super().__init__("PaymentProcessed", f"order-{order_id}")
        self.order_id = order_id


class InventoryReserved(Event):
    """Inventory reserved event."""

    def __init__(self, order_id: str):
        super().__init__("InventoryReserved", f"order-{order_id}")
        self.order_id = order_id


class OrderConfirmed(Event):
    """Order confirmed event."""

    def __init__(self, order_id: str):
        super().__init__("OrderConfirmed", f"order-{order_id}")
        self.order_id = order_id


class OrderAggregate(AggregateRoot):
    """Order aggregate."""

    def __init__(self, order_id: str):
        super().__init__(order_id)
        self._state = {
            "order_id": order_id,
            "customer_id": None,
            "amount": 0.0,
            "status": "pending",
        }

    def _on_order_created(self, event: OrderCreated):
        self._state["customer_id"] = event.customer_id
        self._state["amount"] = event.amount

    def _on_payment_processed(self, event: PaymentProcessed):
        self._state["status"] = "payment_done"

    def _on_inventory_reserved(self, event: InventoryReserved):
        self._state["status"] = "inventory_done"

    def _on_order_confirmed(self, event: OrderConfirmed):
        self._state["status"] = "confirmed"

    def create(self, customer_id: str, amount: float):
        event = OrderCreated(self.id, customer_id, amount)
        self.record_event(event)

    def process_payment(self):
        event = PaymentProcessed(self.id)
        self.record_event(event)

    def reserve_inventory(self):
        event = InventoryReserved(self.id)
        self.record_event(event)

    def confirm(self):
        event = OrderConfirmed(self.id)
        self.record_event(event)


class OrderSummaryProjection(InMemoryProjection):
    """Projection tracking order counts."""

    def __init__(self):
        super().__init__(
            "order_summary",
            {
                "total_orders": 0,
                "confirmed_orders": 0,
                "total_revenue": 0.0,
            },
        )

    async def _on_order_created(self, event: OrderCreated):
        self._state["total_orders"] += 1
        self._state["total_revenue"] += event.amount

    async def _on_order_confirmed(self, event: OrderConfirmed):
        self._state["confirmed_orders"] += 1


@pytest.mark.asyncio
async def test_end_to_end_cqrs_pipeline():
    """Test complete CQRS pipeline."""
    store = EventStore()
    repository = AggregateRepository(store)

    order = OrderAggregate("order-123")
    order.create("customer-1", 100.0)

    repository.save(order)

    loaded = repository.load(OrderAggregate, "order-123")

    assert loaded.get_state_value("customer_id") == "customer-1"
    assert loaded.get_state_value("amount") == 100.0


@pytest.mark.asyncio
async def test_event_bus_to_projections():
    """Test events flowing from bus to projections."""
    store = EventStore()
    manager = ProjectionManager(store)
    projection = OrderSummaryProjection()

    manager.register_projection(projection)

    event = OrderCreated("order-1", "customer-1", 100.0)
    await manager.handle_event(event)

    state = projection.get_state()
    assert state["total_orders"] == 1
    assert state["total_revenue"] == 100.0


@pytest.mark.asyncio
async def test_aggregate_to_projections():
    """Test aggregate changes reflected in projections."""
    store = EventStore()
    repository = AggregateRepository(store)
    manager = ProjectionManager(store)
    projection = OrderSummaryProjection()

    manager.register_projection(projection)

    order = OrderAggregate("order-123")
    order.create("customer-1", 150.0)
    order.confirm()

    for event in order.get_uncommitted_events():
        await manager.handle_event(event)

    repository.save(order)

    state = projection.get_state()
    assert state["total_orders"] == 1
    assert state["confirmed_orders"] == 1


@pytest.mark.asyncio
async def test_event_replay_to_projection():
    """Test replaying events to catch up projection."""
    store = EventStore()

    store.append("order-123", [OrderCreated("order-123", "customer-1", 100.0)])
    store.append("order-123", [OrderConfirmed("order-123")])

    projection = OrderSummaryProjection()
    catchup = CatchUpProjection(store)

    await catchup.catchup(projection)

    state = projection.get_state()
    assert state["total_orders"] == 1
    assert state["confirmed_orders"] == 1


@pytest.mark.asyncio
async def test_saga_triggered_by_event():
    """Test saga triggered by event."""
    saga_steps = []

    executor = SagaExecutor()
    manager = EventTriggeredSaga(executor)

    @manager.on_event_type("OrderCreated")
    async def handle_order_placed(event: OrderCreated) -> Saga:
        async def process_payment():
            saga_steps.append("payment")

        async def reserve_inventory():
            saga_steps.append("inventory")

        saga = Saga(f"order-{event.order_id}")
        saga.add_step("payment", process_payment)
        saga.add_step("inventory", reserve_inventory)
        return saga

    event = OrderCreated("order-1", "customer-1", 100.0)
    state = await manager.handle_event(event)

    assert state.status == SagaStatus.COMPLETED
    assert "payment" in saga_steps
    assert "inventory" in saga_steps


@pytest.mark.asyncio
async def test_complete_order_workflow():
    """Test complete order processing workflow."""
    store = EventStore()
    repository = AggregateRepository(store)
    manager = ProjectionManager(store)
    projection = OrderSummaryProjection()

    manager.register_projection(projection)

    order = OrderAggregate("order-123")
    order.create("customer-1", 150.0)

    for event in order.get_uncommitted_events():
        await manager.handle_event(event)

    repository.save(order)

    loaded = repository.load(OrderAggregate, "order-123")

    assert loaded.version == 1
    assert loaded.get_state_value("status") == "pending"

    loaded.process_payment()
    loaded.reserve_inventory()
    loaded.confirm()

    for event in loaded.get_uncommitted_events():
        await manager.handle_event(event)

    repository.save(loaded)

    projection_state = projection.get_state()
    assert projection_state["total_orders"] == 1


@pytest.mark.asyncio
async def test_event_bus_integration():
    """Test event bus integration with subscribers."""
    store = EventStore()
    received_events = []

    async def order_handler(event: Event):
        received_events.append(event)

    async with EventBusContext() as bus:
        bus.subscribe(order_handler, event_types={"OrderCreated"})

        event = OrderCreated("order-1", "customer-1", 100.0)
        await bus.publish(event)

        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert isinstance(received_events[0], OrderCreated)


@pytest.mark.asyncio
async def test_snapshot_with_projections():
    """Test snapshots working with projections."""
    store = EventStore()
    repository = AggregateRepository(store)

    order = OrderAggregate("order-123")
    order.create("customer-1", 100.0)
    order.process_payment()

    repository.save(order)
    repository.save_snapshot(order)

    order.reserve_inventory()
    order.confirm()

    repository.save(order)

    loaded = repository.load(OrderAggregate, "order-123")

    assert loaded.version == 4
    assert loaded.get_state_value("status") == "confirmed"


@pytest.mark.asyncio
async def test_multiple_aggregates_same_event():
    """Test handling same event type across aggregates."""
    store = EventStore()
    repository = AggregateRepository(store)
    manager = ProjectionManager(store)
    projection = OrderSummaryProjection()

    manager.register_projection(projection)

    for i in range(3):
        order = OrderAggregate(f"order-{i}")
        order.create(f"customer-{i}", float(100 * (i + 1)))

        for event in order.get_uncommitted_events():
            await manager.handle_event(event)

        repository.save(order)

    state = projection.get_state()
    assert state["total_orders"] == 3
    assert state["total_revenue"] == 600.0


@pytest.mark.asyncio
async def test_projection_rebuild_from_store():
    """Test rebuilding projections from store."""
    store = EventStore()

    store.append("order-1", [OrderCreated("order-1", "customer-1", 100.0)])
    store.append("order-2", [OrderCreated("order-2", "customer-2", 200.0)])
    store.append("order-1", [OrderConfirmed("order-1")])

    projection = OrderSummaryProjection()
    catchup = CatchUpProjection(store)

    await catchup.rebuild(projection)

    state = projection.get_state()
    assert state["total_orders"] == 2
    assert state["confirmed_orders"] == 1
    assert state["total_revenue"] == 300.0


@pytest.mark.asyncio
async def test_concurrent_order_creation():
    """Test handling concurrent order creation."""
    store = EventStore()
    manager = ProjectionManager(store)
    projection = OrderSummaryProjection()

    manager.register_projection(projection)

    async def create_order(order_id: str):
        event = OrderCreated(order_id, f"customer-{order_id}", 100.0)
        await manager.handle_event(event)

    tasks = [create_order(f"order-{i}") for i in range(10)]
    await asyncio.gather(*tasks)

    state = projection.get_state()
    assert state["total_orders"] == 10
