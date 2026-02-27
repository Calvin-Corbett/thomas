"""Tests for analytics and metrics."""

from datetime import datetime, timedelta
from uuid import uuid4

from thomas.social_platform import AnalyticsEngine


class TestAnalyticsEngine:
    """Test suite for AnalyticsEngine."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.engine = AnalyticsEngine()
        self.user_id = uuid4()
        self.post_id = uuid4()

    def test_record_post_view(self) -> None:
        """Test recording post view."""
        self.engine.record_post_view(self.post_id, self.user_id)

        stats = self.engine.get_post_stats(self.post_id)
        assert stats is not None
        assert stats.impressions == 1

    def test_record_post_views_multiple(self) -> None:
        """Test recording multiple post views."""
        for _ in range(5):
            self.engine.record_post_view(self.post_id)

        stats = self.engine.get_post_stats(self.post_id)
        assert stats.impressions == 5

    def test_record_post_engagement(self) -> None:
        """Test recording post engagement."""
        self.engine.record_post_view(self.post_id, 10)

        self.engine.record_post_engagement(self.post_id, self.user_id, "like")
        self.engine.record_post_engagement(self.post_id, uuid4(), "comment")
        self.engine.record_post_engagement(self.post_id, uuid4(), "share")

        stats = self.engine.get_post_stats(self.post_id)
        assert stats.like_count == 1
        assert stats.comment_count == 1
        assert stats.share_count == 1

    def test_engagement_rate_calculation(self) -> None:
        """Test engagement rate calculation."""
        self.engine.record_post_view(self.post_id, 100)
        self.engine.record_post_engagement(self.post_id, uuid4(), "like")
        self.engine.record_post_engagement(self.post_id, uuid4(), "like")

        stats = self.engine.get_post_stats(self.post_id)
        assert stats.engagement_rate > 0

    def test_record_user_session(self) -> None:
        """Test recording user session."""
        now = datetime.utcnow()
        start = now - timedelta(hours=1)
        end = now

        self.engine.record_user_session(self.user_id, start, end)

        dau = self.engine.calculate_dau()
        assert dau >= 1

    def test_dau_calculation(self) -> None:
        """Test DAU calculation."""
        now = datetime.utcnow()
        start = now - timedelta(hours=1)
        end = now

        for _ in range(3):
            self.engine.record_user_session(uuid4(), start, end)

        dau = self.engine.calculate_dau()
        assert dau == 3

    def test_mau_calculation(self) -> None:
        """Test MAU calculation."""
        now = datetime.utcnow()
        start = now - timedelta(days=15)
        end = now

        for _ in range(5):
            self.engine.record_user_session(uuid4(), start, end)

        mau = self.engine.calculate_mau()
        assert mau == 5

    def test_dau_mau_ratio(self) -> None:
        """Test DAU/MAU ratio calculation."""
        now = datetime.utcnow()
        today = now - timedelta(hours=1)

        # Record 2 users today
        for _ in range(2):
            self.engine.record_user_session(uuid4(), today, now)

        # Record 5 users this month
        for _ in range(3):
            start = now - timedelta(days=20)
            self.engine.record_user_session(uuid4(), start, now)

        ratio = self.engine.get_dau_mau_ratio()
        assert 0 <= ratio <= 1

    def test_record_user_activity(self) -> None:
        """Test recording user activity."""
        self.engine.record_user_activity(self.user_id, "post", 5)

        stats = self.engine.get_user_stats(self.user_id)
        assert stats.total_posts == 5

    def test_record_reach(self) -> None:
        """Test recording content reach."""
        self.engine.record_reach(self.user_id, 1000)

        stats = self.engine.get_user_stats(self.user_id)
        assert stats.reach_this_month == 1000

    def test_record_hashtag_usage(self) -> None:
        """Test recording hashtag usage."""
        self.engine.record_hashtag_usage("python")
        self.engine.record_hashtag_usage("python")
        self.engine.record_hashtag_usage("coding")

        assert self.engine.hashtag_stats["python"].usage_count == 2
        assert self.engine.hashtag_stats["coding"].usage_count == 1

    def test_trending_hashtags(self) -> None:
        """Test getting trending hashtags."""
        for i in range(10):
            self.engine.record_hashtag_usage("trending")
        for i in range(5):
            self.engine.record_hashtag_usage("popular")
        for i in range(2):
            self.engine.record_hashtag_usage("niche")

        trending = self.engine.get_trending_hashtags(limit=2)

        assert len(trending) <= 2
        assert trending[0].hashtag in ["trending", "popular"]

    def test_calculate_retention_cohort(self) -> None:
        """Test retention cohort calculation."""
        now = datetime.utcnow()
        cohort_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        check_date = now.strftime("%Y-%m-%d")

        # Record users on cohort date
        for _ in range(5):
            start = datetime.strptime(cohort_date, "%Y-%m-%d")
            self.engine.record_user_session(uuid4(), start, start + timedelta(hours=1))

        # Record 3 of them on check date
        for _ in range(3):
            start = datetime.strptime(check_date, "%Y-%m-%d")
            self.engine.record_user_session(uuid4(), start, start + timedelta(hours=1))

        retention = self.engine.calculate_retention_cohort(cohort_date, 7)

        # Should be between 0 and 1
        assert 0 <= retention <= 1

    def test_k_factor_calculation(self) -> None:
        """Test K-factor (viral coefficient) calculation."""
        user = uuid4()

        # Give user some stats
        self.engine.record_user_activity(user, "post")
        self.engine.record_reach(user, 100)
        self.engine.record_user_activity(user, "follow", 5)

        k_factor = self.engine.calculate_k_factor(user)

        assert 0 <= k_factor <= 10

    def test_avg_session_duration(self) -> None:
        """Test average session duration calculation."""
        now = datetime.utcnow()

        # Record multiple sessions
        for i in range(3):
            start = now - timedelta(hours=1, minutes=i * 10)
            end = start + timedelta(minutes=30)
            self.engine.record_user_session(self.user_id, start, end)

        avg_duration = self.engine.get_avg_session_duration(self.user_id)

        assert avg_duration is not None
        assert avg_duration > 0

    def test_aggregate_time_series(self) -> None:
        """Test time series aggregation."""
        now = datetime.utcnow()

        # Record users over 7 days
        for i in range(7):
            date = now - timedelta(days=i)
            for _ in range(i + 1):
                self.engine.record_user_session(uuid4(), date, date + timedelta(hours=1))

        series = self.engine.aggregate_time_series("dau", days_back=7)

        assert len(series) > 0
        assert all(isinstance(v, (int, float)) for _, v in series)

    def test_growth_metrics(self) -> None:
        """Test growth metrics calculation."""
        now = datetime.utcnow()

        # Record activity
        for _ in range(5):
            user = uuid4()
            self.engine.record_user_activity(user, "post")
            start = now - timedelta(hours=12)
            self.engine.record_user_session(user, start, now)

        metrics = self.engine.get_growth_metrics(days=1)

        assert "new_users" in metrics
        assert "total_posts" in metrics
        assert "dau" in metrics
        assert "mau" in metrics

    def test_post_stats(self) -> None:
        """Test post statistics."""
        post = uuid4()

        self.engine.record_post_view(post, 100)
        self.engine.record_post_engagement(post, uuid4(), "like")

        stats = self.engine.get_post_stats(post)
        assert stats is not None
        assert stats.like_count == 1

    def test_user_stats(self) -> None:
        """Test user statistics."""
        user = uuid4()

        self.engine.record_user_activity(user, "post", 3)
        self.engine.record_user_activity(user, "like_received", 10)

        stats = self.engine.get_user_stats(user)
        assert stats is not None
        assert stats.total_posts == 3
        assert stats.total_reactions == 10

    def test_stats_initialization(self) -> None:
        """Test that stats are initialized on first access."""
        post = uuid4()
        user = uuid4()

        # Should not exist yet
        assert self.engine.get_post_stats(post) is None
        assert self.engine.get_user_stats(user) is None

        # Record activity
        self.engine.record_post_view(post)
        self.engine.record_user_activity(user, "post")

        # Now should exist
        assert self.engine.get_post_stats(post) is not None
        assert self.engine.get_user_stats(user) is not None

    def test_multiple_engagement_types(self) -> None:
        """Test recording multiple engagement types for same post."""
        post = uuid4()

        self.engine.record_post_view(post, 100)

        for i in range(5):
            self.engine.record_post_engagement(post, uuid4(), "like")

        for i in range(3):
            self.engine.record_post_engagement(post, uuid4(), "comment")

        for i in range(2):
            self.engine.record_post_engagement(post, uuid4(), "share")

        stats = self.engine.get_post_stats(post)
        assert stats.like_count == 5
        assert stats.comment_count == 3
        assert stats.share_count == 2
