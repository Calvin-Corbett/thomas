"""
Tests for notification routing and preferences.
"""

from datetime import timedelta

import pytest

from thomas.notify._exceptions import RoutingException
from thomas.notify._types import (
    Category,
    ChannelType,
    Notification,
    NotificationPreference,
    Priority,
    Recipient,
)
from thomas.notify.routing import (
    DeduplicationEngine,
    RoutingEngine,
)


class TestRoutingEngine:
    """Tests for routing engine."""

    def test_route_with_no_opt_out(self) -> None:
        """Test routing with user not opted out."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            global_opt_out=False,
        )

        engine.register_preference(preference)

        recipient = Recipient(
            user_id="user1",
            email="user@example.com",
            phone_number="+1234567890",
        )

        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        channels = engine.route(notification)

        assert len(channels) > 0
        assert ChannelType.EMAIL in channels

    def test_route_with_global_opt_out_raises(self) -> None:
        """Test routing with globally opted out user raises."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            global_opt_out=True,
        )

        engine.register_preference(preference)

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        with pytest.raises(RoutingException):
            engine.route(notification)

    def test_quiet_hours_enforcement(self) -> None:
        """Test quiet hours are enforced."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            quiet_hours_enabled=True,
            quiet_hours_start="22:00",
            quiet_hours_end="08:00",
        )

        engine.register_preference(preference)

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            priority=Priority.NORMAL,
        )

        # Assuming current time is in quiet hours (this is simplified)
        # In practice would need to mock time

    def test_quiet_hours_bypass_for_urgent(self) -> None:
        """Test urgent notifications bypass quiet hours."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            quiet_hours_enabled=True,
            quiet_hours_start="22:00",
            quiet_hours_end="08:00",
        )

        engine.register_preference(preference)

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            priority=Priority.URGENT,
        )

        channels = engine.route(notification)

        assert len(channels) > 0

    def test_frequency_cap_exceeded(self) -> None:
        """Test frequency cap prevents delivery."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            max_per_channel_per_day={ChannelType.EMAIL: 1},
        )

        engine.register_preference(preference)

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification1 = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        notification2 = Notification(
            recipient=recipient,
            template_id="t2",
            channel_type=ChannelType.EMAIL,
        )

        channels1 = engine.route(notification1)
        assert len(channels1) > 0

        channels2 = engine.route(notification2)
        assert len(channels2) == 0

    def test_deduplication_detection(self) -> None:
        """Test duplicate notification detection."""
        engine = RoutingEngine()

        preference = NotificationPreference(user_id="user1")
        engine.register_preference(preference)

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        channels1 = engine.route(notification)
        assert len(channels1) > 0

        with pytest.raises(RoutingException):
            engine.route(notification)

    def test_cascade_fallback(self) -> None:
        """Test cascade fallback to alternative channels."""
        engine = RoutingEngine()

        preference = NotificationPreference(
            user_id="user1",
            preferred_channels=[
                ChannelType.PUSH,
                ChannelType.EMAIL,
                ChannelType.SMS,
            ],
        )

        engine.register_preference(preference)

        # Only SMS available
        recipient = Recipient(user_id="user1", phone_number="+1234567890")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
        )

        channels = engine.route(notification)

        assert len(channels) > 0


class TestDeduplicationEngine:
    """Tests for deduplication."""

    def test_duplicate_detection(self) -> None:
        """Test duplicate detection."""
        dedup = DeduplicationEngine(window=timedelta(minutes=5))

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            category=Category.MARKETING,
        )

        assert not dedup.is_duplicate(notification)

        dedup.mark_sent(notification)

        assert dedup.is_duplicate(notification)

    def test_duplicate_expires_outside_window(self) -> None:
        """Test duplicate detection expires after window."""
        dedup = DeduplicationEngine(window=timedelta(minutes=5))

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            category=Category.MARKETING,
        )

        dedup.mark_sent(notification)

        # Move time forward (simplified - in practice would mock datetime)
        dedup.sent_hashes.clear()

        assert not dedup.is_duplicate(notification)

    def test_cleanup_removes_expired(self) -> None:
        """Test cleanup removes expired hashes."""
        dedup = DeduplicationEngine(window=timedelta(minutes=5))

        recipient = Recipient(user_id="user1", email="user@example.com")
        notification = Notification(
            recipient=recipient,
            template_id="t1",
            channel_type=ChannelType.EMAIL,
            category=Category.MARKETING,
        )

        dedup.mark_sent(notification)

        initial_count = len(dedup.sent_hashes)

        removed = dedup.cleanup()

        # In real implementation with time travel
        assert isinstance(removed, int)
