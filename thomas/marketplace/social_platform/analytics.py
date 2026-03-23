"""Platform analytics and metrics aggregation.

This module tracks engagement metrics (DAU/MAU), content performance,
growth metrics, viral coefficient (K-factor), hashtag analytics,
and time-series aggregation with bucketing.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from ._types import HashtagStats, PostStats, UserStats


class AnalyticsEngine:
    """Tracks platform metrics and analytics.

    Attributes:
        post_stats: Statistics per post
        user_stats: Statistics per user
        hashtag_stats: Statistics per hashtag
        daily_active_users: Track DAU per day
        monthly_active_users: Track MAU
        session_data: User session information
        time_series: Aggregated metrics by time bucket
    """

    def __init__(self) -> None:
        """Initialize analytics engine."""
        self.post_stats: dict[UUID, PostStats] = {}
        self.user_stats: dict[UUID, UserStats] = {}
        self.hashtag_stats: dict[str, HashtagStats] = {}
        self.daily_active_users: dict[str, set] = defaultdict(set)  # date -> user_ids
        self.monthly_active_users: dict[str, set] = defaultdict(set)  # month -> user_ids
        self.session_data: dict[UUID, list[tuple[datetime, datetime]]] = defaultdict(list)
        self.time_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

    def record_post_view(self, post_id: UUID, user_id: UUID | None = None) -> None:
        """Record post view/impression.

        Args:
            post_id: Post ID
            user_id: Viewing user ID (optional for anonymous)
        """
        if post_id not in self.post_stats:
            self.post_stats[post_id] = PostStats(post_id=post_id)

        self.post_stats[post_id].impressions += 1

    def record_post_engagement(
        self,
        post_id: UUID,
        user_id: UUID,
        engagement_type: str,  # like, comment, share
    ) -> None:
        """Record post engagement.

        Args:
            post_id: Post ID
            user_id: User engaging
            engagement_type: Type of engagement
        """
        if post_id not in self.post_stats:
            self.post_stats[post_id] = PostStats(post_id=post_id)

        stats = self.post_stats[post_id]

        if engagement_type == "like":
            stats.like_count += 1
        elif engagement_type == "comment":
            stats.comment_count += 1
        elif engagement_type == "share":
            stats.share_count += 1

        # Recalculate engagement rate
        total_engagement = stats.like_count + stats.comment_count + stats.share_count
        stats.engagement_rate = total_engagement / max(stats.impressions, 1) if stats.impressions > 0 else 0

    def record_user_session(self, user_id: UUID, session_start: datetime, session_end: datetime) -> None:
        """Record user session.

        Args:
            user_id: User ID
            session_start: Session start time
            session_end: Session end time
        """
        self.session_data[user_id].append((session_start, session_end))

        # Track DAU/MAU
        date_str = session_start.strftime("%Y-%m-%d")
        month_str = session_start.strftime("%Y-%m")

        self.daily_active_users[date_str].add(user_id)
        self.monthly_active_users[month_str].add(user_id)

    def record_user_activity(
        self,
        user_id: UUID,
        activity_type: str,  # post, like, comment, follow
        value: float = 1.0,
    ) -> None:
        """Record user activity for stats.

        Args:
            user_id: User ID
            activity_type: Type of activity
            value: Activity value/count
        """
        if user_id not in self.user_stats:
            self.user_stats[user_id] = UserStats(user_id=user_id)

        stats = self.user_stats[user_id]

        if activity_type == "post":
            stats.total_posts += int(value)
            stats.posts_this_month += int(value)
        elif activity_type == "like_received":
            stats.total_reactions += int(value)
        elif activity_type == "comment_received":
            stats.total_comments_received += int(value)
        elif activity_type == "comment_made":
            stats.total_comments_made += int(value)
        elif activity_type == "follow":
            stats.followers_gained_this_month += int(value)

        stats.updated_at = datetime.utcnow()

    def record_reach(self, user_id: UUID, reach: int) -> None:
        """Record content reach for user.

        Args:
            user_id: User ID
            reach: Number of unique viewers
        """
        if user_id not in self.user_stats:
            self.user_stats[user_id] = UserStats(user_id=user_id)

        self.user_stats[user_id].reach_this_month += reach

    def record_impressions(self, user_id: UUID, impressions: int) -> None:
        """Record content impressions for user.

        Args:
            user_id: User ID
            impressions: Total impressions
        """
        if user_id not in self.user_stats:
            self.user_stats[user_id] = UserStats(user_id=user_id)

        self.user_stats[user_id].impressions_this_month += impressions

    def record_hashtag_usage(self, hashtag: str) -> None:
        """Record hashtag usage.

        Args:
            hashtag: Hashtag (without #)
        """
        if hashtag not in self.hashtag_stats:
            self.hashtag_stats[hashtag] = HashtagStats(hashtag=hashtag)

        stats = self.hashtag_stats[hashtag]
        stats.usage_count += 1
        stats.updated_at = datetime.utcnow()

    def update_hashtag_trending(self) -> None:
        """Calculate hashtag trending scores."""
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)

        for hashtag_stats in self.hashtag_stats.values():
            if hashtag_stats.updated_at > cutoff:
                # Trending score based on recent usage velocity
                hours_active = (now - hashtag_stats.updated_at).total_seconds() / 3600
                if hours_active > 0:
                    velocity = hashtag_stats.usage_count / hours_active
                    hashtag_stats.trending_score = velocity
            else:
                hashtag_stats.trending_score = 0.0

    def get_trending_hashtags(self, limit: int = 10) -> list[HashtagStats]:
        """Get trending hashtags.

        Args:
            limit: Maximum hashtags

        Returns:
            List of trending HashtagStats
        """
        self.update_hashtag_trending()

        trending = sorted(self.hashtag_stats.values(), key=lambda h: h.trending_score, reverse=True)

        return trending[:limit]

    def get_post_stats(self, post_id: UUID) -> PostStats | None:
        """Get statistics for a post.

        Args:
            post_id: Post ID

        Returns:
            PostStats or None if not found
        """
        return self.post_stats.get(post_id)

    def get_user_stats(self, user_id: UUID) -> UserStats | None:
        """Get statistics for a user.

        Args:
            user_id: User ID

        Returns:
            UserStats or None if not found
        """
        return self.user_stats.get(user_id)

    def calculate_dau(self, date: str | None = None) -> int:
        """Calculate daily active users.

        Args:
            date: Date string (YYYY-MM-DD), defaults to today

        Returns:
            Count of daily active users
        """
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        return len(self.daily_active_users.get(date, set()))

    def calculate_mau(self, month: str | None = None) -> int:
        """Calculate monthly active users.

        Args:
            month: Month string (YYYY-MM), defaults to current month

        Returns:
            Count of monthly active users
        """
        if month is None:
            month = datetime.utcnow().strftime("%Y-%m")

        return len(self.monthly_active_users.get(month, set()))

    def get_dau_mau_ratio(self) -> float:
        """Get DAU/MAU ratio.

        Returns:
            Ratio of daily to monthly active users
        """
        dau = self.calculate_dau()
        mau = self.calculate_mau()

        if mau == 0:
            return 0.0

        return dau / mau

    def calculate_retention_cohort(self, cohort_date: str, days_offset: int) -> float:
        """Calculate retention for cohort.

        Users who were active on cohort_date and still active days_offset later.

        Args:
            cohort_date: Start date (YYYY-MM-DD)
            days_offset: Days to measure retention

        Returns:
            Retention percentage (0-1)
        """
        cohort_users = self.daily_active_users.get(cohort_date, set())

        if not cohort_users:
            return 0.0

        target_date = (datetime.strptime(cohort_date, "%Y-%m-%d") + timedelta(days=days_offset)).strftime("%Y-%m-%d")

        retained_users = self.daily_active_users.get(target_date, set())
        retained = len(cohort_users & retained_users)

        return retained / len(cohort_users)

    def calculate_k_factor(self, user_id: UUID) -> float:
        """Calculate viral coefficient (K-factor) for user.

        K-factor = (invitations sent per user) * (conversion rate)

        Args:
            user_id: User ID

        Returns:
            K-factor value
        """
        if user_id not in self.user_stats:
            return 0.0

        stats = self.user_stats[user_id]

        # Simplified: K-factor based on follower growth rate
        # Real implementation would track invitations and conversions
        if stats.followers_gained_this_month > 0:
            # Estimate conversion rate (followers gained / reach)
            conversion_rate = min(1.0, stats.followers_gained_this_month / max(stats.reach_this_month, 1))
            k_factor = stats.followers_gained_this_month * conversion_rate
            return min(k_factor, 10.0)  # Cap at 10

        return 0.0

    def get_avg_session_duration(self, user_id: UUID) -> float | None:
        """Get average session duration for user in seconds.

        Args:
            user_id: User ID

        Returns:
            Average duration in seconds or None
        """
        sessions = self.session_data.get(user_id, [])

        if not sessions:
            return None

        total_duration = sum((end - start).total_seconds() for start, end in sessions)

        return total_duration / len(sessions)

    def aggregate_time_series(
        self, metric: str, bucket_hours: int = 24, days_back: int = 7
    ) -> list[tuple[datetime, float]]:
        """Aggregate metric by time bucket.

        Args:
            metric: Metric name (dau, mau, posts, etc.)
            bucket_hours: Bucket size in hours
            days_back: How many days back to aggregate

        Returns:
            List of (timestamp, value) tuples
        """
        now = datetime.utcnow()
        start = now - timedelta(days=days_back)

        buckets: dict[str, int] = defaultdict(int)
        current = start

        while current < now:
            bucket_time = current.replace(hour=0, minute=0, second=0, microsecond=0)

            if metric == "dau":
                date_str = bucket_time.strftime("%Y-%m-%d")
                buckets[date_str] = self.calculate_dau(date_str)
            elif metric == "posts":
                date_str = bucket_time.strftime("%Y-%m-%d")
                posts = sum(1 for stats in self.post_stats.values() if stats.created_at.date() == bucket_time.date())
                buckets[date_str] = posts

            current += timedelta(hours=bucket_hours)

        # Convert to list
        result = []
        for date_str, value in sorted(buckets.items()):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            result.append((dt, float(value)))

        return result

    def get_growth_metrics(self, days: int = 30) -> dict[str, float]:
        """Get platform growth metrics.

        Args:
            days: Number of days to measure

        Returns:
            Dictionary with growth metrics
        """
        now = datetime.utcnow()
        past = now - timedelta(days=days)

        new_users = sum(1 for user_id, stats in self.user_stats.items() if stats.updated_at > past)

        total_posts = sum(1 for _ in self.post_stats)

        new_posts = sum(1 for stats in self.post_stats.values() if stats.created_at > past)

        avg_engagement = sum(stats.engagement_rate for stats in self.post_stats.values()) / max(len(self.post_stats), 1)

        return {
            "new_users": new_users,
            "total_posts": total_posts,
            "new_posts_period": new_posts,
            "avg_engagement_rate": avg_engagement,
            "dau": self.calculate_dau(),
            "mau": self.calculate_mau(),
            "dau_mau_ratio": self.get_dau_mau_ratio(),
        }
