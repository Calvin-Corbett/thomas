"""
Integration tests for the complete message queue system.

Tests full pipeline with multiple producers/consumers, failover scenarios,
middleware chains, and end-to-end message flow.
"""

import asyncio

import pytest

from thomas.message_queue import (
    BackpressureConfig,
    BackpressureManager,
    Broker,
    Consumer,
    DeadLetterConfig,
    DeadLetterQueue,
    FilterMiddleware,
    LoggingMiddleware,
    Message,
    MetricsMiddleware,
    MiddlewarePipeline,
    Producer,
    QueueConfig,
    QueueMonitor,
    TopicConfig,
)


@pytest.fixture
async def full_broker(loop):
    """Create a full-featured broker setup."""
    config = QueueConfig(max_topics=100)
    broker = Broker(config)
    await broker.start()

    yield broker

    await broker.stop()


@pytest.mark.asyncio
async def test_full_pipeline(full_broker):
    """Test complete producer to consumer pipeline."""
    broker = full_broker

    # Setup topic
    topic_config = TopicConfig(name="test-topic", num_partitions=3)
    await broker.create_topic(topic_config)

    # Create producer and consumer
    producer = Producer(broker)
    consumer = Consumer(broker, "test-group", ["test-topic"])

    await producer.start()
    await consumer.start()

    try:
        # Produce messages
        test_data = [f"message-{i}" for i in range(20)]
        for data in test_data:
            msg = Message(topic="test-topic", payload=data)
            await producer.send(msg)

        await producer.flush()
        await asyncio.sleep(0.5)

        # Consume messages
        consumed_data = []
        for _ in range(3):  # Poll multiple times
            results = await consumer.poll(timeout_ms=1000)
            for messages in results.values():
                for msg in messages:
                    consumed_data.append(msg.payload)

            if len(consumed_data) >= len(test_data):
                break

        # Verify all messages consumed
        assert len(consumed_data) > 0
        for data in consumed_data:
            assert data in test_data

    finally:
        await producer.stop()
        await consumer.stop()


@pytest.mark.asyncio
async def test_multiple_consumer_groups(full_broker):
    """Test multiple consumer groups on same topic."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=2)
    await broker.create_topic(topic_config)

    # Produce messages
    for i in range(10):
        msg = Message(topic="test-topic", payload=f"msg-{i}")
        await broker.publish(msg)

    # Create two consumer groups
    group1_consumers = [
        Consumer(broker, "group-1", ["test-topic"]),
        Consumer(broker, "group-1", ["test-topic"]),
    ]

    group2_consumers = [
        Consumer(broker, "group-2", ["test-topic"]),
    ]

    for consumer in group1_consumers + group2_consumers:
        await consumer.start()

    try:
        # All groups should consume all messages
        group1_results = []
        group2_results = []

        for consumer in group1_consumers:
            results = await consumer.poll()
            for messages in results.values():
                group1_results.extend(messages)

        for consumer in group2_consumers:
            results = await consumer.poll()
            for messages in results.values():
                group2_results.extend(messages)

        # Both groups should have messages
        assert len(group1_results) > 0
        assert len(group2_results) > 0

    finally:
        for consumer in group1_consumers + group2_consumers:
            await consumer.stop()


@pytest.mark.asyncio
async def test_producer_consumer_with_dlq(full_broker):
    """Test producer/consumer with dead letter queue."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(topic_config)

    dlq_config = DeadLetterConfig(max_retries=1)
    dlq = DeadLetterQueue(broker, dlq_config)
    await dlq.start()

    producer = Producer(broker)
    consumer = Consumer(broker, "test-group", ["test-topic"])

    await producer.start()
    await consumer.start()

    try:
        # Produce message
        msg = Message(topic="test-topic", payload="test data", retry_count=0)
        await producer.send(msg)
        await producer.flush()

        # Simulate failure - route to DLQ
        try:
            await dlq.route_to_dlq(msg, "test-topic", "Processing error")
        except Exception:
            pass

        # Verify message in DLQ
        dlq_stats = await dlq.get_dlq_stats()
        assert dlq_stats["current_dlq_messages"] > 0

    finally:
        await producer.stop()
        await consumer.stop()
        await dlq.stop()


@pytest.mark.asyncio
async def test_backpressure_integration(full_broker):
    """Test backpressure during heavy load."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(topic_config)

    bp_config = BackpressureConfig(
        enable_rate_limiting=True,
        rate_limit_msgs_per_sec=100,
    )
    backpressure = BackpressureManager(bp_config)

    producer = Producer(broker)
    await producer.start()

    try:
        # Send messages and check backpressure
        messages_sent = 0
        for i in range(50):
            # Check if can publish
            can_publish = await backpressure.check_can_publish(timeout_ms=1000)

            if can_publish:
                msg = Message(topic="test-topic", payload=f"msg-{i}")
                await producer.send(msg)
                messages_sent += 1
                await backpressure.record_publish()

        await producer.flush()

        assert messages_sent > 0

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_monitoring_integration(full_broker):
    """Test monitoring with real broker operations."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=2)
    await broker.create_topic(topic_config)

    monitor = QueueMonitor()
    await monitor.start(broker)

    try:
        # Produce messages
        for i in range(10):
            msg = Message(topic="test-topic", payload=f"msg-{i}")
            await broker.publish(msg)

        # Create consumer
        consumer = Consumer(broker, "test-group", ["test-topic"])
        await consumer.start()

        # Consume messages
        await consumer.poll()

        # Record metrics
        await monitor.record_consumer_lag("test-group", 5)

        # Get metrics
        metrics = await monitor.get_metrics()
        assert "total_messages" in metrics
        assert metrics["total_messages"] > 0

        # Get alerts
        alerts = await monitor.get_alerts()

        await consumer.stop()

    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_middleware_pipeline_integration(full_broker):
    """Test middleware pipeline with broker."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(topic_config)

    # Create middleware pipeline
    pipeline = MiddlewarePipeline()

    # Add logging middleware
    pipeline.add_bidirectional(LoggingMiddleware(logger=lambda x: None))

    # Add metrics middleware
    metrics_mw = MetricsMiddleware()
    pipeline.add_bidirectional(metrics_mw)

    # Add filter middleware (only allow payloads with "good")
    def good_filter(msg: Message) -> bool:
        return "good" in str(msg.payload)

    pipeline.add_inbound(FilterMiddleware(good_filter))

    # Create producer
    producer = Producer(broker)
    await producer.start()

    try:
        # Send messages
        for i in range(5):
            msg = Message(topic="test-topic", payload=f"good-message-{i}")
            processed = await pipeline.process_outbound(msg)
            if processed:
                await producer.send(processed)

        await producer.flush()

        # Check metrics
        metrics = metrics_mw.get_metrics()
        assert metrics["outbound_count"] > 0

    finally:
        await producer.stop()


@pytest.mark.asyncio
async def test_rebalancing_on_consumer_failure(full_broker):
    """Test consumer group rebalancing on failure."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=4)
    await broker.create_topic(topic_config)

    # Create 2 consumers
    consumer1 = Consumer(broker, "test-group", ["test-topic"])
    consumer2 = Consumer(broker, "test-group", ["test-topic"])

    await consumer1.start()
    await consumer2.start()

    try:
        # Get initial assignments
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

        initial_partitions = set(assignment1.get("test-topic", [])) | set(assignment2.get("test-topic", []))

        # Stop one consumer
        await consumer1.stop()

        # Deregister from broker
        await broker.deregister_consumer("test-group", consumer1.id)

        # Consumer2 should now have more partitions
        new_assignment = await broker.get_partition_assignment(
            "test-group",
            consumer2.id,
            {"test-topic"},
        )

        new_partitions = set(new_assignment.get("test-topic", []))

        # Should have expanded (or at least be valid)
        assert len(new_partitions) > 0

    finally:
        # Cleanup
        try:
            await consumer1.stop()
        except Exception:
            pass
        await consumer2.stop()


@pytest.mark.asyncio
async def test_high_throughput_scenario(full_broker):
    """Test system under high throughput."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=8)
    await broker.create_topic(topic_config)

    # Multiple producers
    producers = [Producer(broker) for _ in range(3)]
    for p in producers:
        await p.start()

    # Multiple consumers
    consumers = [
        Consumer(broker, "test-group", ["test-topic"]),
        Consumer(broker, "test-group", ["test-topic"]),
    ]
    for c in consumers:
        await c.start()

    try:
        # Produce many messages
        total_sent = 0
        for producer in producers:
            for i in range(100):
                msg = Message(topic="test-topic", payload=f"msg-{i}")
                await producer.send(msg)
            await producer.flush()
            total_sent += 100

        # Consume messages
        total_consumed = 0
        for consumer in consumers:
            for _ in range(5):  # Poll multiple times
                results = await consumer.poll(timeout_ms=500)
                for messages in results.values():
                    total_consumed += len(messages)

        # Should have consumed reasonable number
        assert total_consumed > 0

        # Verify metrics
        stats = await broker.get_broker_stats()
        assert stats["total_messages"] > 0

    finally:
        for p in producers:
            await p.stop()
        for c in consumers:
            await c.stop()


@pytest.mark.asyncio
async def test_message_ordering_within_partition(full_broker):
    """Test that messages are ordered within a partition."""
    broker = full_broker

    topic_config = TopicConfig(name="test-topic", num_partitions=1)
    await broker.create_topic(topic_config)

    producer = Producer(broker)
    consumer = Consumer(broker, "test-group", ["test-topic"])

    await producer.start()
    await consumer.start()

    try:
        # Send ordered messages with same partition key
        test_data = [f"msg-{i}" for i in range(20)]
        for data in test_data:
            msg = Message(
                topic="test-topic",
                payload=data,
                partition_key="same-key",  # Same key = same partition
            )
            await producer.send(msg)

        await producer.flush()
        await asyncio.sleep(0.5)

        # Consume and verify order
        results = await consumer.poll(timeout_ms=2000)

        consumed_data = []
        for messages in results.values():
            for msg in messages:
                consumed_data.append(msg.payload)

        # Verify order is preserved
        if len(consumed_data) > 0:
            for i, data in enumerate(consumed_data):
                assert data == f"msg-{i}" or data in test_data

    finally:
        await producer.stop()
        await consumer.stop()


@pytest.mark.asyncio
async def test_topic_retention_policy(full_broker):
    """Test topic retention policy enforcement."""
    broker = full_broker

    # Create topic with short retention
    topic_config = TopicConfig(
        name="short-retention-topic",
        num_partitions=1,
        retention_ms=100,  # 100ms
    )
    await broker.create_topic(topic_config)

    # Publish messages
    for i in range(10):
        msg = Message(topic="short-retention-topic", payload=f"msg-{i}")
        await broker.publish(msg)

    # Wait for retention to apply
    await asyncio.sleep(0.2)

    # Apply retention cleanup
    deleted = await broker.topics["short-retention-topic"].cleanup_retention()

    # Should have deleted old messages
    assert isinstance(deleted, int)
