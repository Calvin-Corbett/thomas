"""Notification system with batching and preferences.

This module handles notification types, user preferences, push notification
batching, in-app feed, read/unread tracking, grouping, rate limiting,
and digest generation.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from ._types import Notification, NotificationType


class NotificationManager:
    """Manages user notifications and preferences.

    Attributes:
        notifications: Dictionary mapping notification_id to Notification
        user_notifications: Map of user_id to list of notification_ids
        user_preferences: Notification preferences per user and type
        pending_batches: Messages pending to batch for delivery
        rate_limit_tracker: Track notification rate per user
        digest_queue: Queue of users needing digests
    """

    # Rate limiting
    MAX_NOTIFICATIONS_PER_HOUR = 30
    BATCH_WINDOW_MINUTES = 15
    DIGEST_FREQUENCY_HOURS = 24

    def __init__(self) -> None:
        """Initialize notification manager."""
        self.notifications: dict[UUID, Notification] = {}
        self.user_notifications: dict[UUID, list[UUID]] = defaultdict(list)
        self.user_preferences: dict[UUID, dict[NotificationType, bool]] = defaultdict(
            lambda: {nt: True for nt in NotificationType}
        )
        self.pending_batches: dict[UUID, list[Notification]] = defaultdict(list)
        self.rate_limit_tracker: dict[UUID, list[datetime]] = defaultdict(list)
        self.digest_queue: set[UUID] = set()
        self.last_digest_sent: dict[UUID, datetime] = {}

    def create_notification(
        self,
        user_id: UUID,
        notif_type: NotificationType,
        actor_ids: list[UUID],
        title: str,
        body: str,
        content_id: UUID | None = None,
        action_url: str | None = None,
    ) -> Notification | None:
        """Create a notification for user.

        Args:
            user_id: Recipient user ID
            notif_type: Notification type
            actor_ids: List of users causing notification
            title: Notification title
            body: Notification body
            content_id: ID of related content
            action_url: URL for action

        Returns:
            Created Notification or None if filtered/rate-limited
        """
        # Check preferences
        if not self.user_preferences[user_id].get(notif_type, True):
            return None

        # Check rate limit
        if not self._check_rate_limit(user_id):
            return None

        notification = Notification(
            user_id=user_id,
            type=notif_type,
            actor_ids=actor_ids,
            title=title,
            body=body,
            content_id=content_id,
            action_url=action_url,
            created_at=datetime.utcnow(),
        )

        self.notifications[notification.id] = notification
        self.user_notifications[user_id].append(notification.id)

        # Track for rate limiting
        self.rate_limit_tracker[user_id].append(datetime.utcnow())

        # Add to batch for delivery
        self.pending_batches[user_id].append(notification)

        return notification

    def _check_rate_limit(self, user_id: UUID) -> bool:
        """Check if user has exceeded rate limit.

        Args:
            user_id: User ID

        Returns:
            True if within limit
        """
        cutoff = datetime.utcnow() - timedelta(hours=1)
        recent = [t for t in self.rate_limit_tracker[user_id] if t > cutoff]
        self.rate_limit_tracker[user_id] = recent

        return len(recent) < self.MAX_NOTIFICATIONS_PER_HOUR

    def set_notification_preference(self, user_id: UUID, notif_type: NotificationType, enabled: bool) -> None:
        """Set notification preference for user.

        Args:
            user_id: User ID
            notif_type: Notification type
            enabled: Whether to enable
        """
        self.user_preferences[user_id][notif_type] = enabled

    def get_notification_preferences(self, user_id: UUID) -> dict[NotificationType, bool]:
        """Get user's notification preferences.

        Args:
            user_id: User ID

        Returns:
            Dictionary mapping notification type to enabled
        """
        return self.user_preferences[user_id]

    def get_user_notifications(self, user_id: UUID, limit: int = 20, unread_only: bool = False) -> list[Notification]:
        """Get notifications for user.

        Args:
            user_id: User ID
            limit: Maximum notifications
            unread_only: Only unread if True

        Returns:
            List of Notification objects
        """
        notif_ids = self.user_notifications.get(user_id, [])
        notifs = [self.notifications[nid] for nid in notif_ids if nid in self.notifications]

        if unread_only:
            notifs = [n for n in notifs if n.read_at is None]

        notifs.sort(key=lambda n: n.created_at, reverse=True)
        return notifs[:limit]

    def mark_as_read(self, notification_id: UUID) -> None:
        """Mark notification as read.

        Args:
            notification_id: Notification ID
        """
        if notification_id in self.notifications:
            self.notifications[notification_id].read_at = datetime.utcnow()

    def mark_all_as_read(self, user_id: UUID) -> None:
        """Mark all user's notifications as read.

        Args:
            user_id: User ID
        """
        notif_ids = self.user_notifications.get(user_id, [])
        for notif_id in notif_ids:
            self.mark_as_read(notif_id)

    def get_unread_count(self, user_id: UUID) -> int:
        """Get unread notification count for user.

        Args:
            user_id: User ID

        Returns:
            Count of unread notifications
        """
        notif_ids = self.user_notifications.get(user_id, [])
        unread = sum(1 for nid in notif_ids if nid in self.notifications and self.notifications[nid].read_at is None)
        return unread

    def group_notifications(
        self, user_id: UUID, notif_type: NotificationType | None = None, max_group_size: int = 3
    ) -> list[Notification]:
        """Get grouped notifications.

        Groups similar notifications (3 people liked your post).

        Args:
            user_id: User ID
            notif_type: Filter by type
            max_group_size: Max actors to show individually

        Returns:
            List of grouped Notification objects
        """
        notifs = self.get_user_notifications(user_id)

        if notif_type:
            notifs = [n for n in notifs if n.type == notif_type]

        # Group by content_id and type
        grouped: dict[tuple, Notification] = {}
        for notif in notifs:
            key = (notif.type, notif.content_id)

            if key not in grouped:
                grouped[key] = notif
            else:
                # Merge actors
                grouped[key].actor_ids.extend(notif.actor_ids)
                grouped[key].actor_ids = list(set(grouped[key].actor_ids))

        result = list(grouped.values())
        result.sort(key=lambda n: n.created_at, reverse=True)

        return result

    def batch_notifications(self) -> dict[UUID, list[Notification]]:
        """Get batched notifications ready for delivery.

        Returns pending notifications that have been batching for
        BATCH_WINDOW_MINUTES.

        Returns:
            Dictionary mapping user_id to list of Notification objects
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=self.BATCH_WINDOW_MINUTES)

        batched = {}
        for user_id, notifs in list(self.pending_batches.items()):
            # Check if oldest notification is past batch window
            if notifs and notifs[0].created_at < cutoff:
                batched[user_id] = notifs
                self.pending_batches[user_id] = []

        return batched

    def generate_digest(self, user_id: UUID, frequency: str = "daily") -> str | None:
        """Generate notification digest for user.

        Args:
            user_id: User ID
            frequency: Digest frequency (daily, weekly)

        Returns:
            Digest text or None if no notifications
        """
        notifs = self.get_user_notifications(user_id, limit=100)

        if not notifs:
            return None

        lines = [f"Notification Digest ({frequency})"]
        lines.append("=" * 50)

        # Group by type
        by_type: dict[NotificationType, list[Notification]] = defaultdict(list)
        for notif in notifs:
            by_type[notif.type].append(notif)

        for notif_type, type_notifs in by_type.items():
            lines.append(f"\n{notif_type.value.upper()} ({len(type_notifs)})")
            lines.append("-" * 40)

            for notif in type_notifs[:5]:  # Show top 5 per type
                lines.append(f"  {notif.title}")
                if notif.body:
                    lines.append(f"    {notif.body}")

            if len(type_notifs) > 5:
                lines.append(f"  ... and {len(type_notifs) - 5} more")

        digest = "\n".join(lines)

        # Update last sent
        self.last_digest_sent[user_id] = datetime.utcnow()

        return digest

    def should_send_digest(self, user_id: UUID) -> bool:
        """Check if user should receive digest.

        Args:
            user_id: User ID

        Returns:
            True if digest is due
        """
        last_sent = self.last_digest_sent.get(user_id)

        if last_sent is None:
            return True

        elapsed = (datetime.utcnow() - last_sent).total_seconds() / 3600
        return elapsed >= self.DIGEST_FREQUENCY_HOURS

    def queue_digest(self, user_id: UUID) -> None:
        """Queue digest for user.

        Args:
            user_id: User ID
        """
        if self.should_send_digest(user_id):
            self.digest_queue.add(user_id)

    def get_digest_queue(self) -> list[UUID]:
        """Get users waiting for digests.

        Returns:
            List of user IDs
        """
        return list(self.digest_queue)

    def clear_digest_queue(self) -> None:
        """Clear digest queue after sending."""
        self.digest_queue.clear()

    def get_notification_stats(self, user_id: UUID) -> dict[str, int]:
        """Get notification statistics for user.

        Args:
            user_id: User ID

        Returns:
            Dictionary with stats
        """
        notifs = self.user_notifications.get(user_id, [])
        unread = sum(1 for nid in notifs if nid in self.notifications and self.notifications[nid].read_at is None)

        by_type: dict[NotificationType, int] = defaultdict(int)
        for nid in notifs:
            if nid in self.notifications:
                by_type[self.notifications[nid].type] += 1

        return {
            "total_notifications": len(notifs),
            "unread_count": unread,
            "notifications_by_type": {k.value: v for k, v in by_type.items()},
        }

    def clear_old_notifications(self, days: int = 30) -> int:
        """Clear notifications older than specified days.

        Args:
            days: Age threshold in days

        Returns:
            Count of cleared notifications
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        to_delete = []

        for notif_id, notif in self.notifications.items():
            if notif.created_at < cutoff:
                to_delete.append(notif_id)

        for notif_id in to_delete:
            del self.notifications[notif_id]

            # Remove from user lists
            for user_notifs in self.user_notifications.values():
                if notif_id in user_notifs:
                    user_notifs.remove(notif_id)

        return len(to_delete)

    def delete_notification(self, notification_id: UUID) -> None:
        """Delete a notification.

        Args:
            notification_id: Notification ID
        """
        if notification_id in self.notifications:
            del self.notifications[notification_id]

            for user_notifs in self.user_notifications.values():
                if notification_id in user_notifs:
                    user_notifs.remove(notification_id)
