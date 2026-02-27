"""
Notification routing engine with preference-based channel selection,
cascading fallbacks, quiet hours, and frequency capping.
"""

from datetime import datetime, timedelta

from thomas.notify._exceptions import RoutingException
from thomas.notify._types import (
    ChannelType,
    Notification,
    NotificationPreference,
)


class RoutingEngine:
    """Routes notifications to appropriate channels based on preferences."""

    def __init__(self) -> None:
        """Initialize routing engine."""
        self.preferences: dict[str, NotificationPreference] = {}
        self.sent_notifications: dict[str, list[tuple[str, datetime]]] = {}
        self.deduplication_window = timedelta(minutes=5)

    def register_preference(self, preference: NotificationPreference) -> None:
        """Register user preference.

        Args:
            preference: User notification preference
        """
        self.preferences[preference.user_id] = preference

        if preference.user_id not in self.sent_notifications:
            self.sent_notifications[preference.user_id] = []

    def get_preference(self, user_id: str) -> NotificationPreference:
        """Get user preference with defaults.

        Args:
            user_id: User identifier

        Returns:
            Notification preference (creates default if not found)
        """
        if user_id not in self.preferences:
            self.preferences[user_id] = NotificationPreference(user_id=user_id)

        return self.preferences[user_id]

    def route(self, notification: Notification) -> list[ChannelType]:
        """Route notification to appropriate channels.

        Args:
            notification: Notification to route

        Returns:
            Ordered list of channels to attempt delivery

        Raises:
            RoutingException: If routing fails
        """
        try:
            preference = self.get_preference(notification.recipient.user_id)

            # Check global opt-out
            if preference.global_opt_out:
                raise RoutingException(f"User {notification.recipient.user_id} has opted out")

            # Check deduplication
            if self._is_duplicate(notification):
                raise RoutingException(f"Notification is duplicate within {self.deduplication_window}")

            # Check quiet hours
            in_quiet_hours = self._check_quiet_hours(
                notification.recipient.timezone,
                preference,
            )

            if in_quiet_hours and not notification.should_skip_quiet_hours():
                raise RoutingException(f"User is in quiet hours for {notification.category.value}")

            # Check frequency cap
            if self._exceeds_frequency_cap(
                notification.recipient.user_id,
                notification.channel_type,
                preference,
            ):
                return []

            # Get channels with cascade fallback
            channels = self._get_channels_with_cascade(notification, preference)

            if not channels:
                raise RoutingException(f"No available channels for user {notification.recipient.user_id}")

            self._record_notification(notification)
            return channels

        except RoutingException:
            raise
        except Exception as e:
            raise RoutingException(f"Routing failed: {str(e)}")

    def _is_duplicate(self, notification: Notification) -> bool:
        """Check if notification is duplicate.

        Args:
            notification: Notification to check

        Returns:
            True if duplicate within deduplication window
        """
        user_id = notification.recipient.user_id
        if user_id not in self.sent_notifications:
            return False

        recent = [n for n in self.sent_notifications[user_id] if datetime.utcnow() - n[1] < self.deduplication_window]

        # Check if same template was sent recently
        for template_id, _ in recent:
            if template_id == notification.template_id:
                return True

        return False

    def _check_quiet_hours(self, user_timezone: str, preference: NotificationPreference) -> bool:
        """Check if user is in quiet hours.

        Args:
            user_timezone: User timezone
            preference: User preferences

        Returns:
            True if in quiet hours
        """
        if not preference.quiet_hours_enabled:
            return False

        try:
            start_str = preference.quiet_hours_start
            end_str = preference.quiet_hours_end

            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()

            current_time = datetime.utcnow().time()

            if start_time <= end_time:
                return start_time <= current_time <= end_time
            else:
                return current_time >= start_time or current_time <= end_time

        except (ValueError, AttributeError):
            return False

    def _exceeds_frequency_cap(
        self,
        user_id: str,
        channel_type: ChannelType,
        preference: NotificationPreference,
    ) -> bool:
        """Check if user exceeds frequency cap.

        Args:
            user_id: User identifier
            channel_type: Channel type
            preference: User preferences

        Returns:
            True if frequency cap exceeded
        """
        max_per_day = preference.max_per_channel_per_day.get(channel_type)

        if max_per_day is None:
            return False

        if user_id not in self.sent_notifications:
            return False

        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())

        sent_today = [n for n in self.sent_notifications[user_id] if n[1] >= today_start]

        return len(sent_today) >= max_per_day

    def _get_channels_with_cascade(
        self,
        notification: Notification,
        preference: NotificationPreference,
    ) -> list[ChannelType]:
        """Get channels with cascade fallback strategy.

        Args:
            notification: Notification to route
            preference: User preferences

        Returns:
            Ordered list of channels to attempt
        """
        recipient = notification.recipient
        category = notification.category

        # Preferred channels in order
        preferred = preference.get_preferred_channels()

        # Filter by user preference and channel availability
        available_channels = []
        for channel in preferred:
            if not preference.is_category_enabled(category, channel):
                continue

            if not recipient.get_channel_address(channel):
                continue

            available_channels.append(channel)

        if available_channels:
            return available_channels

        # Cascade fallback: email -> SMS -> push
        cascade = [
            ChannelType.EMAIL,
            ChannelType.SMS,
            ChannelType.PUSH,
            ChannelType.IN_APP,
        ]

        fallback_channels = []
        for channel in cascade:
            if not recipient.get_channel_address(channel):
                continue

            if not preference.is_category_enabled(category, channel):
                continue

            fallback_channels.append(channel)

        return fallback_channels

    def _record_notification(self, notification: Notification) -> None:
        """Record sent notification for deduplication/capping.

        Args:
            notification: Notification to record
        """
        user_id = notification.recipient.user_id

        if user_id not in self.sent_notifications:
            self.sent_notifications[user_id] = []

        self.sent_notifications[user_id].append((notification.template_id, datetime.utcnow()))

        # Keep only last 1000 notifications per user
        if len(self.sent_notifications[user_id]) > 1000:
            self.sent_notifications[user_id] = self.sent_notifications[user_id][-1000:]

    def set_quiet_hours(
        self,
        user_id: str,
        enabled: bool,
        start_time: str = "22:00",
        end_time: str = "08:00",
    ) -> None:
        """Set quiet hours for user.

        Args:
            user_id: User identifier
            enabled: Enable/disable quiet hours
            start_time: Quiet hours start (HH:MM)
            end_time: Quiet hours end (HH:MM)
        """
        preference = self.get_preference(user_id)
        preference.quiet_hours_enabled = enabled
        preference.quiet_hours_start = start_time
        preference.quiet_hours_end = end_time

    def set_frequency_cap(
        self,
        user_id: str,
        channel_type: ChannelType,
        max_per_day: int,
    ) -> None:
        """Set frequency cap for channel.

        Args:
            user_id: User identifier
            channel_type: Channel type
            max_per_day: Maximum per day
        """
        preference = self.get_preference(user_id)
        preference.max_per_channel_per_day[channel_type] = max_per_day


class DeduplicationEngine:
    """Handles notification deduplication."""

    def __init__(self, window: timedelta = timedelta(minutes=5)) -> None:
        """Initialize deduplication engine.

        Args:
            window: Deduplication window duration
        """
        self.window = window
        self.sent_hashes: dict[str, datetime] = {}

    def get_notification_hash(self, notification: Notification) -> str:
        """Get unique hash for notification.

        Args:
            notification: Notification to hash

        Returns:
            Hash string combining recipient, template, and category
        """
        import hashlib

        data = f"{notification.recipient.user_id}:" f"{notification.template_id}:" f"{notification.category.value}"

        return hashlib.sha256(data.encode()).hexdigest()

    def is_duplicate(self, notification: Notification) -> bool:
        """Check if notification is duplicate.

        Args:
            notification: Notification to check

        Returns:
            True if duplicate within window
        """
        notification_hash = self.get_notification_hash(notification)

        if notification_hash not in self.sent_hashes:
            return False

        last_sent = self.sent_hashes[notification_hash]
        elapsed = datetime.utcnow() - last_sent

        return elapsed < self.window

    def mark_sent(self, notification: Notification) -> None:
        """Mark notification as sent.

        Args:
            notification: Notification that was sent
        """
        notification_hash = self.get_notification_hash(notification)
        self.sent_hashes[notification_hash] = datetime.utcnow()

        # Cleanup old entries
        cutoff = datetime.utcnow() - self.window * 2
        self.sent_hashes = {h: ts for h, ts in self.sent_hashes.items() if ts > cutoff}

    def cleanup(self) -> int:
        """Remove expired hashes.

        Returns:
            Number of hashes removed
        """
        cutoff = datetime.utcnow() - self.window
        initial_count = len(self.sent_hashes)

        self.sent_hashes = {h: ts for h, ts in self.sent_hashes.items() if ts > cutoff}

        return initial_count - len(self.sent_hashes)
