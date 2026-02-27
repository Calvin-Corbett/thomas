"""
Tests for event projections.

Tests catch-up, live projections, rebuild, and state management.
"""

import pytest

from . import (
    AggregateProjection,
    CatchUpProjection,
    Event,
    EventStore,
    InMemoryProjection,
    ProjectionManager,
    ProjectionStatus,
)


class OrderEvent(Event):
    """Base order event."""

    def __init__(self, event_type: str, order_id: str):
        super().__init__(event_type, f"order-{order_id}")
        self.order_id = order_id


class OrderCreated(OrderEvent):
    """Order created event."""

    def __init__(self, order_id: str, amount: float):
        super().__init__("OrderCreated", order_id)
        self.amount = amount


class OrderShipped(OrderEvent):
    """Order shipped event."""

    def __init__(self, order_id: str):
        super().__init__("OrderShipped", order_id)


class OrderCancelled(OrderEvent):
    """Order cancelled event."""

    def __init__(self, order_id: str):
        super().__init__("OrderCancelled", order_id)


class OrderCountProjection(InMemoryProjection):
    """Counts orders by status."""

    def __init__(self):
        super().__init__("order_count", {"created": 0, "shipped": 0, "cancelled": 0})

    async def _on_order_created(self, event: OrderEvent):
        self._state["created"] += 1

    async def _on_order_shipped(self, event: OrderEvent):
        self._state["shipped"] += 1

    async def _on_order_cancelled(self, event: OrderEvent):
        self._state["cancelled"] += 1


class OrderDetailProjection(AggregateProjection):
    """Tracks individual order details."""

    def __init__(self):
        super().__init__("order_details")

    async def _on_order_created(self, event: OrderEvent, state: dict):
        state["amount"] = event.amount
        state["status"] = "created"

    async def _on_order_shipped(self, event: OrderEvent, state: dict):
        state["status"] = "shipped"

    async def _on_order_cancelled(self, event: OrderEvent, state: dict):
        state["status"] = "cancelled"


@pytest.fixture
def store():
    """Create event store."""
    return EventStore()


@pytest.fixture
def populated_store(store):
    """Create store with sample events."""
    store.append("order-1", [OrderCreated("1", 100.0)])
    store.append("order-1", [OrderShipped("1")])
    store.append("order-2", [OrderCreated("2", 200.0)])
    store.append("order-2", [OrderCancelled("2")])
    return store


@pytest.mark.asyncio
async def test_in_memory_projection(store):
    """Test in-memory projection."""
    projection = OrderCountProjection()

    store.append("order-1", [OrderCreated("1", 100.0)])

    await projection.apply(OrderCreated("1", 100.0))
    await projection.apply(OrderShipped("1"))

    state = projection.get_state()
    assert state["created"] == 1
    assert state["shipped"] == 1


@pytest.mark.asyncio
async def test_aggregate_projection(store):
    """Test aggregate projection."""
    projection = OrderDetailProjection()

    await projection.apply(OrderCreated("1", 100.0))
    await projection.apply(OrderShipped("1"))

    aggregate = projection.get_aggregate("order-1")
    assert aggregate["amount"] == 100.0
    assert aggregate["status"] == "shipped"


@pytest.mark.asyncio
async def test_catch_up_projection(populated_store):
    """Test catch-up projection."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection)

    state = projection.get_state()
    assert state["created"] == 2
    assert state["shipped"] == 1
    assert state["cancelled"] == 1


@pytest.mark.asyncio
async def test_projection_checkpoint(populated_store):
    """Test projection checkpoint tracking."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection)

    checkpoint = projection.get_checkpoint()
    assert checkpoint > 0


@pytest.mark.asyncio
async def test_catch_up_from_checkpoint(populated_store):
    """Test resuming catch-up from checkpoint."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection, batch_size=2)

    initial_version = projection.get_version()

    await catchup.catchup(projection, from_checkpoint=projection.get_checkpoint())

    assert projection.get_version() >= initial_version


@pytest.mark.asyncio
async def test_rebuild_projection(populated_store):
    """Test rebuilding projection."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection)

    first_version = projection.get_version()

    await catchup.rebuild(projection)

    assert projection.get_version() == first_version


@pytest.mark.asyncio
async def test_reset_projection():
    """Test resetting projection state."""
    projection = OrderCountProjection()

    await projection.apply(OrderCreated("1", 100.0))
    assert projection.get_version() == 1

    await projection.reset()

    assert projection.get_version() == 0
    assert projection.get_state()["created"] == 0


@pytest.mark.asyncio
async def test_projection_version_tracking(populated_store):
    """Test projection version tracking."""
    projection = OrderCountProjection()

    assert projection.get_version() == 0

    await projection.apply(OrderCreated("1", 100.0))

    assert projection.get_version() == 1


@pytest.mark.asyncio
async def test_projection_status(populated_store):
    """Test projection status changes."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    assert projection.status == ProjectionStatus.IDLE

    await catchup.catchup(projection)

    assert projection.status in (ProjectionStatus.IDLE, ProjectionStatus.LIVE)


@pytest.mark.asyncio
async def test_projection_manager_register(store):
    """Test registering projections."""
    manager = ProjectionManager(store)

    projection = OrderCountProjection()
    manager.register_projection(projection)

    assert manager.get_projection("order_count") is not None


@pytest.mark.asyncio
async def test_projection_manager_catchup_all(populated_store):
    """Test catching up all projections."""
    manager = ProjectionManager(populated_store)

    proj1 = OrderCountProjection()
    proj2 = OrderDetailProjection()

    manager.register_projection(proj1)
    manager.register_projection(proj2)

    await manager.catchup_all()

    assert proj1.get_version() > 0
    assert proj2.get_version() > 0


@pytest.mark.asyncio
async def test_projection_manager_specific_catchup(populated_store):
    """Test catching up specific projection."""
    manager = ProjectionManager(populated_store)

    projection = OrderCountProjection()
    manager.register_projection(projection)

    await manager.catchup_projection("order_count")

    assert projection.get_version() > 0


@pytest.mark.asyncio
async def test_projection_manager_rebuild(populated_store):
    """Test rebuilding via manager."""
    manager = ProjectionManager(populated_store)

    projection = OrderCountProjection()
    manager.register_projection(projection)

    await manager.rebuild_projection("order_count")

    assert projection.get_version() > 0


@pytest.mark.asyncio
async def test_projection_manager_unregister(store):
    """Test unregistering projection."""
    manager = ProjectionManager(store)

    projection = OrderCountProjection()
    manager.register_projection(projection)

    assert manager.get_projection("order_count") is not None

    manager.unregister_projection("order_count")

    assert manager.get_projection("order_count") is None


@pytest.mark.asyncio
async def test_aggregate_projection_multiple(populated_store):
    """Test aggregate projection with multiple aggregates."""
    projection = OrderDetailProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection)

    all_aggs = projection.get_all_aggregates()

    assert "order-1" in all_aggs
    assert "order-2" in all_aggs
    assert all_aggs["order-1"]["status"] == "shipped"
    assert all_aggs["order-2"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_projection_batch_processing(populated_store):
    """Test batch processing in catch-up."""
    projection = OrderCountProjection()
    catchup = CatchUpProjection(populated_store)

    await catchup.catchup(projection, batch_size=1)

    assert projection.get_version() > 0


@pytest.mark.asyncio
async def test_handle_event_broadcast(store):
    """Test broadcasting event to projections."""
    manager = ProjectionManager(store)

    proj1 = OrderCountProjection()
    proj2 = OrderDetailProjection()

    manager.register_projection(proj1)
    manager.register_projection(proj2)

    event = OrderCreated("1", 100.0)
    await manager.handle_event(event)

    assert proj1.get_version() == 1
    assert proj2.get_version() == 1
