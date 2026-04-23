"""
Tests for event store and event handling.

Tests event persistence, concurrency control, snapshots,
global position tracking, and event retrieval.
"""

import asyncio

import pytest

from . import (
    AggregateId,
    ConcurrencyException,
    Event,
    EventStore,
    Metadata,
)


class TestEvent(Event):
    """Test event."""

    def __init__(self, name: str = "test"):
        super().__init__()
        self.name = name


class AnotherEvent(Event):
    """Another test event."""

    def __init__(self, value: int = 42):
        super().__init__()
        self.value = value


class TestEventStore:
    """Tests for EventStore."""

    @pytest.mark.asyncio
    async def test_append_events(self):
        """Test appending events."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        events = [TestEvent("first"), TestEvent("second")]
        metadata = Metadata(user_id="user1")

        await store.append(agg_id, events, expected_version=0, metadata=metadata)

        retrieved = await store.get_events(agg_id)
        assert len(retrieved) == 2
        assert retrieved[0].aggregate_version == 1
        assert retrieved[1].aggregate_version == 2

    @pytest.mark.asyncio
    async def test_optimistic_concurrency(self):
        """Test optimistic concurrency control."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        metadata = Metadata()

        # First append
        await store.append(agg_id, [TestEvent()], expected_version=0, metadata=metadata)

        # Concurrent append with wrong expected version
        with pytest.raises(ConcurrencyException):
            await store.append(agg_id, [TestEvent()], expected_version=0, metadata=metadata)

    @pytest.mark.asyncio
    async def test_get_events_from_version(self):
        """Test retrieving events from specific version."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        metadata = Metadata()

        # Append multiple events
        await store.append(
            agg_id,
            [TestEvent("v1"), TestEvent("v2"), TestEvent("v3")],
            expected_version=0,
            metadata=metadata,
        )

        # Get events from version 2
        events = await store.get_events(agg_id, from_version=1)
        assert len(events) == 2
        assert events[0].aggregate_version == 2
        assert events[1].aggregate_version == 3

    @pytest.mark.asyncio
    async def test_get_current_version(self):
        """Test getting current aggregate version."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        metadata = Metadata()

        # Non-existent aggregate
        version = await store.get_current_version(agg_id)
        assert version == 0

        # After appending events
        await store.append(agg_id, [TestEvent(), TestEvent()], expected_version=0, metadata=metadata)
        version = await store.get_current_version(agg_id)
        assert version == 2

    @pytest.mark.asyncio
    async def test_get_events_by_type(self):
        """Test retrieving events by type."""
        store = EventStore()
        agg_id1 = AggregateId("1", "Agg")
        agg_id2 = AggregateId("2", "Agg")
        metadata = Metadata()

        # Append mixed events
        await store.append(agg_id1, [TestEvent(), AnotherEvent()], expected_version=0, metadata=metadata)
        await store.append(agg_id2, [AnotherEvent(), TestEvent()], expected_version=0, metadata=metadata)

        # Get TestEvents
        test_events = await store.get_events_by_type("TestEvent")
        assert len(test_events) == 2

        # Get AnotherEvents
        another_events = await store.get_events_by_type("AnotherEvent")
        assert len(another_events) == 2

    @pytest.mark.asyncio
    async def test_get_events_from_position(self):
        """Test retrieving events from global position."""
        store = EventStore()
        agg_id1 = AggregateId("1", "Agg")
        agg_id2 = AggregateId("2", "Agg")
        metadata = Metadata()

        # Append to first aggregate
        await store.append(agg_id1, [TestEvent(), TestEvent()], expected_version=0, metadata=metadata)

        # Append to second aggregate
        await store.append(agg_id2, [TestEvent(), TestEvent()], expected_version=0, metadata=metadata)

        # Get from position 2 (third event)
        events = await store.get_events_from_position(from_position=2)
        assert len(events) >= 2

    @pytest.mark.asyncio
    async def test_get_events_with_limit(self):
        """Test retrieving events with limit."""
        store = EventStore()
        agg_id = AggregateId("1", "Agg")
        metadata = Metadata()

        await store.append(
            agg_id,
            [TestEvent() for _ in range(10)],
            expected_version=0,
            metadata=metadata,
        )

        events = await store.get_events_from_position(from_position=0, limit=3)
        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_global_position_tracking(self):
        """Test global position increments correctly."""
        store = EventStore()
        agg_id1 = AggregateId("1", "Agg")
        agg_id2 = AggregateId("2", "Agg")
        metadata = Metadata()

        initial_pos = await store.get_global_position()
        assert initial_pos == 0

        await store.append(agg_id1, [TestEvent()], expected_version=0, metadata=metadata)
        pos1 = await store.get_global_position()
        assert pos1 == 1

        await store.append(agg_id2, [TestEvent(), TestEvent()], expected_version=0, metadata=metadata)
        pos2 = await store.get_global_position()
        assert pos2 == 3

    @pytest.mark.asyncio
    async def test_save_and_get_snapshot(self):
        """Test snapshot persistence."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        state = {"name": "John", "balance": 100}

        await store.save_snapshot(agg_id, version=5, state=state)

        snapshot = await store.get_snapshot(agg_id)
        assert snapshot is not None
        assert snapshot.aggregate_version == 5
        assert snapshot.state == state

    @pytest.mark.asyncio
    async def test_snapshot_updates_to_latest(self):
        """Test getting latest snapshot."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")

        await store.save_snapshot(agg_id, version=5, state={"v": 5})
        await store.save_snapshot(agg_id, version=10, state={"v": 10})

        snapshot = await store.get_snapshot(agg_id)
        assert snapshot.aggregate_version == 10
        assert snapshot.state["v"] == 10

    @pytest.mark.asyncio
    async def test_subscribers_notified(self):
        """Test subscribers are notified of new events."""
        store = EventStore()
        agg_id = AggregateId("123", "TestAggregate")
        metadata = Metadata()

        events_received = []

        async def subscriber(events):
            events_received.extend(events)

        await store.subscribe(subscriber)

        await store.append(
            agg_id,
            [TestEvent("first"), TestEvent("second")],
            expected_version=0,
            metadata=metadata,
        )

        await asyncio.sleep(0.1)
        assert len(events_received) == 2

    @pytest.mark.asyncio
    async def test_event_count(self):
        """Test getting total event count."""
        store = EventStore()
        agg_id1 = AggregateId("1", "Agg")
        agg_id2 = AggregateId("2", "Agg")
        metadata = Metadata()

        assert await store.event_count() == 0

        await store.append(agg_id1, [TestEvent()], expected_version=0, metadata=metadata)
        assert await store.event_count() == 1

        await store.append(agg_id2, [TestEvent(), TestEvent()], expected_version=0, metadata=metadata)
        assert await store.event_count() == 3

    @pytest.mark.asyncio
    async def test_clear_store(self):
        """Test clearing store."""
        store = EventStore()
        agg_id = AggregateId("1", "Agg")
        metadata = Metadata()

        await store.append(agg_id, [TestEvent()], expected_version=0, metadata=metadata)
        assert await store.event_count() == 1

        await store.clear()
        assert await store.event_count() == 0

    @pytest.mark.asyncio
    async def test_multiple_aggregates(self):
        """Test handling multiple aggregates."""
        store = EventStore()
        agg_id1 = AggregateId("1", "TypeA")
        agg_id2 = AggregateId("2", "TypeB")
        metadata = Metadata()

        await store.append(agg_id1, [TestEvent("a1")], expected_version=0, metadata=metadata)
        await store.append(agg_id2, [TestEvent("b1")], expected_version=0, metadata=metadata)

        events1 = await store.get_events(agg_id1)
        events2 = await store.get_events(agg_id2)

        assert len(events1) == 1
        assert len(events2) == 1
        assert events1[0].event.name == "a1"
        assert events2[0].event.name == "b1"
