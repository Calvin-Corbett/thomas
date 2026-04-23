"""
Tests for aggregate roots and repositories.

Tests aggregate state management, event application,
version tracking, snapshots, and rehydration.
"""

from typing import Any

import pytest

from . import (
    AggregateId,
    AggregateNotFoundException,
    AggregateRepository,
    AggregateRoot,
    ConcurrencyException,
    Event,
    EventStore,
    Metadata,
)


class DomainEvent(Event):
    """Base domain event."""

    pass


class Created(DomainEvent):
    """Aggregate created."""

    def __init__(self, name: str = ""):
        super().__init__()
        self.name = name


class NameChanged(DomainEvent):
    """Name changed."""

    def __init__(self, new_name: str = ""):
        super().__init__()
        self.new_name = new_name


class TestAggregate(AggregateRoot):
    """Test aggregate."""

    def __init__(self, aggregate_id: AggregateId):
        super().__init__(aggregate_id)
        self.name: str = ""
        self.created: bool = False

    def create(self, name: str) -> None:
        """Create aggregate."""
        self.raise_event(Created(name))

    def on_Created(self, event: Created) -> None:
        """Apply Created event."""
        self.name = event.name
        self.created = True

    def change_name(self, new_name: str) -> None:
        """Change name."""
        self.raise_event(NameChanged(new_name))

    def on_NameChanged(self, event: NameChanged) -> None:
        """Apply NameChanged event."""
        self.name = event.new_name

    def to_snapshot_state(self) -> dict[str, Any]:
        """Serialize to snapshot."""
        return {
            "version": self.version,
            "name": self.name,
            "created": self.created,
        }

    def restore_from_snapshot(self, state: dict[str, Any]) -> None:
        """Restore from snapshot."""
        self.version = state.get("version", 0)
        self.name = state.get("name", "")
        self.created = state.get("created", False)


class TestAggregateRoot:
    """Tests for AggregateRoot."""

    def test_initialize_aggregate(self):
        """Test aggregate initialization."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        assert agg.aggregate_id == agg_id
        assert agg.version == 0
        assert not agg.has_uncommitted_events()

    def test_raise_and_apply_event(self):
        """Test raising and applying events."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        agg.create("Alice")

        assert agg.name == "Alice"
        assert agg.created
        assert agg.version == 1
        assert agg.has_uncommitted_events()

    def test_get_uncommitted_events(self):
        """Test getting uncommitted events."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        agg.create("Alice")
        agg.change_name("Bob")

        events = agg.get_uncommitted_events()
        assert len(events) == 2
        assert isinstance(events[0], Created)
        assert isinstance(events[1], NameChanged)

    def test_clear_uncommitted_events(self):
        """Test clearing uncommitted events."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        agg.create("Alice")
        assert agg.has_uncommitted_events()

        agg.clear_uncommitted_events()
        assert not agg.has_uncommitted_events()
        assert agg.version == 1

    def test_get_version(self):
        """Test getting aggregate version."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        assert agg.get_version() == 0

        agg.create("Alice")
        assert agg.get_version() == 1

        agg.change_name("Bob")
        assert agg.get_version() == 2

    def test_multiple_events_increment_version(self):
        """Test version increments correctly."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        for i in range(5):
            agg.change_name(f"Name{i}")

        assert agg.version == 5

    def test_to_snapshot_state(self):
        """Test snapshot state serialization."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        agg.create("Alice")
        state = agg.to_snapshot_state()

        assert state["version"] == 1
        assert state["name"] == "Alice"
        assert state["created"]

    def test_restore_from_snapshot(self):
        """Test restoring from snapshot."""
        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        state = {
            "version": 5,
            "name": "Alice",
            "created": True,
        }
        agg.restore_from_snapshot(state)

        assert agg.version == 5
        assert agg.name == "Alice"
        assert agg.created

    def test_load_from_history(self):
        """Test loading from event history."""
        from . import EventEnvelope

        agg_id = AggregateId("123", "TestAggregate")
        metadata = Metadata()

        # Create events
        event1 = Created("Alice")
        event2 = NameChanged("Bob")

        envelope1 = EventEnvelope(
            event=event1,
            aggregate_id=agg_id,
            aggregate_version=1,
            global_position=0,
            metadata=metadata,
            event_type="Created",
        )

        envelope2 = EventEnvelope(
            event=event2,
            aggregate_id=agg_id,
            aggregate_version=2,
            global_position=1,
            metadata=metadata,
            event_type="NameChanged",
        )

        # Load aggregate from history
        agg = TestAggregate(agg_id)
        agg.load_from_history([envelope1, envelope2])

        assert agg.version == 2
        assert agg.name == "Bob"
        assert agg.created
        assert not agg.has_uncommitted_events()


class TestAggregateRepository:
    """Tests for AggregateRepository."""

    @pytest.mark.asyncio
    async def test_save_aggregate(self):
        """Test saving aggregate."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)
        agg.create("Alice")
        agg.change_name("Bob")

        metadata = Metadata(user_id="user1")
        await repo.save(agg, metadata)

        assert not agg.has_uncommitted_events()
        assert agg.version == 2

    @pytest.mark.asyncio
    async def test_save_empty_aggregate(self):
        """Test saving aggregate with no uncommitted events."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)

        metadata = Metadata()
        await repo.save(agg, metadata)  # Should not raise

    @pytest.mark.asyncio
    async def test_get_by_id(self):
        """Test loading aggregate."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")
        agg1 = TestAggregate(agg_id)
        agg1.create("Alice")
        agg1.change_name("Bob")

        metadata = Metadata(user_id="user1")
        await repo.save(agg1, metadata)

        # Load aggregate
        agg2 = await repo.get_by_id(agg_id, TestAggregate)

        assert agg2.aggregate_id == agg_id
        assert agg2.version == 2
        assert agg2.name == "Bob"
        assert agg2.created

    @pytest.mark.asyncio
    async def test_get_nonexistent_aggregate(self):
        """Test loading nonexistent aggregate."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("999", "TestAggregate")

        with pytest.raises(AggregateNotFoundException):
            await repo.get_by_id(agg_id, TestAggregate)

    @pytest.mark.asyncio
    async def test_exists(self):
        """Test checking aggregate existence."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id1 = AggregateId("123", "TestAggregate")
        agg_id2 = AggregateId("999", "TestAggregate")

        agg = TestAggregate(agg_id1)
        agg.create("Alice")

        metadata = Metadata()
        await repo.save(agg, metadata)

        assert await repo.exists(agg_id1)
        assert not await repo.exists(agg_id2)

    @pytest.mark.asyncio
    async def test_save_and_load_cycle(self):
        """Test complete save and load cycle."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")

        # Create and save
        agg1 = TestAggregate(agg_id)
        agg1.create("Alice")
        metadata = Metadata(user_id="user1")
        await repo.save(agg1, metadata)

        # Modify and save again
        agg1.change_name("Bob")
        await repo.save(agg1, metadata)

        # Load
        agg2 = await repo.get_by_id(agg_id, TestAggregate)

        assert agg2.version == 2
        assert agg2.name == "Bob"
        assert agg2.created

    @pytest.mark.asyncio
    async def test_optimistic_concurrency_error(self):
        """Test concurrency error handling."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")

        # Create aggregate
        agg = TestAggregate(agg_id)
        agg.create("Alice")
        metadata = Metadata()
        await repo.save(agg, metadata)

        # Manually modify version to simulate conflict
        agg.version = 10  # Wrong version

        with pytest.raises(ConcurrencyException):
            await repo.save(agg, metadata)

    @pytest.mark.asyncio
    async def test_snapshot_save(self):
        """Test saving snapshots."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")
        agg = TestAggregate(agg_id)
        agg.create("Alice")
        metadata = Metadata()
        await repo.save(agg, metadata)

        # Save snapshot
        await repo.save_snapshot(agg, frequency=1)

        # Verify snapshot exists
        snapshot = await event_store.get_snapshot(agg_id)
        assert snapshot is not None
        assert snapshot.aggregate_version == 1

    @pytest.mark.asyncio
    async def test_load_from_snapshot(self):
        """Test loading aggregate from snapshot."""
        event_store = EventStore()
        repo = AggregateRepository(event_store)

        agg_id = AggregateId("123", "TestAggregate")

        # Create and save
        agg1 = TestAggregate(agg_id)
        agg1.create("Alice")
        agg1.change_name("Bob")
        metadata = Metadata()
        await repo.save(agg1, metadata)

        # Save snapshot after version 2
        await repo.save_snapshot(agg1, frequency=1)

        # Add more events
        agg1.change_name("Charlie")
        await repo.save(agg1, metadata)

        # Load - should use snapshot and replay remaining events
        agg2 = await repo.get_by_id(agg_id, TestAggregate)

        assert agg2.version == 3
        assert agg2.name == "Charlie"
