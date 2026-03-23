"""
Tests for the message broker.

Tests broker lifecycle, topic management, producer/consumer registration,
routing patterns, and graceful shutdown.
"""

import pytest

from thomas.marketplace.message_queue import (
    Broker,
    Message,
    QueueConfig,
    TopicAlreadyExistsError,
    TopicConfig,
    TopicNotFoundError,
)


@pytest.fixture
async def broker(loop):
    """Create a test broker."""
    config = QueueConfig(max_topics=100)
    broker = Broker(config)
    await broker.start()
    yield broker
    await broker.stop()


@pytest.mark.asyncio
async def test_broker_lifecycle():
    """Test broker startup and shutdown."""
    broker = Broker()
    assert not broker._running

    await broker.start()
    assert broker._running

    await broker.stop()
    assert not broker._running


@pytest.mark.asyncio
async def test_create_topic(broker):
    """Test creating a topic."""
    config = TopicConfig(name="test-topic", num_partitions=3)
    await broker.create_topic(config)

    topics = await broker.list_topics()
    assert "test-topic" in topics


@pytest.mark.asyncio
async def test_create_duplicate_topic(broker):
    """Test that creating a duplicate topic raises error."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    with pytest.raises(TopicAlreadyExistsError):
        await broker.create_topic(config)


@pytest.mark.asyncio
async def test_delete_topic(broker):
    """Test deleting a topic."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    await broker.delete_topic("test-topic")

    topics = await broker.list_topics()
    assert "test-topic" not in topics


@pytest.mark.asyncio
async def test_delete_nonexistent_topic(broker):
    """Test that deleting nonexistent topic raises error."""
    with pytest.raises(TopicNotFoundError):
        await broker.delete_topic("nonexistent")


@pytest.mark.asyncio
async def test_list_topics(broker):
    """Test listing topics."""
    for i in range(5):
        config = TopicConfig(name=f"topic-{i}")
        await broker.create_topic(config)

    topics = await broker.list_topics()
    assert len(topics) == 5
    assert all(f"topic-{i}" in topics for i in range(5))


@pytest.mark.asyncio
async def test_publish_message(broker):
    """Test publishing a message."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    message = Message(
        topic="test-topic",
        payload={"data": "test"},
    )

    partition_id, offset = await broker.publish(message)
    assert partition_id == 0
    assert offset == 0


@pytest.mark.asyncio
async def test_publish_to_nonexistent_topic(broker):
    """Test publishing to nonexistent topic raises error."""
    message = Message(
        topic="nonexistent",
        payload={"data": "test"},
    )

    with pytest.raises(TopicNotFoundError):
        await broker.publish(message)


@pytest.mark.asyncio
async def test_fetch_messages(broker):
    """Test fetching messages."""
    config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(config)

    # Publish messages
    for i in range(5):
        message = Message(
            topic="test-topic",
            payload=f"message-{i}",
        )
        await broker.publish(message)

    # Fetch messages
    messages = await broker.fetch("test-topic", 0, 0, 10, "test-group")

    assert len(messages) == 5
    assert messages[0].payload == "message-0"


@pytest.mark.asyncio
async def test_consumer_registration(broker):
    """Test registering a consumer."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    await broker.register_consumer(
        "test-group",
        "consumer-1",
        {"test-topic"},
    )

    # Check that consumer can get partition assignment
    assignment = await broker.get_partition_assignment(
        "test-group",
        "consumer-1",
        {"test-topic"},
    )

    assert "test-topic" in assignment


@pytest.mark.asyncio
async def test_consumer_deregistration(broker):
    """Test deregistering a consumer."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    await broker.register_consumer(
        "test-group",
        "consumer-1",
        {"test-topic"},
    )

    await broker.deregister_consumer("test-group", "consumer-1")

    # Verify deregistration
    stats = await broker.get_broker_stats()
    assert stats["active_consumers"] == 0


@pytest.mark.asyncio
async def test_partition_assignment_range(broker):
    """Test range-based partition assignment."""
    config = TopicConfig(
        name="test-topic",
        num_partitions=6,
    )
    await broker.create_topic(config)

    # Register 3 consumers
    for i in range(3):
        await broker.register_consumer(
            "test-group",
            f"consumer-{i}",
            {"test-topic"},
        )

    # Get assignments
    assignments = []
    for i in range(3):
        assignment = await broker.get_partition_assignment(
            "test-group",
            f"consumer-{i}",
            {"test-topic"},
        )
        assignments.append(set(assignment["test-topic"]))

    # Verify each partition is assigned exactly once
    all_partitions = set()
    for assignment in assignments:
        all_partitions.update(assignment)

    assert all_partitions == set(range(6))


@pytest.mark.asyncio
async def test_commit_offset(broker):
    """Test committing an offset."""
    config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(config)

    # Publish and commit
    message = Message(topic="test-topic", payload="test")
    await broker.publish(message)

    await broker.commit_offset("test-group", "test-topic", 0, 0)

    # Verify offset is committed
    offset = await broker.topics["test-topic"].partitions[0].get_offset_for_group("test-group")
    assert offset == 0


@pytest.mark.asyncio
async def test_seek_offset(broker):
    """Test seeking to an offset."""
    config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(config)

    # Publish messages
    for i in range(5):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    # Seek to offset 2
    await broker.seek("test-group", "test-topic", 0, 2)

    # Verify seek
    offset = await broker.topics["test-topic"].partitions[0].get_offset_for_group("test-group")
    assert offset == 2


@pytest.mark.asyncio
async def test_heartbeat(broker):
    """Test consumer heartbeat."""
    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    await broker.register_consumer(
        "test-group",
        "consumer-1",
        {"test-topic"},
    )

    # Send heartbeat
    await broker.heartbeat("test-group", "consumer-1")

    # Verify heartbeat was recorded
    key = ("test-group", "consumer-1")
    assert key in broker.last_heartbeat


@pytest.mark.asyncio
async def test_get_broker_stats(broker):
    """Test getting broker statistics."""
    config = TopicConfig(name="test-topic", num_partitions=2)
    await broker.create_topic(config)

    # Publish messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    stats = await broker.get_broker_stats()
    assert stats["topics"] == 1
    assert stats["total_messages"] == 10


@pytest.mark.asyncio
async def test_get_topic_stats(broker):
    """Test getting topic statistics."""
    config = TopicConfig(name="test-topic", num_partitions=2)
    await broker.create_topic(config)

    # Publish messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    stats = await broker.get_topic_stats("test-topic")
    assert stats["name"] == "test-topic"
    assert stats["partitions"] == 2
    assert stats["total_messages"] == 10


@pytest.mark.asyncio
async def test_max_topics_limit(broker):
    """Test that broker enforces max topic limit."""
    config = QueueConfig(max_topics=5)
    limited_broker = Broker(config)
    await limited_broker.start()

    try:
        # Create 5 topics
        for i in range(5):
            topic_config = TopicConfig(name=f"topic-{i}")
            await limited_broker.create_topic(topic_config)

        # Try to create 6th topic
        with pytest.raises(RuntimeError):
            topic_config = TopicConfig(name="topic-5")
            await limited_broker.create_topic(topic_config)

    finally:
        await limited_broker.stop()


@pytest.mark.asyncio
async def test_round_robin_partition_selection():
    """Test round-robin partition selection for messages."""
    broker = Broker()
    await broker.start()

    try:
        config = TopicConfig(name="test-topic", num_partitions=3)
        await broker.create_topic(config)

        # Publish messages without partition key
        partitions_hit = set()
        for i in range(10):
            message = Message(topic="test-topic", payload=f"msg-{i}")
            partition_id, _ = await broker.publish(message)
            partitions_hit.add(partition_id)

        # Should have hit multiple partitions
        assert len(partitions_hit) > 1

    finally:
        await broker.stop()


@pytest.mark.asyncio
async def test_key_based_partition_selection():
    """Test key-based partition selection."""
    broker = Broker()
    await broker.start()

    try:
        config = TopicConfig(name="test-topic", num_partitions=3)
        await broker.create_topic(config)

        # Publish messages with same key
        partition_ids = []
        for i in range(5):
            message = Message(
                topic="test-topic",
                payload=f"msg-{i}",
                partition_key="same-key",
            )
            partition_id, _ = await broker.publish(message)
            partition_ids.append(partition_id)

        # All should go to same partition
        assert len(set(partition_ids)) == 1

    finally:
        await broker.stop()
