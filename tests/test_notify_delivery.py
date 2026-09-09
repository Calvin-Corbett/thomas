"""
Tests for delivery queue and management.
"""

from thomas.notify._types import (
    ChannelType,
    DeliveryResult,
    DeliveryStatus,
    Notification,
    Priority,
    Recipient,
)
from thomas.notify.delivery import (
    DeliveryManager,
    DeliveryQueue,
    DeliveryRateMonitor,
)


class TestDeliveryQueue:
    """Tests for delivery queue."""

    def test_enqueue_and_dequeue(self) -> None:
        """Test enqueueing and dequeueing."""
        queue = DeliveryQueue()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        queue.enqueue(notification)

        assert queue.size() == 1

        dequeued = queue.dequeue()

        assert dequeued.notification_id == notification.notification_id
        assert queue.size() == 0

    def test_peek_without_removal(self) -> None:
        """Test peeking at queue."""
        queue = DeliveryQueue()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        queue.enqueue(notification)

        peeked = queue.peek()

        assert peeked.notification_id == notification.notification_id
        assert queue.size() == 1

    def test_priority_ordering(self) -> None:
        """Test notifications are ordered by priority."""
        queue = DeliveryQueue()

        recipient1 = Recipient(user_id="user1", email="user1@example.com")
        recipient2 = Recipient(user_id="user2", email="user2@example.com")

        low_priority = Notification(
            recipient=recipient1,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            priority=Priority.LOW,
        )

        high_priority = Notification(
            recipient=recipient2,
            template_id="t2",
            channel_type=ChannelType.EMAIL,
            priority=Priority.HIGH,
        )

        queue.enqueue(low_priority, priority=1.0)
        queue.enqueue(high_priority, priority=10.0)

        first = queue.dequeue()

        assert first.priority == Priority.HIGH


class TestDeliveryManager:
    """Tests for delivery manager."""

    def test_add_to_queue(self) -> None:
        """Test adding notification to queue."""
        manager = DeliveryManager()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification)

        assert manager.queue.size() == 1
        status = manager.get_delivery_status(notification.notification_id)
        assert status == DeliveryStatus.QUEUED

    def test_get_next_batch(self) -> None:
        """Test getting batch of notifications."""
        manager = DeliveryManager()

        for i in range(150):
            recipient = Recipient(
                user_id=f"user{i}",
                email=f"user{i}@example.com",
            )
            notification = Notification(
                recipient=recipient,
                template_id="t1",
                channel_type=ChannelType.EMAIL,
            )
            manager.add_to_queue(notification)

        batch = manager.get_next_batch(batch_size=100)

        assert len(batch) == 100

    def test_mark_delivered(self) -> None:
        """Test marking notification as delivered."""
        manager = DeliveryManager()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification)
        manager.mark_sent(notification.notification_id)
        manager.mark_delivered(notification.notification_id)

        status = manager.get_delivery_status(notification.notification_id)

        assert status == DeliveryStatus.DELIVERED

    def test_mark_failed_retries(self) -> None:
        """Test marking failed with retry."""
        manager = DeliveryManager()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification)

        should_retry = manager.mark_failed(
            notification.notification_id,
            error_message="Connection timeout",
        )

        assert should_retry is True

        status = manager.get_delivery_status(notification.notification_id)

        assert status == DeliveryStatus.DEFERRED

    def test_mark_failed_max_retries(self) -> None:
        """Test failing after max retries."""
        manager = DeliveryManager()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification)

        # Fail 3 times
        for _ in range(3):
            manager.mark_failed(
                notification.notification_id,
                error_message="Failure",
            )

        status = manager.get_delivery_status(notification.notification_id)

        assert status == DeliveryStatus.FAILED

    def test_mark_hard_bounce(self) -> None:
        """Test hard bounce handling."""
        manager = DeliveryManager()

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification)

        should_retry = manager.mark_failed(
            notification.notification_id,
            bounce_type="hard",
        )

        assert should_retry is False

        status = manager.get_delivery_status(notification.notification_id)

        assert status == DeliveryStatus.BOUNCED

    def test_get_delivery_metrics(self) -> None:
        """Test getting delivery metrics."""
        manager = DeliveryManager()

        recipient1 = Recipient(user_id="user1", email="user1@example.com")
        recipient2 = Recipient(user_id="user2", email="user2@example.com")

        notification1 = Notification(
            recipient=recipient1,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        notification2 = Notification(
            recipient=recipient2,
            template_id="t2",
            channel_type=ChannelType.EMAIL,
        )

        manager.add_to_queue(notification1)
        manager.add_to_queue(notification2)

        manager.mark_sent(notification1.notification_id)
        manager.mark_delivered(notification1.notification_id)

        metrics = manager.get_delivery_metrics()

        assert metrics["sending"] == 1
        assert metrics["delivered"] == 1


class TestDeliveryRateMonitor:
    """Tests for delivery rate monitoring."""

    def test_record_result(self) -> None:
        """Test recording delivery result."""
        monitor = DeliveryRateMonitor()

        result = DeliveryResult(
            notification_id="notif1",
            recipient_id="user1",
            channel_type=ChannelType.EMAIL,
            status=DeliveryStatus.DELIVERED,
        )

        monitor.record_result(result)

        assert len(monitor.delivery_results) == 1

    def test_get_delivery_rate(self) -> None:
        """Test delivery rate calculation."""
        monitor = DeliveryRateMonitor()

        for i in range(100):
            status = DeliveryStatus.DELIVERED if i < 90 else DeliveryStatus.FAILED

            result = DeliveryResult(
                notification_id=f"notif{i}",
                recipient_id="user1",
                channel_type=ChannelType.EMAIL,
                status=status,
            )

            monitor.record_result(result)

        rate = monitor.get_delivery_rate()

        assert rate == 0.9

    def test_get_channel_specific_rate(self) -> None:
        """Test channel-specific delivery rate."""
        monitor = DeliveryRateMonitor()

        # Email results
        for i in range(100):
            status = DeliveryStatus.DELIVERED if i < 90 else DeliveryStatus.FAILED

            result = DeliveryResult(
                notification_id=f"email{i}",
                recipient_id="user1",
                channel_type=ChannelType.EMAIL,
                status=status,
            )

            monitor.record_result(result)

        # SMS results
        for i in range(100):
            status = DeliveryStatus.DELIVERED if i < 80 else DeliveryStatus.FAILED

            result = DeliveryResult(
                notification_id=f"sms{i}",
                recipient_id="user1",
                channel_type=ChannelType.SMS,
                status=status,
            )

            monitor.record_result(result)

        email_rate = monitor.get_delivery_rate(ChannelType.EMAIL)
        sms_rate = monitor.get_delivery_rate(ChannelType.SMS)

        assert email_rate == 0.9
        assert sms_rate == 0.8

    def test_get_average_delivery_time(self) -> None:
        """Test average delivery time calculation."""
        monitor = DeliveryRateMonitor()

        for i in range(10):
            result = DeliveryResult(
                notification_id=f"notif{i}",
                recipient_id="user1",
                channel_type=ChannelType.EMAIL,
                status=DeliveryStatus.DELIVERED,
                delivery_time_ms=100.0,
            )

            monitor.record_result(result)

        avg_time = monitor.get_average_delivery_time()

        assert avg_time == 100.0
