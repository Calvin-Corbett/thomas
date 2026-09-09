"""Tests for webhook delivery functionality."""

from thomas.marketplace.webhooks._types import (
    Delivery,
    DeliveryStatus,
    Endpoint,
    EventPayload,
    Subscription,
    WebhookEvent,
)
from thomas.marketplace.webhooks.delivery import DeliveryEnvelope, DeliveryManager, DeliveryQueue


class TestDeliveryQueue:
    """Test delivery queue priority management."""

    def test_enqueue_single_delivery(self):
        """Test enqueueing a single delivery."""
        queue = DeliveryQueue()
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        queue.enqueue(delivery, endpoint, subscription, event)

        assert queue.size() == 1

    def test_dequeue_fifo(self):
        """Test that dequeue returns highest priority."""
        queue = DeliveryQueue()
        delivery1 = Delivery(id="del_1")
        delivery2 = Delivery(id="del_2")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event1 = WebhookEvent(id="evt_1", type="order.created")
        event2 = WebhookEvent(id="evt_2", type="order.created")

        queue.enqueue(delivery1, endpoint, subscription, event1)
        queue.enqueue(delivery2, endpoint, subscription, event2)

        dequeued = queue.dequeue()
        assert dequeued is not None
        assert queue.size() == 1

    def test_peek_without_removing(self):
        """Test peek doesn't remove item from queue."""
        queue = DeliveryQueue()
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        queue.enqueue(delivery, endpoint, subscription, event)

        peeked = queue.peek()
        assert peeked is not None
        assert queue.size() == 1

    def test_dequeue_empty_queue(self):
        """Test dequeue on empty queue."""
        queue = DeliveryQueue()
        assert queue.dequeue() is None

    def test_queue_size(self):
        """Test getting queue size."""
        queue = DeliveryQueue()
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        assert queue.size() == 0
        queue.enqueue(delivery, endpoint, subscription, event)
        assert queue.size() == 1


class TestDeliveryEnvelope:
    """Test webhook envelope creation."""

    def test_create_envelope(self):
        """Test creating a standard webhook envelope."""
        event = WebhookEvent(
            id="evt_1",
            type="order.created",
            payload=EventPayload(data={"order_id": "123"}),
            source="test",
        )

        envelope = DeliveryEnvelope.create(event)

        assert envelope["id"] == event.id
        assert envelope["type"] == event.type
        assert envelope["source"] == event.source
        assert envelope["data"] == {"order_id": "123"}

    def test_create_envelope_with_signature(self):
        """Test envelope with signature."""
        event = WebhookEvent(
            id="evt_1",
            type="order.created",
            payload=EventPayload(data={}),
        )
        signature = "sig_123456"

        envelope = DeliveryEnvelope.create(event, signature=signature)

        assert envelope["signature"] == signature


class TestDeliveryManager:
    """Test delivery management."""

    def test_schedule_delivery(self):
        """Test scheduling a delivery."""
        manager = DeliveryManager()
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        manager.schedule_delivery(delivery, endpoint, subscription, event)

        assert delivery.status == DeliveryStatus.PENDING
        assert manager.get_queue_stats()["pending"] == 1

    def test_process_delivery_success(self):
        """Test processing a successful delivery."""

        def mock_http_handler(url, payload, headers, timeout):
            return 200, '{"status": "ok"}', 50

        manager = DeliveryManager(http_handler=mock_http_handler)
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        attempt = manager.process_delivery(delivery, endpoint, subscription, event)

        assert attempt.status == DeliveryStatus.DELIVERED
        assert attempt.status_code == 200
        assert attempt.latency_ms == 50

    def test_process_delivery_failure_retryable(self):
        """Test processing delivery with retryable failure."""

        def mock_http_handler(url, payload, headers, timeout):
            return 503, "Service Unavailable", 100

        manager = DeliveryManager(http_handler=mock_http_handler)
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        attempt = manager.process_delivery(delivery, endpoint, subscription, event)

        assert attempt.status == DeliveryStatus.FAILED
        assert attempt.status_code == 503

    def test_process_delivery_failure_permanent(self):
        """Test processing delivery with permanent failure."""

        def mock_http_handler(url, payload, headers, timeout):
            return 400, "Bad Request", 50

        manager = DeliveryManager(http_handler=mock_http_handler)
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        attempt = manager.process_delivery(delivery, endpoint, subscription, event)

        assert attempt.status == DeliveryStatus.FAILED
        assert delivery.status == DeliveryStatus.EXHAUSTED
        assert delivery.permanent_failure_reason is not None

    def test_process_delivery_idempotency(self):
        """Test idempotent delivery processing."""
        call_count = 0

        def mock_http_handler(url, payload, headers, timeout):
            nonlocal call_count
            call_count += 1
            return 200, '{"status": "ok"}', 50

        manager = DeliveryManager(http_handler=mock_http_handler)
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        attempt1 = manager.process_delivery(delivery, endpoint, subscription, event)
        attempt2 = manager.process_delivery(delivery, endpoint, subscription, event)

        assert call_count == 1
        assert attempt1 is attempt2

    def test_process_batch_delivery(self):
        """Test batch delivery to same endpoint."""

        def mock_http_handler(url, payload, headers, timeout):
            return 200, '{"status": "ok"}', 75

        manager = DeliveryManager(http_handler=mock_http_handler)
        deliveries = [Delivery(id=f"del_{i}") for i in range(3)]
        endpoint = Endpoint(url="https://example.com/webhooks")

        attempts = manager.process_batch(deliveries, endpoint)

        assert len(attempts) == 3
        assert all(a.status == DeliveryStatus.DELIVERED for a in attempts)

    def test_get_queue_stats(self):
        """Test getting queue statistics."""
        manager = DeliveryManager()
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        manager.schedule_delivery(delivery, endpoint, subscription, event)

        stats = manager.get_queue_stats()
        assert stats["pending"] == 1
        assert stats["in_flight"] == 0


class TestPrepareHeaders:
    """Test HTTP header preparation."""

    def test_prepare_headers_with_custom_headers(self):
        """Test header preparation with custom headers."""
        manager = DeliveryManager()
        endpoint = Endpoint(
            url="https://example.com/webhooks",
            headers={"X-Custom": "value1"},
        )
        subscription = Subscription(
            id="sub_1",
            custom_headers={"X-Subscription": "value2"},
        )

        headers = manager._prepare_headers(endpoint, subscription, 1)

        assert headers["Content-Type"] == "application/json"
        assert headers["X-Custom"] == "value1"
        assert headers["X-Subscription"] == "value2"
        assert headers["X-Webhook-Attempt"] == "1"


class TestDeliveryWithException:
    """Test delivery with exception handling."""

    def test_process_delivery_with_exception(self):
        """Test delivery when HTTP handler raises exception."""

        def mock_http_handler(url, payload, headers, timeout):
            raise Exception("Connection refused")

        manager = DeliveryManager(http_handler=mock_http_handler)
        delivery = Delivery(id="del_1")
        endpoint = Endpoint(url="https://example.com/webhooks")
        subscription = Subscription(id="sub_1")
        event = WebhookEvent(id="evt_1", type="order.created")

        attempt = manager.process_delivery(delivery, endpoint, subscription, event)

        assert attempt.status == DeliveryStatus.FAILED
        assert "Connection refused" in attempt.error_message
