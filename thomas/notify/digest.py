"""
Notification digest system for aggregating and batching notifications.
Supports scheduling and personalization.
"""

from datetime import datetime, timedelta

from thomas.notify._exceptions import NotifyException
from thomas.notify._types import (
    Category,
    ChannelType,
    Digest,
    Notification,
)


class DigestScheduler:
    """Schedules and manages notification digests."""

    def __init__(self) -> None:
        """Initialize digest scheduler."""
        self.digests: dict[str, Digest] = {}
        self.pending_notifications: dict[str, list[Notification]] = {}
        self.sent_digests: dict[str, list[datetime]] = {}

    def create_digest(
        self,
        user_id: str,
        frequency: str,
        preferred_time: str = "09:00",
        timezone: str = "UTC",
        categories: list[Category] | None = None,
        channel_type: ChannelType = ChannelType.EMAIL,
    ) -> Digest:
        """Create digest configuration.

        Args:
            user_id: User identifier
            frequency: "daily" or "weekly"
            preferred_time: Delivery time (HH:MM)
            timezone: User timezone
            categories: Categories to include (all if None)
            channel_type: Channel for digest delivery

        Returns:
            Created digest

        Raises:
            NotifyException: If configuration invalid
        """
        if frequency not in ("daily", "weekly"):
            raise NotifyException(f"Invalid frequency: {frequency}")

        digest = Digest(
            user_id=user_id,
            frequency=frequency,
            preferred_time=preferred_time,
            timezone=timezone,
            categories=categories or list(Category),
            channel_type=channel_type,
        )

        self.digests[digest.digest_id] = digest

        if user_id not in self.pending_notifications:
            self.pending_notifications[user_id] = []

        return digest

    def add_pending_notification(self, user_id: str, notification: Notification) -> None:
        """Add notification to user's digest queue.

        Args:
            user_id: User identifier
            notification: Notification to queue
        """
        if user_id not in self.pending_notifications:
            self.pending_notifications[user_id] = []

        self.pending_notifications[user_id].append(notification)

    def get_pending_notifications(self, user_id: str) -> list[Notification]:
        """Get pending notifications for user.

        Args:
            user_id: User identifier

        Returns:
            List of pending notifications
        """
        return self.pending_notifications.get(user_id, [])

    def get_pending_notifications_by_category(self, user_id: str) -> dict[Category, list[Notification]]:
        """Get pending notifications grouped by category.

        Args:
            user_id: User identifier

        Returns:
            Dictionary of notifications by category
        """
        notifications = self.get_pending_notifications(user_id)

        grouped: dict[Category, list[Notification]] = {}
        for notif in notifications:
            if notif.category not in grouped:
                grouped[notif.category] = []
            grouped[notif.category].append(notif)

        return grouped

    def clear_pending_notifications(self, user_id: str) -> int:
        """Clear pending notifications for user.

        Args:
            user_id: User identifier

        Returns:
            Number of notifications cleared
        """
        count = len(self.pending_notifications.get(user_id, []))
        self.pending_notifications[user_id] = []
        return count

    def is_time_to_send(self, user_id: str, current_time: datetime | None = None) -> bool:
        """Check if it's time to send digest.

        Args:
            user_id: User identifier
            current_time: Current time (defaults to now)

        Returns:
            True if digest should be sent
        """
        if user_id not in self.digests:
            return False

        digest = self.digests[user_id]
        if not digest.enabled:
            return False

        if current_time is None:
            current_time = datetime.utcnow()

        # Parse preferred time
        hour, minute = map(int, digest.preferred_time.split(":"))
        preferred_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # Check if we're near preferred time (within 5 minutes window)
        time_diff = abs((current_time - preferred_time).total_seconds())
        within_window = time_diff <= 300  # 5-minute window

        if not within_window:
            return False

        # Check frequency
        if digest.frequency == "daily":
            return self._should_send_daily(user_id, current_time)
        elif digest.frequency == "weekly":
            return self._should_send_weekly(user_id, current_time)

        return False

    def has_pending_notifications(self, user_id: str) -> bool:
        """Check if user has pending notifications.

        Args:
            user_id: User identifier

        Returns:
            True if has pending
        """
        return len(self.pending_notifications.get(user_id, [])) > 0

    def should_skip_empty_digest(self, user_id: str) -> bool:
        """Check if digest should be skipped (no pending).

        Args:
            user_id: User identifier

        Returns:
            True if digest is empty
        """
        return not self.has_pending_notifications(user_id)

    def mark_digest_sent(self, user_id: str) -> None:
        """Mark digest as sent.

        Args:
            user_id: User identifier
        """
        if user_id not in self.sent_digests:
            self.sent_digests[user_id] = []

        self.sent_digests[user_id].append(datetime.utcnow())

        # Keep only last 30 days of records
        cutoff = datetime.utcnow() - timedelta(days=30)
        self.sent_digests[user_id] = [ts for ts in self.sent_digests[user_id] if ts > cutoff]

    def get_digest(self, user_id: str) -> Digest | None:
        """Get digest for user.

        Args:
            user_id: User identifier

        Returns:
            Digest or None if not configured
        """
        return self.digests.get(user_id)

    def disable_digest(self, user_id: str) -> None:
        """Disable digest for user.

        Args:
            user_id: User identifier
        """
        if user_id in self.digests:
            self.digests[user_id].enabled = False

    def _should_send_daily(self, user_id: str, current_time: datetime) -> bool:
        """Check if should send daily digest.

        Args:
            user_id: User identifier
            current_time: Current time

        Returns:
            True if should send
        """
        if user_id not in self.sent_digests:
            return True

        sent_times = self.sent_digests[user_id]
        if not sent_times:
            return True

        last_sent = sent_times[-1]
        hours_elapsed = (current_time - last_sent).total_seconds() / 3600

        return hours_elapsed >= 24

    def _should_send_weekly(self, user_id: str, current_time: datetime) -> bool:
        """Check if should send weekly digest.

        Args:
            user_id: User identifier
            current_time: Current time

        Returns:
            True if should send
        """
        if user_id not in self.sent_digests:
            return True

        sent_times = self.sent_digests[user_id]
        if not sent_times:
            return True

        last_sent = sent_times[-1]
        days_elapsed = (current_time - last_sent).total_seconds() / 86400

        return days_elapsed >= 7


class DigestRenderer:
    """Renders digest content from pending notifications."""

    def __init__(self) -> None:
        """Initialize digest renderer."""
        pass

    def render_digest_body(
        self,
        notifications: dict[Category, list[Notification]],
        include_empty_categories: bool = False,
    ) -> str:
        """Render digest body from notifications.

        Args:
            notifications: Notifications grouped by category
            include_empty_categories: Include categories with no items

        Returns:
            Rendered digest text
        """
        sections = []

        for category, notifs in notifications.items():
            if not notifs and not include_empty_categories:
                continue

            section = self._render_category_section(category, notifs)
            if section:
                sections.append(section)

        return "\n\n".join(sections)

    def render_digest_html(
        self,
        notifications: dict[Category, list[Notification]],
        include_empty_categories: bool = False,
    ) -> str:
        """Render digest as HTML.

        Args:
            notifications: Notifications grouped by category
            include_empty_categories: Include categories with no items

        Returns:
            Rendered HTML digest
        """
        sections = []
        sections.append("<html><body>")

        for category, notifs in notifications.items():
            if not notifs and not include_empty_categories:
                continue

            html_section = self._render_category_section_html(category, notifs)
            sections.append(html_section)

        sections.append("</body></html>")
        return "".join(sections)

    def get_digest_summary(self, notifications: dict[Category, list[Notification]]) -> dict[str, int]:
        """Get summary counts by category.

        Args:
            notifications: Notifications grouped by category

        Returns:
            Count by category
        """
        summary = {}

        for category, notifs in notifications.items():
            summary[category.value] = len(notifs)

        return summary

    def _render_category_section(self, category: Category, notifications: list[Notification]) -> str:
        """Render category section.

        Args:
            category: Notification category
            notifications: Notifications in category

        Returns:
            Rendered section text
        """
        if not notifications:
            return ""

        lines = [f"--- {category.value.upper()} " f"({len(notifications)} items) ---"]

        for i, notif in enumerate(notifications[:10], 1):
            lines.append(f"{i}. {notif.template_id}")

        if len(notifications) > 10:
            lines.append(f"... and {len(notifications) - 10} more")

        return "\n".join(lines)

    def _render_category_section_html(self, category: Category, notifications: list[Notification]) -> str:
        """Render category section as HTML.

        Args:
            category: Notification category
            notifications: Notifications in category

        Returns:
            Rendered HTML section
        """
        if not notifications:
            return ""

        html = []
        html.append(f"<section><h2>{category.value.upper()} " f"({len(notifications)} items)</h2>")
        html.append("<ul>")

        for notif in notifications[:10]:
            html.append(f"<li>{notif.template_id}</li>")

        if len(notifications) > 10:
            html.append(f"<li>... and {len(notifications) - 10} more</li>")

        html.append("</ul></section>")

        return "".join(html)
