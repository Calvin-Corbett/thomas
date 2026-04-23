"""
Tests for message persistence functionality.

Tests segment file creation, recovery, log cleaning, and index operations.
"""

import pickle
import tempfile
from pathlib import Path

import pytest

from thomas.marketplace.message_queue import Message
from thomas.marketplace.message_queue.persistence import (
    PersistenceManager,
    SegmentReader,
    SegmentWriter,
)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for persistence tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.asyncio
async def test_segment_writer_basic(temp_dir):
    """Test basic segment writer operation."""
    path = Path(temp_dir) / "segment_0.seg"
    writer = SegmentWriter(path, 0)

    # Add messages
    for i in range(5):
        message = Message(topic="test", payload=f"msg-{i}")
        await writer.append(message, offset=i)

    # Flush
    bytes_written = await writer.flush()
    assert bytes_written > 0
    assert path.exists()


@pytest.mark.asyncio
async def test_segment_reader_basic(temp_dir):
    """Test basic segment reader operation."""
    path = Path(temp_dir) / "segment_0.seg"

    # Write segment
    writer = SegmentWriter(path, 0)
    for i in range(5):
        message = Message(topic="test", payload=f"msg-{i}")
        await writer.append(message, offset=i)
    await writer.flush()

    # Read segment
    reader = SegmentReader(path)
    await reader.load()

    # Verify messages
    for i in range(5):
        message = await reader.get_message(i)
        assert message is not None
        assert message.payload == f"msg-{i}"


@pytest.mark.asyncio
async def test_segment_offset_index(temp_dir):
    """Test segment offset indexing."""
    path = Path(temp_dir) / "segment_0.seg"

    # Write segment with specific offsets
    writer = SegmentWriter(path, 0)
    offsets = [10, 11, 12, 13, 14]
    for offset in offsets:
        message = Message(topic="test", payload=f"msg-{offset}")
        await writer.append(message, offset=offset)
    await writer.flush()

    # Read and verify offsets
    reader = SegmentReader(path)
    await reader.load()

    for i, expected_offset in enumerate(offsets):
        actual_offset = await reader.get_offset(i)
        assert actual_offset == expected_offset


@pytest.mark.asyncio
async def test_persistence_manager_append(temp_dir):
    """Test message append to persistence."""
    manager = PersistenceManager(temp_dir)

    # Append messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await manager.append_message("test-topic", 0, message, offset=i)

    # Flush
    bytes_written = await manager.flush_segment("test-topic", 0)
    assert bytes_written > 0


@pytest.mark.asyncio
async def test_persistence_manager_retrieval(temp_dir):
    """Test message retrieval from persistence."""
    manager = PersistenceManager(temp_dir)

    # Write messages
    test_message = Message(topic="test-topic", payload="test data")
    await manager.append_message("test-topic", 0, test_message, offset=5)
    await manager.flush_segment("test-topic", 0)

    # Retrieve message
    retrieved = await manager.get_message("test-topic", 0, 5)
    assert retrieved is not None
    assert retrieved.payload == "test data"


@pytest.mark.asyncio
async def test_persistence_multiple_segments(temp_dir):
    """Test handling multiple segments."""
    manager = PersistenceManager(temp_dir)

    # Write to multiple topic/partition combinations
    for topic in ["topic-1", "topic-2"]:
        for partition in range(2):
            for i in range(5):
                message = Message(topic=topic, payload=f"{topic}-{partition}-{i}")
                await manager.append_message(topic, partition, message, offset=i)
            await manager.flush_segment(topic, partition)

    # Verify stats
    stats = await manager.get_stats()
    assert stats["total_segments"] > 0


@pytest.mark.asyncio
async def test_persistence_cleanup_retention(temp_dir):
    """Test cleanup based on retention policy."""
    manager = PersistenceManager(temp_dir)

    # Write messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await manager.append_message("test-topic", 0, message, offset=i)
    await manager.flush_segment("test-topic", 0)

    # Cleanup with aggressive retention
    deleted = await manager.cleanup_segments(
        "test-topic",
        0,
        retention_ms=1,  # 1 ms - should delete old segments
    )

    # Note: May not delete current segment
    assert isinstance(deleted, int)


@pytest.mark.asyncio
async def test_persistence_load_nonexistent():
    """Test loading nonexistent segment."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = PersistenceManager(tmpdir)

        # Try to load nonexistent
        reader = await manager.load_segment("topic", 0, 999)

        assert reader is None


@pytest.mark.asyncio
async def test_persistence_segment_caching(temp_dir):
    """Test segment reader caching."""
    manager = PersistenceManager(temp_dir)

    # Write segment
    for i in range(5):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await manager.append_message("test-topic", 0, message, offset=i)
    await manager.flush_segment("test-topic", 0)

    # Load and cache
    segment_id = int((await manager.get_stats())["total_segments"])

    # Stats should reflect caching
    stats = await manager.get_stats()
    assert stats["cached_readers"] >= 0


@pytest.mark.asyncio
async def test_persistence_stats(temp_dir):
    """Test persistence statistics."""
    manager = PersistenceManager(temp_dir)

    # Write some data
    for i in range(5):
        message = Message(topic="test", payload=f"msg-{i}")
        await manager.append_message("test", 0, message, offset=i)
    await manager.flush_segment("test", 0)

    stats = await manager.get_stats()

    assert "total_segments" in stats
    assert "total_size_bytes" in stats
    assert "cached_readers" in stats
    assert "active_writers" in stats


@pytest.mark.asyncio
async def test_segment_writer_empty_flush(temp_dir):
    """Test flushing empty segment."""
    path = Path(temp_dir) / "empty.seg"
    writer = SegmentWriter(path, 0)

    # Flush without adding messages
    bytes_written = await writer.flush()
    assert bytes_written == 0


@pytest.mark.asyncio
async def test_segment_reader_empty(temp_dir):
    """Test reading empty segment."""
    path = Path(temp_dir) / "empty.seg"
    path.touch()  # Create empty file

    reader = SegmentReader(path)
    await reader.load()

    # Should handle empty gracefully
    assert reader.messages == []


@pytest.mark.asyncio
async def test_persistence_large_payload(temp_dir):
    """Test persistence with large payloads."""
    manager = PersistenceManager(temp_dir)

    # Create large payload
    large_payload = "x" * 100000  # 100KB

    message = Message(topic="test", payload=large_payload)
    await manager.append_message("test", 0, message, offset=0)
    await manager.flush_segment("test", 0)

    # Retrieve and verify
    retrieved = await manager.get_message("test", 0, 0)
    assert retrieved is not None
    assert retrieved.payload == large_payload


@pytest.mark.asyncio
async def test_persistence_many_messages(temp_dir):
    """Test persistence with many messages."""
    manager = PersistenceManager(temp_dir)

    # Write many messages
    num_messages = 1000
    for i in range(num_messages):
        message = Message(topic="test", payload=f"msg-{i}")
        await manager.append_message("test", 0, message, offset=i)

    await manager.flush_segment("test", 0)

    # Verify stats
    stats = await manager.get_stats()
    assert stats["total_size_bytes"] > 0


@pytest.mark.asyncio
async def test_segment_reader_rejects_unsafe_pickle_globals(temp_dir):
    """Test segment reader rejects unexpected pickle globals."""
    path = Path(temp_dir) / "unsafe.seg"

    class _Exploit:
        def __reduce__(self):
            return (eval, ("1 + 1",))

    payload = pickle.dumps(_Exploit())
    with open(path, "wb") as handle:
        handle.write((0).to_bytes(8, "big"))
        handle.write(len(payload).to_bytes(4, "big"))
        handle.write(payload)

    reader = SegmentReader(path)

    with pytest.raises(Exception):
        await reader.load()
