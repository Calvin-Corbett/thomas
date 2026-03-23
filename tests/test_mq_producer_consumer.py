"""
Tests for producer and consumer functionality.

Tests end-to-end messaging, consumer groups, rebalancing,
acknowledgment modes, and offset management.
"""

import asyncio

import pytest

from thomas.marketplace.message_queue import (
    Broker,
    Consumer,
    ConsumerConfig,
    Message,
    Producer,
    ProducerConfig,
    TopicConfig,
)


@pytest.fixture
async def broker(loop):
    """Create a test broker."""
    broker = Broker()
    await broker.start()
    yield broker
    await broker.stop()


@pytest.fixture
async def topic_setup(broker, loop):
    """Setup a test topic."""
    config = TopicConfig(name="test-topic", num_partitions=3)
    await broker.create_topic(config)
    return broker


@pytest.mark.asyncio
async def test_producer_send(topic_setup):
    """Test basic producer send."""
    broker = topic_setup
    producer = Producer(broker)
    await producer.start()

    try:
        message = Message(topic="test-topic", payload="test data")
        msg_id = await producer.send(message)

        assert msg_id == message.id
        assert producer.metrics.messages_sent > 0

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_producer_batching(topic_setup):
    """Test producer message batching."""
    broker = topic_setup
    config = ProducerConfig(batch_size=5)
    producer = Producer(broker, config)
    await producer.start()

    try:
        # Send 10 messages (should create 2 batches)
        for i in range(10):
            message = Message(topic="test-topic", payload=f"msg-{i}")
            await producer.send(message)

        await producer.flush()

        assert producer.metrics.batches_sent >= 2

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_producer_flush(topic_setup):
    """Test producer flush."""
    broker = topic_setup
    config = ProducerConfig(batch_size=100)
    producer = Producer(broker, config)
    await producer.start()

    try:
        # Send less than batch size
        for i in range(5):
            message = Message(topic="test-topic", payload=f"msg-{i}")
            await producer.send(message)

        # Flush should send the batch
        await producer.flush()

        assert producer.metrics.messages_sent == 5

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_producer_with_callback(topic_setup):
    """Test producer send with callback."""
    broker = topic_setup
    producer = Producer(broker)
    await producer.start()

    callback_results = []

    def callback(msg_id, error):
        callback_results.append((msg_id, error))

    try:
        message = Message(topic="test-topic", payload="test data")
        await producer.send(message, callback=callback)

        await producer.flush()
        await asyncio.sleep(0.5)  # Wait for callback

        assert len(callback_results) > 0

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_consumer_poll(topic_setup):
    """Test consumer poll."""
    broker = topic_setup

    # Publish messages
    for i in range(5):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    # Consume messages
    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        results = await consumer.poll(timeout_ms=1000)

        # Should have messages from at least one partition
        total_messages = sum(len(msgs) for msgs in results.values())
        assert total_messages > 0

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_group_coordination(topic_setup):
    """Test consumer group coordination."""
    broker = topic_setup

    # Create 2 consumers in same group
    consumer1 = Consumer(broker, "test-group", ["test-topic"])
    consumer2 = Consumer(broker, "test-group", ["test-topic"])

    await consumer1.start()
    await consumer2.start()

    try:
        # Both consumers should get partition assignment
        assignment1 = await broker.get_partition_assignment(
            "test-group",
            consumer1.id,
            {"test-topic"},
        )

        assignment2 = await broker.get_partition_assignment(
            "test-group",
            consumer2.id,
            {"test-topic"},
        )

        # Verify assignments don't overlap
        partitions1 = set(assignment1.get("test-topic", []))
        partitions2 = set(assignment2.get("test-topic", []))

        assert partitions1.isdisjoint(partitions2) or len(partitions1) == 0

    finally:
        await consumer1.stop()
        await consumer2.stop()


@pytest.mark.asyncio
async def test_consumer_commit_sync(topic_setup):
    """Test synchronous offset commit."""
    broker = topic_setup

    # Publish messages
    for i in range(5):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        # Poll messages
        results = await consumer.poll()

        # Commit offsets
        await consumer.commit_sync()

        # Should have committed some offsets
        assert consumer.metrics.messages_committed > 0

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_auto_commit(topic_setup):
    """Test consumer auto-commit."""
    broker = topic_setup

    config = ConsumerConfig(enable_auto_commit=True)

    # Publish messages
    for i in range(5):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer = Consumer(broker, "test-group", ["test-topic"], config)
    await consumer.start()

    try:
        # Poll messages
        await consumer.poll()

        # Wait for auto-commit
        await asyncio.sleep(1)

        # Should have auto-committed
        assert consumer.metrics.messages_committed > 0

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_seek(topic_setup):
    """Test consumer seek."""
    broker = topic_setup

    # Publish messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        # Seek to offset 5
        await consumer.seek("test-topic", 0, 5)

        # Check position
        position = await consumer.get_position("test-topic", 0)
        assert position == 5

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_pause_resume(topic_setup):
    """Test consumer pause and resume."""
    broker = topic_setup

    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        # Pause partition
        await consumer.pause("test-topic", 0)
        assert ("test-topic", 0) in consumer.paused_partitions

        # Resume partition
        await consumer.resume("test-topic", 0)
        assert ("test-topic", 0) not in consumer.paused_partitions

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_producer_consumer_pipeline(topic_setup):
    """Test complete producer to consumer pipeline."""
    broker = topic_setup

    # Create producer and consumer
    producer = Producer(broker)
    consumer = Consumer(broker, "test-group", ["test-topic"])

    await producer.start()
    await consumer.start()

    try:
        # Produce messages
        test_messages = [f"message-{i}" for i in range(10)]
        for payload in test_messages:
            message = Message(topic="test-topic", payload=payload)
            await producer.send(message)

        await producer.flush()

        # Consume messages
        await asyncio.sleep(0.5)  # Give time for messages to be available
        results = await consumer.poll(timeout_ms=5000)

        consumed_messages = []
        for partition_messages in results.values():
            for msg in partition_messages:
                consumed_messages.append(msg.payload)

        # Verify we got the messages
        assert len(consumed_messages) > 0
        for payload in consumed_messages:
            assert payload in test_messages

    finally:
        await producer.stop()
        await consumer.stop()


@pytest.mark.asyncio
async def test_consumer_lag_tracking(topic_setup):
    """Test consumer lag tracking."""
    broker = topic_setup

    # Publish messages
    for i in range(100):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        # Poll some messages
        results = await consumer.poll()

        # Calculate lag
        total_consumed = sum(len(msgs) for msgs in results.values())
        assert total_consumed > 0

        # Update metrics with lag
        consumer.metrics.messages_consumed = total_consumed

    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_multiple_producers(topic_setup):
    """Test multiple producers to same topic."""
    broker = topic_setup

    producer1 = Producer(broker)
    producer2 = Producer(broker)

    await producer1.start()
    await producer2.start()

    try:
        # Each producer sends messages
        for i in range(5):
            msg1 = Message(topic="test-topic", payload=f"p1-{i}")
            msg2 = Message(topic="test-topic", payload=f"p2-{i}")

            await producer1.send(msg1)
            await producer2.send(msg2)

        await producer1.flush()
        await producer2.flush()

        assert producer1.metrics.messages_sent == 5
        assert producer2.metrics.messages_sent == 5

    finally:
        await producer1.stop()
        await producer2.stop()


@pytest.mark.asyncio
async def test_multiple_consumers(topic_setup):
    """Test multiple consumers from same topic."""
    broker = topic_setup

    # Publish messages
    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer1 = Consumer(broker, "test-group", ["test-topic"])
    consumer2 = Consumer(broker, "test-group", ["test-topic"])

    await consumer1.start()
    await consumer2.start()

    try:
        results1 = await consumer1.poll()
        results2 = await consumer2.poll()

        total_consumed = sum(len(msgs) for msgs in results1.values()) + sum(len(msgs) for msgs in results2.values())

        # Should have consumed all messages between 2 consumers
        assert total_consumed > 0

    finally:
        await consumer1.stop()
        await consumer2.stop()


@pytest.mark.asyncio
async def test_producer_metrics(topic_setup):
    """Test producer metrics collection."""
    broker = topic_setup
    producer = Producer(broker)
    await producer.start()

    try:
        for i in range(10):
            message = Message(topic="test-topic", payload=f"msg-{i}")
            await producer.send(message)

        await producer.flush()

        metrics = producer.get_metrics()
        assert metrics["messages_sent"] == 10
        assert metrics["batches_sent"] > 0

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_consumer_metrics(topic_setup):
    """Test consumer metrics collection."""
    broker = topic_setup

    for i in range(10):
        message = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(message)

    consumer = Consumer(broker, "test-group", ["test-topic"])
    await consumer.start()

    try:
        await consumer.poll()

        metrics = consumer.get_metrics()
        assert metrics["messages_consumed"] > 0
        assert metrics["tracked_offsets"] > 0

    finally:
        await consumer.stop()
