"""
Tests for event store functionality.

Tests append, read, concurrency control, and snapshots.
"""

import pytest

from . import Event, EventStore, StreamSnapshot


class OrderCreated(Event):
    """Test event."""

    def __init__(self, order_id: str, amount: float):
        super().__init__("OrderCreated", f"order-{order_id}")
        self.order_id = order_id
        self.amount = amount


class OrderShipped(Event):
    """Test event."""

    def __init__(self, order_id: str, tracking: str):
        super().__init__("OrderShipped", f"order-{order_id}")
        self.order_id = order_id
        self.tracking = tracking


@pytest.fixture
def store():
    """Create an event store."""
    return EventStore()


def test_append_events(store):
    """Test appending events to a stream."""
    stream = "order-123"
    events = [
        OrderCreated("123", 100.0),
        OrderShipped("123", "TRACK123"),
    ]

    version, sequence = store.append(stream, events)

    assert version == 2
    assert sequence == 2


def test_read_stream_forward(store):
    """Test reading events forward."""
    stream = "order-123"
    events = [OrderCreated("123", 100.0), OrderShipped("123", "TRACK123")]

    store.append(stream, events)

    result = store.read_stream_forward(stream)

    assert len(result) == 2
    assert result[0].event.type == "OrderCreated"
    assert result[1].event.type == "OrderShipped"


def test_read_stream_backward(store):
    """Test reading events backward."""
    stream = "order-123"
    events = [OrderCreated("123", 100.0), OrderShipped("123", "TRACK123")]

    store.append(stream, events)

    result = store.read_stream_backward(stream)

    assert len(result) == 2
    assert result[0].event.type == "OrderShipped"
    assert result[1].event.type == "OrderCreated"


def test_read_by_type(store):
    """Test reading events by type."""
    store.append("order-1", [OrderCreated("1", 100.0)])
    store.append("order-2", [OrderCreated("2", 200.0)])
    store.append("order-1", [OrderShipped("1", "TRACK1")])

    result = store.read_by_type("OrderCreated")

    assert len(result) == 2
    assert all(e.event.type == "OrderCreated" for e in result)


def test_optimistic_concurrency(store):
    """Test optimistic concurrency check."""
    stream = "order-123"
    events1 = [OrderCreated("123", 100.0)]

    version1, _ = store.append(stream, events1)

    assert version1 == 1

    events2 = [OrderShipped("123", "TRACK")]

    from . import ConcurrencyError

    with pytest.raises(ConcurrencyError):
        store.append(stream, events2, expected_version=0)


def test_stream_metadata(store):
    """Test stream metadata."""
    stream = "order-123"
    events = [OrderCreated("123", 100.0), OrderShipped("123", "TRACK")]

    store.append(stream, events)

    metadata = store.get_metadata(stream)

    assert metadata.stream_name == stream
    assert metadata.version == 2
    assert metadata.event_count == 2


def test_update_metadata(store):
    """Test updating stream metadata."""
    stream = "order-123"
    store.append(stream, [OrderCreated("123", 100.0)])

    store.update_metadata(stream, {"custom_key": "custom_value"})

    metadata = store.get_metadata(stream)
    assert metadata.custom_metadata["custom_key"] == "custom_value"


def test_save_snapshot(store):
    """Test saving snapshots."""
    stream = "order-123"
    store.append(stream, [OrderCreated("123", 100.0)])

    snapshot = StreamSnapshot(
        stream_name=stream,
        version=1,
        state={"order_id": "123", "amount": 100.0},
    )

    store.save_snapshot(snapshot)

    retrieved = store.get_snapshot(stream)

    assert retrieved is not None
    assert retrieved.version == 1
    assert retrieved.state["order_id"] == "123"


def test_delete_snapshot(store):
    """Test deleting snapshots."""
    stream = "order-123"
    snapshot = StreamSnapshot(stream, 1, {})

    store.save_snapshot(snapshot)
    assert store.get_snapshot(stream) is not None

    store.delete_snapshot(stream)
    assert store.get_snapshot(stream) is None


def test_read_all_forward(store):
    """Test reading all events globally."""
    store.append("order-1", [OrderCreated("1", 100.0)])
    store.append("order-2", [OrderCreated("2", 200.0)])
    store.append("order-1", [OrderShipped("1", "TRACK1")])

    result = store.read_all_forward()

    assert len(result) == 3
    assert all(hasattr(e, "sequence_number") for e in result)


def test_stream_version(store):
    """Test getting stream version."""
    stream = "order-123"
    assert store.get_stream_version(stream) == 0

    store.append(stream, [OrderCreated("123", 100.0)])
    assert store.get_stream_version(stream) == 1


def test_global_position(store):
    """Test global event sequence."""
    pos1 = store.get_global_position()
    store.append("stream1", [OrderCreated("1", 100.0)])
    pos2 = store.get_global_position()
    store.append("stream2", [OrderCreated("2", 200.0)])
    pos3 = store.get_global_position()

    assert pos1 == 0
    assert pos2 == 1
    assert pos3 == 2


def test_multiple_streams(store):
    """Test working with multiple independent streams."""
    store.append("order-1", [OrderCreated("1", 100.0)])
    store.append("order-2", [OrderCreated("2", 200.0)])

    result1 = store.read_stream_forward("order-1")
    result2 = store.read_stream_forward("order-2")

    assert len(result1) == 1
    assert len(result2) == 1
    assert result1[0].event.order_id == "1"
    assert result2[0].event.order_id == "2"


def test_stream_exists(store):
    """Test checking stream existence."""
    assert not store.stream_exists("order-123")

    store.append("order-123", [OrderCreated("123", 100.0)])

    assert store.stream_exists("order-123")


def test_get_all_streams(store):
    """Test getting all stream names."""
    store.append("order-1", [OrderCreated("1", 100.0)])
    store.append("order-2", [OrderCreated("2", 200.0)])

    streams = store.get_all_streams()

    assert len(streams) == 2
    assert "order-1" in streams
    assert "order-2" in streams


def test_read_from_version(store):
    """Test reading from specific version."""
    stream = "order-123"
    store.append(
        stream,
        [
            OrderCreated("123", 100.0),
            OrderShipped("123", "TRACK1"),
            OrderShipped("123", "TRACK2"),
        ],
    )

    result = store.read_stream_forward(stream, from_version=2)

    assert len(result) == 2


def test_read_with_count_limit(store):
    """Test reading with count limit."""
    stream = "order-123"
    store.append(
        stream,
        [OrderCreated("123", 100.0), OrderShipped("123", "T1"), OrderShipped("123", "T2")],
    )

    result = store.read_stream_forward(stream, count=2)

    assert len(result) == 2


def test_clear_store(store):
    """Test clearing store."""
    store.append("order-1", [OrderCreated("1", 100.0)])

    assert store.stream_exists("order-1")

    store.clear()

    assert not store.stream_exists("order-1")
    assert store.get_global_position() == 0


def test_empty_stream_error(store):
    """Test error on empty append."""
    from . import EventStoreError

    with pytest.raises(EventStoreError):
        store.append("order-123", [])


def test_concurrent_appends(store):
    """Test appending with expected versions."""
    stream = "order-123"

    v1, _ = store.append(stream, [OrderCreated("123", 100.0)])
    assert v1 == 1

    v2, _ = store.append(stream, [OrderShipped("123", "TRACK")], expected_version=1)
    assert v2 == 2


def test_envelope_metadata(store):
    """Test event envelope metadata."""
    stream = "order-123"
    events = [OrderCreated("123", 100.0)]

    store.append(stream, events)

    result = store.read_stream_forward(stream)

    assert len(result) == 1
    envelope = result[0]
    assert envelope.stream_name == stream
    assert envelope.stream_version == 1
    assert envelope.sequence_number == 1


def test_snapshot_with_large_state(store):
    """Test snapshot with large state."""
    stream = "order-123"
    large_state = {f"key_{i}": f"value_{i}" for i in range(1000)}

    snapshot = StreamSnapshot(stream, 1, large_state)
    store.save_snapshot(snapshot)

    retrieved = store.get_snapshot(stream)
    assert len(retrieved.state) == 1000


def test_read_backward_with_limit(store):
    """Test reading backward with limit."""
    stream = "order-123"
    store.append(
        stream,
        [
            OrderCreated("123", 100.0),
            OrderShipped("123", "T1"),
            OrderShipped("123", "T2"),
        ],
    )

    result = store.read_stream_backward(stream, count=2)

    assert len(result) == 2
    assert result[0].event.type == "OrderShipped"
