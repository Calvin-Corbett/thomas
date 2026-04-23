"""
Delivery queue management with retry logic and status tracking.
Handles batch sending and delivery receipt processing.
"""

import heapq
from datetime import datetime, timedelta

from thomas.notify._types import (
    ChannelType,
    DeliveryResult,
    DeliveryStatus,
    Notification,
)


class DeliveryQueue:
    """Priority queue for notification delivery."""

    def __init__(self) -> None:
        """Initialize delivery queue."""
        self.queue: list[tuple[float, str, Notification]] = []
        self.processed: dict[str, DeliveryResult] = {}
        self.queue_counter = 0

    def enqueue(
        self,
        notification: Notification,
        priority: float = 0.0,
    ) -> None:
        """Add notification to queue.

        Args:
            notification: Notification to queue
            priority: Priority score (higher = sooner)
        """
        # Use negative priority for max-heap behavior
        heap_priority = (-priority, self.queue_counter)
        self.queue_counter += 1

        heapq.heappush(
            self.queue,
            (heap_priority, notification.notification_id, notification),
        )

    def dequeue(self) -> Notification | None:
        """Remove next notification from queue.

        Returns:
            Next notification or None if empty
        """
        while self.queue:
            _, _, notification = heapq.heappop(self.queue)
            return notification

        return None

    def peek(self) -> Notification | None:
        """View next notification without removing.

        Returns:
            Next notification or None if empty
        """
        if not self.queue:
            return None

        _, _, notification = self.queue[0]
        return notification

    def size(self) -> int:
        """Get queue size.

        Returns:
            Number of queued notifications
        """
        return len(self.queue)

    def mark_processed(self, result: DeliveryResult) -> None:
        """Mark notification as processed.

        Args:
            result: Delivery result
        """
        self.processed[result.notification_id] = result


class DeliveryManager:
    """Manages notification delivery with retry logic."""

    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_DELAY_SECONDS = 60
    DEFAULT_BATCH_SIZE = 100

    def __init__(self) -> None:
        """Initialize delivery manager."""
        self.queue = DeliveryQueue()
        self.retry_attempts: dict[str, int] = {}
        self.next_retry_time: dict[str, datetime] = {}
        self.bounce_list: set = set()
        self.delivery_status: dict[str, DeliveryStatus] = {}

    def add_to_queue(self, notification: Notification) -> None:
        """Add notification to delivery queue.

        Args:
            notification: Notification to queue
        """
        priority_value = self._calculate_priority(notification)
        self.queue.enqueue(notification, priority_value)
        self.delivery_status[notification.notification_id] = DeliveryStatus.QUEUED
        self.retry_attempts[notification.notification_id] = 0

    def get_next_batch(self, batch_size: int = DEFAULT_BATCH_SIZE) -> list[Notification]:
        """Get next batch of notifications for delivery.

        Args:
            batch_size: Maximum batch size

        Returns:
            Batch of ready notifications
        """
        batch = []
        current_time = datetime.utcnow()

        while len(batch) < batch_size:
            notification = self.queue.peek()

            if not notification:
                break

            # Check if ready to retry
            notif_id = notification.notification_id
            if notif_id in self.next_retry_time:
                if current_time < self.next_retry_time[notif_id]:
                    break

            self.queue.dequeue()
            batch.append(notification)

        return batch

    def mark_sent(self, notification_id: str) -> None:
        """Mark notification as sent.

        Args:
            notification_id: Notification identifier
        """
        self.delivery_status[notification_id] = DeliveryStatus.SENDING

    def mark_delivered(self, notification_id: str, delivery_time_ms: float = 0.0) -> None:
        """Mark notification as delivered.

        Args:
            notification_id: Notification identifier
            delivery_time_ms: Delivery time in milliseconds
        """
        self.delivery_status[notification_id] = DeliveryStatus.DELIVERED

        if notification_id in self.retry_attempts:
            del self.retry_attempts[notification_id]

        if notification_id in self.next_retry_time:
            del self.next_retry_time[notification_id]

    def mark_failed(
        self,
        notification_id: str,
        error_message: str = "",
        bounce_type: str | None = None,
    ) -> bool:
        """Mark notification as failed with retry logic.

        Args:
            notification_id: Notification identifier
            error_message: Error message
            bounce_type: "hard" or "soft" bounce

        Returns:
            True if should retry, False if max retries exceeded
        """
        if notification_id not in self.retry_attempts:
            self.retry_attempts[notification_id] = 0

        current_attempts = self.retry_attempts[notification_id]
        current_attempts += 1
        self.retry_attempts[notification_id] = current_attempts

        # Handle bounce
        if bounce_type == "hard":
            self.delivery_status[notification_id] = DeliveryStatus.BOUNCED
            self.bounce_list.add(notification_id)
            return False

        if bounce_type == "soft":
            # Schedule retry for soft bounces
            pass

        if current_attempts >= self.DEFAULT_MAX_RETRIES:
            self.delivery_status[notification_id] = DeliveryStatus.FAILED
            return False

        # Schedule retry with exponential backoff
        delay_seconds = self.DEFAULT_RETRY_DELAY_SECONDS * (2 ** (current_attempts - 1))
        self.next_retry_time[notification_id] = datetime.utcnow() + timedelta(seconds=delay_seconds)

        self.delivery_status[notification_id] = DeliveryStatus.DEFERRED

        return True

    def get_delivery_status(self, notification_id: str) -> DeliveryStatus:
        """Get delivery status for notification.

        Args:
            notification_id: Notification identifier

        Returns:
            Delivery status
        """
        return self.delivery_status.get(notification_id, DeliveryStatus.QUEUED)

    def get_delivery_metrics(self) -> dict[str, int]:
        """Get delivery metrics.

        Returns:
            Status counts
        """
        metrics: dict[str, int] = {}

        for status in DeliveryStatus:
            metrics[status.value] = 0

        for status in self.delivery_status.values():
            metrics[status.value] += 1

        # Backward compatibility: older dashboards treated queued work as "sending".
        metrics[DeliveryStatus.SENDING.value] += metrics[DeliveryStatus.QUEUED.value]

        return metrics

    def is_in_bounce_list(self, notification_id: str) -> bool:
        """Check if notification is in bounce list.

        Args:
            notification_id: Notification identifier

        Returns:
            True if in bounce list
        """
        return notification_id in self.bounce_list

    def handle_unsubscribe(self, notification_id: str) -> None:
        """Handle unsubscribe for notification.

        Args:
            notification_id: Notification identifier
        """
        self.delivery_status[notification_id] = DeliveryStatus.UNSUBSCRIBED

    def _calculate_priority(self, notification: Notification) -> float:
        """Calculate delivery priority for notification.

        Args:
            notification: Notification to prioritize

        Returns:
            Priority score
        """
        priority_weights = {
            "URGENT": 4,
            "HIGH": 3,
            "NORMAL": 2,
            "LOW": 1,
        }

        base_priority = priority_weights.get(notification.priority.value.upper(), 1)

        # Adjust for age
        age_seconds = (datetime.utcnow() - notification.created_at).total_seconds()
        age_factor = min(age_seconds / 3600, 4)  # Max 4 hours worth

        return base_priority + age_factor


class DeliveryRateMonitor:
    """Monitors delivery rates and metrics."""

    def __init__(self) -> None:
        """Initialize rate monitor."""
        self.delivery_results: list[DeliveryResult] = []
        self.channel_stats: dict[ChannelType, dict[str, int]] = {}

    def record_result(self, result: DeliveryResult) -> None:
        """Record delivery result.

        Args:
            result: Delivery result
        """
        self.delivery_results.append(result)

        channel = result.channel_type

        if channel not in self.channel_stats:
            self.channel_stats[channel] = {
                "sent": 0,
                "delivered": 0,
                "failed": 0,
            }

        self.channel_stats[channel]["sent"] += 1

        if result.status == DeliveryStatus.DELIVERED:
            self.channel_stats[channel]["delivered"] += 1
        elif result.status == DeliveryStatus.FAILED:
            self.channel_stats[channel]["failed"] += 1

    def get_delivery_rate(self, channel: ChannelType | None = None) -> float:
        """Get delivery rate.

        Args:
            channel: Filter by channel (optional)

        Returns:
            Delivery rate (0-1)
        """
        if not self.delivery_results:
            return 0.0

        delivered = sum(
            1
            for r in self.delivery_results
            if (r.status == DeliveryStatus.DELIVERED and (channel is None or r.channel_type == channel))
        )

        total = sum(1 for r in self.delivery_results if channel is None or r.channel_type == channel)

        if total == 0:
            return 0.0

        return delivered / total

    def get_channel_stats(self, channel: ChannelType) -> dict[str, int]:
        """Get statistics for a channel.

        Args:
            channel: Channel type

        Returns:
            Channel statistics
        """
        return self.channel_stats.get(channel, {"sent": 0, "delivered": 0, "failed": 0})

    def get_average_delivery_time(self) -> float:
        """Get average delivery time in milliseconds.

        Returns:
            Average delivery time
        """
        results_with_time = [r for r in self.delivery_results if r.delivery_time_ms is not None]

        if not results_with_time:
            return 0.0

        total_time = sum(r.delivery_time_ms for r in results_with_time)

        return total_time / len(results_with_time)
