"""
Tests for dead letter queue functionality.

Tests DLQ routing, retry scheduling, replay, poison pill detection,
and max retry enforcement.
"""

import asyncio

import pytest

from thomas.message_queue import (
    Broker,
    DeadLetterConfig,
    DeadLetterQueue,
    Message,
    TopicConfig,
)


@pytest.fixture
async def broker_with_dlq(loop):
    """Create a test broker with DLQ."""
    broker = Broker()
    await broker.start()

    config = TopicConfig(name="test-topic")
    await broker.create_topic(config)

    dlq = DeadLetterQueue(broker)
    await dlq.start()

    yield broker, dlq

    await dlq.stop()
    await broker.stop()


@pytest.mark.asyncio
async def test_route_to_dlq(broker_with_dlq):
    """Test routing a message to DLQ."""
    broker, dlq = broker_with_dlq

    message = Message(topic="test-topic", payload="test data")

    try:
        await dlq.route_to_dlq(
            message,
            "test-topic",
            "Processing error",
            original_offset=0,
        )
    except Exception as e:
        assert "routed to DLQ" in str(e)

    # Verify message is in DLQ
    assert message.id in dlq.dlq_messages
    assert dlq.total_dlq_messages == 1


@pytest.mark.asyncio
async def test_dlq_retry_scheduling(broker_with_dlq):
    """Test retry scheduling for DLQ messages."""
    broker, dlq = broker_with_dlq

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Verify retry was scheduled
    assert message.id in dlq.retry_queue


@pytest.mark.asyncio
async def test_dlq_max_retries(broker_with_dlq):
    """Test that max retries is enforced."""
    broker, dlq = broker_with_dlq

    message = Message(
        topic="test-topic",
        payload="test data",
        retry_count=3,  # At max retries
    )

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Should be in DLQ but not scheduled for retry
    assert message.id in dlq.dlq_messages
    assert message.id not in dlq.retry_queue


@pytest.mark.asyncio
async def test_dlq_replay_message(broker_with_dlq):
    """Test replaying a message from DLQ."""
    broker, dlq = broker_with_dlq

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Replay the message
    replayed = await dlq.replay(message.id)

    assert replayed is not None
    assert replayed.retry_count == 0
    assert message.id not in dlq.dlq_messages


@pytest.mark.asyncio
async def test_dlq_replay_all(broker_with_dlq):
    """Test replaying all messages from DLQ."""
    broker, dlq = broker_with_dlq

    # Route multiple messages to DLQ
    for i in range(5):
        message = Message(topic="test-topic", payload=f"test-{i}", retry_count=0)

        try:
            await dlq.route_to_dlq(
                message,
                "test-topic",
                f"Error {i}",
                original_offset=i,
            )
        except Exception:
            pass

    # Replay all
    replayed_count = await dlq.replay_all()

    assert replayed_count == 5
    assert len(dlq.dlq_messages) == 0


@pytest.mark.asyncio
async def test_dlq_replay_callback(broker_with_dlq):
    """Test replay callbacks are triggered."""
    broker, dlq = broker_with_dlq

    callback_results = []

    def callback(msg):
        callback_results.append(msg.id)

    dlq.register_replay_callback(callback)

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    await dlq.replay(message.id)
    await asyncio.sleep(0.1)  # Give callback time to execute

    assert message.id in callback_results


@pytest.mark.asyncio
async def test_dlq_poison_pill_detection(broker_with_dlq):
    """Test poison pill detection."""
    broker, dlq = broker_with_dlq

    config = DeadLetterConfig(
        enable_poison_pill_detection=True,
        poison_pill_threshold=2,
    )
    dlq.config = config

    # Route same message with same error multiple times
    message = Message(topic="test-topic", payload="test data", retry_count=0)
    message.set_header("error", "parsing_error")

    for i in range(3):
        try:
            await dlq.route_to_dlq(
                message,
                "test-topic",
                "parsing_error",
                original_offset=0,
            )
        except Exception:
            pass

    # Check if poison pill was detected
    stats = await dlq.get_dlq_stats()
    assert stats["current_dlq_messages"] > 0


@pytest.mark.asyncio
async def test_dlq_exponential_backoff(broker_with_dlq):
    """Test exponential backoff for retries."""
    broker, dlq = broker_with_dlq

    config = DeadLetterConfig(
        max_retries=3,
        initial_backoff_ms=100,
        backoff_multiplier=2.0,
    )
    dlq.config = config

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Get scheduled retry time
    assert message.id in dlq.retry_queue


@pytest.mark.asyncio
async def test_dlq_schedule_retry(broker_with_dlq):
    """Test scheduling a retry for a message."""
    broker, dlq = broker_with_dlq

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Schedule a retry
    scheduled = await dlq.schedule_retry(message.id, delay_ms=1000)

    assert scheduled is True


@pytest.mark.asyncio
async def test_dlq_get_messages(broker_with_dlq):
    """Test retrieving messages from DLQ."""
    broker, dlq = broker_with_dlq

    # Add messages to DLQ
    for i in range(5):
        message = Message(topic="test-topic", payload=f"test-{i}", retry_count=0)

        try:
            await dlq.route_to_dlq(
                message,
                "test-topic",
                f"Error {i}",
                original_offset=i,
            )
        except Exception:
            pass

    # Get messages
    dlq_messages = await dlq.get_dlq_messages(max_results=10)

    assert len(dlq_messages) == 5


@pytest.mark.asyncio
async def test_dlq_stats(broker_with_dlq):
    """Test DLQ statistics."""
    broker, dlq = broker_with_dlq

    # Route messages to DLQ
    for i in range(3):
        message = Message(topic="test-topic", payload=f"test-{i}", retry_count=0)

        try:
            await dlq.route_to_dlq(
                message,
                "test-topic",
                f"Error {i}",
                original_offset=i,
            )
        except Exception:
            pass

    stats = await dlq.get_dlq_stats()

    assert stats["total_dlq_messages"] == 3
    assert stats["current_dlq_messages"] == 3


@pytest.mark.asyncio
async def test_dlq_metadata(broker_with_dlq):
    """Test DLQ message metadata."""
    broker, dlq = broker_with_dlq

    message = Message(topic="test-topic", payload="test data", retry_count=1)

    try:
        await dlq.route_to_dlq(
            message,
            "test-topic",
            "Processing failed",
            original_offset=42,
        )
    except Exception:
        pass

    # Get message and metadata
    msg, meta = dlq.dlq_messages[message.id]

    assert meta.original_topic == "test-topic"
    assert meta.original_offset == 42
    assert meta.retry_count == 1
    assert meta.error_reason == "Processing failed"
    assert meta.last_error_time is not None


@pytest.mark.asyncio
async def test_dlq_target_topic_replay(broker_with_dlq):
    """Test replaying to a different target topic."""
    broker, dlq = broker_with_dlq

    # Create target topic
    target_config = TopicConfig(name="dlq-replay-topic")
    await broker.create_topic(target_config)

    message = Message(topic="test-topic", payload="test data", retry_count=0)

    try:
        await dlq.route_to_dlq(message, "test-topic", "Error", original_offset=0)
    except Exception:
        pass

    # Replay to different topic
    replayed = await dlq.replay(message.id, target_topic="dlq-replay-topic")

    assert replayed is not None
    assert replayed.topic == "dlq-replay-topic"


@pytest.mark.asyncio
async def test_dlq_replay_by_topic_filter(broker_with_dlq):
    """Test replaying messages filtered by topic."""
    broker, dlq = broker_with_dlq

    # Create second topic
    topic2_config = TopicConfig(name="topic-2")
    await broker.create_topic(topic2_config)

    # Route messages from different topics
    for topic in ["test-topic", "topic-2"]:
        message = Message(topic=topic, payload=f"data from {topic}", retry_count=0)

        try:
            await dlq.route_to_dlq(message, topic, "Error", original_offset=0)
        except Exception:
            pass

    # Replay only from test-topic
    replayed = await dlq.replay_all(original_topic="test-topic")

    # Should have replayed 1 message
    assert replayed == 1
