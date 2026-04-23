"""
Engagement tracking and metrics system.
Tracks opens, clicks, conversions, and calculates engagement scores.
"""

from datetime import datetime, timedelta

from thomas.notify._types import (
    EngagementMetric,
)


class EngagementTracker:
    """Tracks engagement events for notifications."""

    # Engagement score weights
    OPEN_WEIGHT = 1
    CLICK_WEIGHT = 3
    CONVERSION_WEIGHT = 5

    def __init__(self) -> None:
        """Initialize engagement tracker."""
        self.metrics: dict[str, list[EngagementMetric]] = {}
        self.user_open_times: dict[str, list[datetime]] = {}

    def record_open(
        self,
        notification_id: str,
        user_id: str,
    ) -> EngagementMetric:
        """Record notification open event.

        Args:
            notification_id: Notification identifier
            user_id: User identifier

        Returns:
            Recorded metric
        """
        metric = EngagementMetric(
            notification_id=notification_id,
            user_id=user_id,
            metric_type="open",
        )

        self._store_metric(metric)

        if user_id not in self.user_open_times:
            self.user_open_times[user_id] = []

        self.user_open_times[user_id].append(metric.timestamp)

        return metric

    def record_click(
        self,
        notification_id: str,
        user_id: str,
        url: str | None = None,
    ) -> EngagementMetric:
        """Record notification click event.

        Args:
            notification_id: Notification identifier
            user_id: User identifier
            url: Clicked URL

        Returns:
            Recorded metric
        """
        metric = EngagementMetric(
            notification_id=notification_id,
            user_id=user_id,
            metric_type="click",
            url_clicked=url,
        )

        self._store_metric(metric)

        return metric

    def record_conversion(
        self,
        notification_id: str,
        user_id: str,
        conversion_value: float | None = None,
    ) -> EngagementMetric:
        """Record conversion event.

        Args:
            notification_id: Notification identifier
            user_id: User identifier
            conversion_value: Monetary value of conversion

        Returns:
            Recorded metric
        """
        metric = EngagementMetric(
            notification_id=notification_id,
            user_id=user_id,
            metric_type="conversion",
            metadata={"value": conversion_value} if conversion_value else {},
        )

        self._store_metric(metric)

        return metric

    def get_metrics(self, notification_id: str) -> list[EngagementMetric]:
        """Get all metrics for a notification.

        Args:
            notification_id: Notification identifier

        Returns:
            List of engagement metrics
        """
        return self.metrics.get(notification_id, [])

    def calculate_engagement_score(self, notification_id: str) -> float:
        """Calculate engagement score for notification.

        Args:
            notification_id: Notification identifier

        Returns:
            Engagement score (weighted sum)
        """
        metrics = self.get_metrics(notification_id)

        score = 0.0
        for metric in metrics:
            if metric.metric_type == "open":
                score += self.OPEN_WEIGHT
            elif metric.metric_type == "click":
                score += self.CLICK_WEIGHT
            elif metric.metric_type == "conversion":
                score += self.CONVERSION_WEIGHT

        return score

    def get_user_engagement_score(self, user_id: str) -> float:
        """Calculate aggregate engagement score for user.

        Args:
            user_id: User identifier

        Returns:
            Total engagement score
        """
        score = 0.0

        for metrics in self.metrics.values():
            for metric in metrics:
                if metric.user_id != user_id:
                    continue

                if metric.metric_type == "open":
                    score += self.OPEN_WEIGHT
                elif metric.metric_type == "click":
                    score += self.CLICK_WEIGHT
                elif metric.metric_type == "conversion":
                    score += self.CONVERSION_WEIGHT

        return score

    def get_engagement_funnel(self, notification_id: str) -> dict[str, int]:
        """Get engagement funnel for notification.

        Args:
            notification_id: Notification identifier

        Returns:
            Counts at each stage: sent, delivered, opened, clicked
        """
        metrics = self.get_metrics(notification_id)

        funnel = {
            "sent": 1,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
        }

        unique_users = set()

        for metric in metrics:
            unique_users.add(metric.user_id)

            if metric.metric_type == "open":
                funnel["opened"] += 1
            elif metric.metric_type == "click":
                funnel["clicked"] += 1

        funnel["delivered"] = len(unique_users)

        return funnel

    def _store_metric(self, metric: EngagementMetric) -> None:
        """Store engagement metric.

        Args:
            metric: Metric to store
        """
        notification_id = metric.notification_id

        if notification_id not in self.metrics:
            self.metrics[notification_id] = []

        self.metrics[notification_id].append(metric)


class OptimalSendTimePredictor:
    """Predicts optimal send time based on engagement history."""

    def __init__(self) -> None:
        """Initialize send time predictor."""
        self.user_open_patterns: dict[str, list[int]] = {}

    def record_open_time(self, user_id: str, open_time: datetime) -> None:
        """Record when user opened a notification.

        Args:
            user_id: User identifier
            open_time: Time of open event
        """
        if user_id not in self.user_open_patterns:
            self.user_open_patterns[user_id] = []

        hour = open_time.hour
        self.user_open_patterns[user_id].append(hour)

    def get_optimal_send_hour(self, user_id: str) -> int | None:
        """Get optimal send hour for user.

        Args:
            user_id: User identifier

        Returns:
            Optimal hour (0-23) or None if insufficient data
        """
        if user_id not in self.user_open_patterns:
            return None

        hours = self.user_open_patterns[user_id]

        if len(hours) < 5:
            return None

        # Calculate hour with most opens
        hour_counts: dict[int, int] = {}
        for hour in hours:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        if not hour_counts:
            return None

        best_hour = max(hour_counts, key=hour_counts.get)

        return best_hour

    def get_engagement_by_hour(self, user_id: str) -> dict[int, int]:
        """Get engagement distribution by hour of day.

        Args:
            user_id: User identifier

        Returns:
            Engagement count by hour
        """
        if user_id not in self.user_open_patterns:
            return {}

        hours = self.user_open_patterns[user_id]

        hour_counts: dict[int, int] = {}
        for hour in hours:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        return hour_counts


class ReEngagementCampaignManager:
    """Identifies and targets inactive users for re-engagement."""

    def __init__(self, inactivity_days: int = 30) -> None:
        """Initialize re-engagement manager.

        Args:
            inactivity_days: Days without engagement to mark inactive
        """
        self.inactivity_days = inactivity_days
        self.user_last_engagement: dict[str, datetime] = {}

    def record_engagement(self, user_id: str, engagement_time: datetime) -> None:
        """Record engagement event for user.

        Args:
            user_id: User identifier
            engagement_time: Time of engagement
        """
        self.user_last_engagement[user_id] = engagement_time

    def is_inactive(self, user_id: str) -> bool:
        """Check if user is inactive.

        Args:
            user_id: User identifier

        Returns:
            True if user has not engaged in threshold period
        """
        if user_id not in self.user_last_engagement:
            return True

        last_engagement = self.user_last_engagement[user_id]
        threshold = datetime.utcnow() - timedelta(days=self.inactivity_days)

        return last_engagement < threshold

    def get_inactive_users(self, all_users: list[str]) -> list[str]:
        """Get list of inactive users.

        Args:
            all_users: List of all user IDs

        Returns:
            List of inactive user IDs
        """
        inactive = []

        for user_id in all_users:
            if self.is_inactive(user_id):
                inactive.append(user_id)

        return inactive

    def get_days_since_engagement(self, user_id: str) -> int | None:
        """Get days since last engagement.

        Args:
            user_id: User identifier

        Returns:
            Days since engagement or None if no engagement
        """
        if user_id not in self.user_last_engagement:
            return None

        last_engagement = self.user_last_engagement[user_id]
        days = (datetime.utcnow() - last_engagement).days

        return days
