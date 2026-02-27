"""
Tests for projections and projection manager.

Tests projection creation, event handling, catch-up, checkpoints,
and rebuild functionality.
"""

import asyncio
from typing import Any

import pytest

from . import (
    AggregateId,
    Event,
    EventEnvelope,
    EventStore,
    InMemoryProjection,
    Metadata,
    ProjectionException,
    ProjectionManager,
)


class TestEvent(Event):
    """Test event."""

    def __init__(self, data: str = ""):
        super().__init__()
        self.data = data


class AnotherEvent(Event):
    """Another event."""

    def __init__(self, value: int = 0):
        super().__init__()
        self.value = value


class CounterProjection(InMemoryProjection):
    """Projection that counts events."""

    def __init__(self):
        super().__init__("counter")
        self._data = {"count": 0}
        self.register_handler("TestEvent", self._on_test_event)

    async def _on_test_event(self, event: EventEnvelope) -> None:
        """Count test events."""
        self._data["count"] += 1

    async def get_count(self) -> int:
        """Get event count."""
        return self._data["count"]


class AggregatingProjection(InMemoryProjection):
    """Projection that aggregates event data."""

    def __init__(self):
        super().__init__("aggregator")
        self._data: dict[str, Any] = {}
        self.register_handler("TestEvent", self._on_test_event)

    async def _on_test_event(self, event: EventEnvelope) -> None:
        """Aggregate test event data."""
        key = event.aggregate_id.value
        if key not in self._data:
            self._data[key] = []
        self._data[key].append(event.event.data)

    async def get_data(self) -> dict[str, Any]:
        """Get aggregated data."""
        return self._data.copy()


class TestProjectionManager:
    """Tests for ProjectionManager."""

    @pytest.mark.asyncio
    async def test_register_projection(self):
        """Test registering a projection."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()

        await manager.register_projection(projection)

        retrieved = await manager.get_projection("counter")
        assert retrieved is projection

    @pytest.mark.asyncio
    async def test_handle_event_single_projection(self):
        """Test event handling by single projection."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        # Create event envelope
        agg_id = AggregateId("1", "Test")
        metadata = Metadata()
        envelope = EventEnvelope(
            event=TestEvent("test"),
            aggregate_id=agg_id,
            aggregate_version=1,
            global_position=0,
            metadata=metadata,
            event_type="TestEvent",
        )

        # Handle event
        await manager.handle_event(envelope)

        # Check projection state
        count = await projection.get_count()
        assert count == 1

    @pytest.mark.asyncio
    async def test_handle_event_multiple_projections(self):
        """Test event distribution to multiple projections."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)

        proj1 = CounterProjection()
        proj2 = AggregatingProjection()

        await manager.register_projection(proj1)
        await manager.register_projection(proj2)

        agg_id = AggregateId("1", "Test")
        metadata = Metadata()
        envelope = EventEnvelope(
            event=TestEvent("data1"),
            aggregate_id=agg_id,
            aggregate_version=1,
            global_position=0,
            metadata=metadata,
            event_type="TestEvent",
        )

        await manager.handle_event(envelope)

        count = await proj1.get_count()
        data = await proj2.get_data()

        assert count == 1
        assert "1" in data
        assert data["1"] == ["data1"]

    @pytest.mark.asyncio
    async def test_catch_up_projection(self):
        """Test catching up projection from event store."""
        event_store = EventStore()
        agg_id = AggregateId("1", "Test")
        metadata = Metadata()

        # Add events to store
        await event_store.append(
            agg_id,
            [TestEvent("first"), TestEvent("second"), TestEvent("third")],
            expected_version=0,
            metadata=metadata,
        )

        # Create manager with projection
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        # Catch up
        await manager.catch_up("counter")

        # Check projection has all events
        count = await projection.get_count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_catch_up_all_projections(self):
        """Test catching up all projections."""
        event_store = EventStore()
        agg_id = AggregateId("1", "Test")
        metadata = Metadata()

        await event_store.append(
            agg_id,
            [TestEvent("event1"), TestEvent("event2")],
            expected_version=0,
            metadata=metadata,
        )

        manager = ProjectionManager(event_store)
        proj1 = CounterProjection()
        proj2 = AggregatingProjection()

        await manager.register_projection(proj1)
        await manager.register_projection(proj2)

        await manager.catch_up_all()

        count = await proj1.get_count()
        data = await proj2.get_data()

        assert count == 2
        assert "1" in data

    @pytest.mark.asyncio
    async def test_rebuild_projection(self):
        """Test rebuilding projection."""
        event_store = EventStore()
        agg_id = AggregateId("1", "Test")
        metadata = Metadata()

        # Add events
        await event_store.append(
            agg_id,
            [TestEvent("first"), TestEvent("second")],
            expected_version=0,
            metadata=metadata,
        )

        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        # Catch up
        await manager.catch_up("counter")
        assert await projection.get_count() == 2

        # Reset and rebuild
        await manager.rebuild_projection("counter")
        assert await projection.get_count() == 2

    @pytest.mark.asyncio
    async def test_checkpoint_tracking(self):
        """Test checkpoint tracking."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        checkpoint = await manager.get_checkpoint("counter")
        assert checkpoint is not None
        assert checkpoint.last_processed_position == -1

        # Update checkpoint
        await manager.update_checkpoint("counter", 5)

        checkpoint = await manager.get_checkpoint("counter")
        assert checkpoint.last_processed_position == 5

    @pytest.mark.asyncio
    async def test_projection_ready_state(self):
        """Test projection ready state."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        # Initially not ready
        is_ready = await manager.is_projection_ready("counter")
        assert not is_ready

        # Mark as ready
        await projection.set_ready()
        is_ready = await manager.is_projection_ready("counter")
        assert is_ready

    @pytest.mark.asyncio
    async def test_wait_for_projection_ready(self):
        """Test waiting for projection to be ready."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        async def mark_ready():
            await asyncio.sleep(0.1)
            await projection.set_ready()

        asyncio.create_task(mark_ready())

        # This should complete
        await manager.wait_for_projection("counter", timeout_seconds=1.0)

    @pytest.mark.asyncio
    async def test_wait_for_projection_timeout(self):
        """Test timeout waiting for projection."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        with pytest.raises(asyncio.TimeoutError):
            await manager.wait_for_projection("counter", timeout_seconds=0.1)

    @pytest.mark.asyncio
    async def test_get_all_projections(self):
        """Test getting all projections."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)

        proj1 = CounterProjection()
        proj2 = AggregatingProjection()

        await manager.register_projection(proj1)
        await manager.register_projection(proj2)

        all_projs = await manager.projections()
        assert len(all_projs) == 2
        assert "counter" in all_projs
        assert "aggregator" in all_projs

    @pytest.mark.asyncio
    async def test_projection_error_handling(self):
        """Test error handling in projections."""
        event_store = EventStore()
        manager = ProjectionManager(event_store)

        class FailingProjection(InMemoryProjection):
            async def __init__(self):
                super().__init__("failing")
                self.register_handler("TestEvent", self._on_test)

            async def _on_test(self, event: EventEnvelope) -> None:
                raise ValueError("Projection error")

        failing = FailingProjection()
        await manager.register_projection(failing)

        agg_id = AggregateId("1", "Test")
        metadata = Metadata()
        envelope = EventEnvelope(
            event=TestEvent("test"),
            aggregate_id=agg_id,
            aggregate_version=1,
            global_position=0,
            metadata=metadata,
            event_type="TestEvent",
        )

        with pytest.raises(ProjectionException):
            await manager.handle_event(envelope)

    @pytest.mark.asyncio
    async def test_incremental_catch_up(self):
        """Test incremental catch-up from checkpoint."""
        event_store = EventStore()
        agg_id = AggregateId("1", "Test")
        metadata = Metadata()

        # Add initial events
        await event_store.append(
            agg_id,
            [TestEvent("first"), TestEvent("second")],
            expected_version=0,
            metadata=metadata,
        )

        manager = ProjectionManager(event_store)
        projection = CounterProjection()
        await manager.register_projection(projection)

        # Catch up
        await manager.catch_up("counter")
        assert await projection.get_count() == 2

        # Add more events
        await event_store.append(
            agg_id,
            [TestEvent("third")],
            expected_version=2,
            metadata=metadata,
        )

        # Catch up again (should only get new event)
        await manager.catch_up("counter")
        assert await projection.get_count() == 3
