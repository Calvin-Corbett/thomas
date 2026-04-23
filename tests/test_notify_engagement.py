"""
Tests for engagement tracking and metrics.
"""

from datetime import datetime, timedelta

from thomas.notify.engagement import (
    EngagementTracker,
    OptimalSendTimePredictor,
    ReEngagementCampaignManager,
)


class TestEngagementTracker:
    """Tests for engagement tracking."""

    def test_record_open(self) -> None:
        """Test recording open event."""
        tracker = EngagementTracker()

        metric = tracker.record_open(
            notification_id="notif1",
            user_id="user1",
        )

        assert metric.metric_type == "open"
        assert metric.notification_id == "notif1"

    def test_record_click(self) -> None:
        """Test recording click event."""
        tracker = EngagementTracker()

        metric = tracker.record_click(
            notification_id="notif1",
            user_id="user1",
            url="https://example.com",
        )

        assert metric.metric_type == "click"
        assert metric.url_clicked == "https://example.com"

    def test_record_conversion(self) -> None:
        """Test recording conversion event."""
        tracker = EngagementTracker()

        metric = tracker.record_conversion(
            notification_id="notif1",
            user_id="user1",
            conversion_value=99.99,
        )

        assert metric.metric_type == "conversion"
        assert metric.metadata["value"] == 99.99

    def test_calculate_engagement_score(self) -> None:
        """Test engagement score calculation."""
        tracker = EngagementTracker()

        tracker.record_open("notif1", "user1")
        tracker.record_click("notif1", "user1")
        tracker.record_conversion("notif1", "user1")

        score = tracker.calculate_engagement_score("notif1")

        # 1 (open) + 3 (click) + 5 (conversion) = 9
        assert score == 9

    def test_get_engagement_funnel(self) -> None:
        """Test engagement funnel calculation."""
        tracker = EngagementTracker()

        tracker.record_open("notif1", "user1")
        tracker.record_click("notif1", "user1")

        funnel = tracker.get_engagement_funnel("notif1")

        assert funnel["sent"] == 1
        assert funnel["opened"] == 1
        assert funnel["clicked"] == 1

    def test_get_user_engagement_score(self) -> None:
        """Test aggregate user engagement score."""
        tracker = EngagementTracker()

        tracker.record_open("notif1", "user1")
        tracker.record_open("notif2", "user1")
        tracker.record_click("notif3", "user1")

        score = tracker.get_user_engagement_score("user1")

        # 1 + 1 + 3 = 5
        assert score == 5


class TestOptimalSendTimePredictor:
    """Tests for optimal send time prediction."""

    def test_record_open_time(self) -> None:
        """Test recording open time."""
        predictor = OptimalSendTimePredictor()

        now = datetime.utcnow()
        predictor.record_open_time("user1", now)

        assert "user1" in predictor.user_open_patterns
        assert now.hour in predictor.user_open_patterns["user1"]

    def test_get_optimal_send_hour(self) -> None:
        """Test optimal send hour calculation."""
        predictor = OptimalSendTimePredictor()

        # Record opens at 9am multiple times
        base_time = datetime.utcnow().replace(hour=9, minute=0)

        for i in range(10):
            predictor.record_open_time(
                "user1",
                base_time + timedelta(days=i),
            )

        best_hour = predictor.get_optimal_send_hour("user1")

        assert best_hour == 9

    def test_insufficient_data_returns_none(self) -> None:
        """Test that insufficient data returns None."""
        predictor = OptimalSendTimePredictor()

        # Only 3 data points (need 5)
        for i in range(3):
            predictor.record_open_time(
                "user1",
                datetime.utcnow(),
            )

        best_hour = predictor.get_optimal_send_hour("user1")

        assert best_hour is None

    def test_get_engagement_by_hour(self) -> None:
        """Test engagement distribution by hour."""
        predictor = OptimalSendTimePredictor()

        # Record opens at different hours
        for hour in range(9, 17):
            base_time = datetime.utcnow().replace(hour=hour)
            for _ in range(5):
                predictor.record_open_time(
                    "user1",
                    base_time,
                )

        distribution = predictor.get_engagement_by_hour("user1")

        for hour in range(9, 17):
            assert distribution[hour] == 5


class TestReEngagementCampaignManager:
    """Tests for re-engagement campaign management."""

    def test_record_engagement(self) -> None:
        """Test recording engagement."""
        manager = ReEngagementCampaignManager(inactivity_days=30)

        now = datetime.utcnow()
        manager.record_engagement("user1", now)

        assert "user1" in manager.user_last_engagement

    def test_is_inactive_new_user(self) -> None:
        """Test new user without engagement is inactive."""
        manager = ReEngagementCampaignManager(inactivity_days=30)

        assert manager.is_inactive("user1") is True

    def test_is_inactive_recently_engaged(self) -> None:
        """Test recently engaged user is not inactive."""
        manager = ReEngagementCampaignManager(inactivity_days=30)

        now = datetime.utcnow()
        manager.record_engagement("user1", now)

        assert manager.is_inactive("user1") is False

    def test_is_inactive_old_engagement(self) -> None:
        """Test user with old engagement is inactive."""
        manager = ReEngagementCampaignManager(inactivity_days=30)

        old_time = datetime.utcnow() - timedelta(days=40)
        manager.record_engagement("user1", old_time)

        assert manager.is_inactive("user1") is True

    def test_get_inactive_users(self) -> None:
        """Test getting list of inactive users."""
        manager = ReEngagementCampaignManager(inactivity_days=30)

        now = datetime.utcnow()
        old_time = datetime.utcnow() - timedelta(days=40)

        manager.record_engagement("user1", now)
        manager.record_engagement("user2", old_time)

        inactive = manager.get_inactive_users(["user1", "user2"])

        assert "user2" in inactive
        assert "user1" not in inactive

    def test_get_days_since_engagement(self) -> None:
        """Test getting days since engagement."""
        manager = ReEngagementCampaignManager()

        past = datetime.utcnow() - timedelta(days=5)
        manager.record_engagement("user1", past)

        days = manager.get_days_since_engagement("user1")

        assert days == 5

    def test_no_engagement_returns_none(self) -> None:
        """Test no engagement returns None."""
        manager = ReEngagementCampaignManager()

        days = manager.get_days_since_engagement("user1")

        assert days is None
