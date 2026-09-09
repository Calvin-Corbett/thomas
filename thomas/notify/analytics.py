"""
Notification analytics system with funnel analysis, engagement metrics, and ROI calculations.
"""

from datetime import datetime, timedelta

from thomas.notify._exceptions import NotifyException
from thomas.notify._types import (
    Category,
    ChannelType,
)


class DeliveryFunnel:
    """Analyzes delivery funnel: sent → delivered → opened → clicked → converted."""

    def __init__(self) -> None:
        """Initialize delivery funnel."""
        self.funnel_data: dict[str, dict[str, int]] = {
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "converted": 0,
        }

    def add_sent(self, count: int = 1) -> None:
        """Record sent notifications.

        Args:
            count: Number of notifications sent
        """
        self.funnel_data["sent"] += count

    def add_delivered(self, count: int = 1) -> None:
        """Record delivered notifications.

        Args:
            count: Number of notifications delivered
        """
        self.funnel_data["delivered"] += count

    def add_opened(self, count: int = 1) -> None:
        """Record opened notifications.

        Args:
            count: Number of notifications opened
        """
        self.funnel_data["opened"] += count

    def add_clicked(self, count: int = 1) -> None:
        """Record clicked notifications.

        Args:
            count: Number of notifications clicked
        """
        self.funnel_data["clicked"] += count

    def add_converted(self, count: int = 1) -> None:
        """Record converted notifications.

        Args:
            count: Number of conversions
        """
        self.funnel_data["converted"] += count

    def get_funnel(self) -> dict[str, int]:
        """Get funnel data.

        Returns:
            Funnel stage counts
        """
        return self.funnel_data.copy()

    def get_conversion_rate(self) -> float:
        """Get overall conversion rate.

        Returns:
            Conversion rate (0-1)
        """
        if self.funnel_data["sent"] == 0:
            return 0.0

        return self.funnel_data["converted"] / self.funnel_data["sent"]

    def get_delivery_rate(self) -> float:
        """Get delivery rate.

        Returns:
            Delivery rate (0-1)
        """
        if self.funnel_data["sent"] == 0:
            return 0.0

        return self.funnel_data["delivered"] / self.funnel_data["sent"]

    def get_open_rate(self) -> float:
        """Get open rate (of delivered).

        Returns:
            Open rate (0-1)
        """
        if self.funnel_data["delivered"] == 0:
            return 0.0

        return self.funnel_data["opened"] / self.funnel_data["delivered"]

    def get_click_rate(self) -> float:
        """Get click rate (of opened).

        Returns:
            Click rate (0-1)
        """
        if self.funnel_data["opened"] == 0:
            return 0.0

        return self.funnel_data["clicked"] / self.funnel_data["opened"]


class ChannelComparison:
    """Compares engagement rates across channels."""

    def __init__(self) -> None:
        """Initialize channel comparison."""
        self.channel_metrics: dict[ChannelType, dict[str, int]] = {}

    def record_channel_metric(
        self,
        channel: ChannelType,
        metric_type: str,
        count: int = 1,
    ) -> None:
        """Record metric for channel.

        Args:
            channel: Channel type
            metric_type: Metric name (e.g., "sent", "opened", "clicked")
            count: Count
        """
        if channel not in self.channel_metrics:
            self.channel_metrics[channel] = {}

        if metric_type not in self.channel_metrics[channel]:
            self.channel_metrics[channel][metric_type] = 0

        self.channel_metrics[channel][metric_type] += count

    def get_channel_engagement_rate(self, channel: ChannelType) -> float:
        """Get engagement rate for channel.

        Args:
            channel: Channel type

        Returns:
            Engagement rate (0-1)
        """
        if channel not in self.channel_metrics:
            return 0.0

        metrics = self.channel_metrics[channel]

        sent = metrics.get("sent", 0)
        if sent == 0:
            return 0.0

        engaged = metrics.get("opened", 0) + metrics.get("clicked", 0)

        return engaged / sent

    def get_channel_conversion_rate(self, channel: ChannelType) -> float:
        """Get conversion rate for channel.

        Args:
            channel: Channel type

        Returns:
            Conversion rate (0-1)
        """
        if channel not in self.channel_metrics:
            return 0.0

        metrics = self.channel_metrics[channel]

        sent = metrics.get("sent", 0)
        if sent == 0:
            return 0.0

        converted = metrics.get("converted", 0)

        return converted / sent

    def compare_channels(
        self,
    ) -> dict[ChannelType, dict[str, float]]:
        """Compare all channels.

        Returns:
            Metrics for each channel
        """
        comparison = {}

        for channel in self.channel_metrics:
            comparison[channel] = {
                "engagement_rate": (self.get_channel_engagement_rate(channel)),
                "conversion_rate": (self.get_channel_conversion_rate(channel)),
            }

        return comparison


class CategoryPerformance:
    """Tracks performance by notification category."""

    def __init__(self) -> None:
        """Initialize category performance."""
        self.category_metrics: dict[Category, dict[str, int]] = {}

    def record_category_metric(
        self,
        category: Category,
        metric_type: str,
        count: int = 1,
    ) -> None:
        """Record metric for category.

        Args:
            category: Category
            metric_type: Metric name
            count: Count
        """
        if category not in self.category_metrics:
            self.category_metrics[category] = {}

        if metric_type not in self.category_metrics[category]:
            self.category_metrics[category][metric_type] = 0

        self.category_metrics[category][metric_type] += count

    def get_category_engagement_rate(self, category: Category) -> float:
        """Get engagement rate for category.

        Args:
            category: Category

        Returns:
            Engagement rate (0-1)
        """
        if category not in self.category_metrics:
            return 0.0

        metrics = self.category_metrics[category]

        sent = metrics.get("sent", 0)
        if sent == 0:
            return 0.0

        engaged = metrics.get("engaged", 0)

        return engaged / sent

    def get_top_categories(self, limit: int = 5) -> list[tuple[Category, float]]:
        """Get top categories by engagement.

        Args:
            limit: Number of categories to return

        Returns:
            List of (category, engagement_rate) tuples
        """
        rates = []

        for category in self.category_metrics:
            rate = self.get_category_engagement_rate(category)
            rates.append((category, rate))

        rates.sort(key=lambda x: x[1], reverse=True)

        return rates[:limit]


class TimeOfDayAnalysis:
    """Analyzes engagement by time of day."""

    def __init__(self) -> None:
        """Initialize time of day analysis."""
        self.hourly_metrics: dict[int, dict[str, int]] = {}

    def record_hourly_metric(
        self,
        hour: int,
        metric_type: str,
        count: int = 1,
    ) -> None:
        """Record metric for hour.

        Args:
            hour: Hour (0-23)
            metric_type: Metric name
            count: Count

        Raises:
            NotifyException: If invalid hour
        """
        if not (0 <= hour < 24):
            raise NotifyException(f"Invalid hour: {hour}")

        if hour not in self.hourly_metrics:
            self.hourly_metrics[hour] = {}

        if metric_type not in self.hourly_metrics[hour]:
            self.hourly_metrics[hour][metric_type] = 0

        self.hourly_metrics[hour][metric_type] += count

    def get_best_sending_hour(self) -> int | None:
        """Get hour with best engagement.

        Returns:
            Best hour (0-23) or None
        """
        if not self.hourly_metrics:
            return None

        best_hour = None
        best_rate = 0.0

        for hour, metrics in self.hourly_metrics.items():
            sent = metrics.get("sent", 0)
            if sent == 0:
                continue

            engaged = metrics.get("engaged", 0)
            rate = engaged / sent

            if rate > best_rate:
                best_rate = rate
                best_hour = hour

        return best_hour

    def get_hourly_performance(
        self,
    ) -> dict[int, dict[str, float]]:
        """Get performance metrics for each hour.

        Returns:
            Metrics by hour
        """
        performance = {}

        for hour, metrics in self.hourly_metrics.items():
            sent = metrics.get("sent", 0)

            if sent == 0:
                continue

            engaged = metrics.get("engaged", 0)
            performance[hour] = {
                "engagement_rate": engaged / sent,
                "sent": sent,
            }

        return performance


class NotificationFatigueDetector:
    """Detects notification fatigue from declining engagement."""

    def __init__(self, window_days: int = 7, fatigue_threshold: float = 0.2) -> None:
        """Initialize fatigue detector.

        Args:
            window_days: Rolling window in days
            fatigue_threshold: Decline threshold (e.g., 0.2 = 20% decline)
        """
        self.window_days = window_days
        self.fatigue_threshold = fatigue_threshold
        self.engagement_history: dict[str, list[tuple[datetime, float]]] = {}

    def record_engagement_rate(self, user_id: str, rate: float) -> None:
        """Record engagement rate for user.

        Args:
            user_id: User identifier
            rate: Engagement rate (0-1)
        """
        if user_id not in self.engagement_history:
            self.engagement_history[user_id] = []

        self.engagement_history[user_id].append((datetime.utcnow(), rate))

        # Keep only last N days
        cutoff = datetime.utcnow() - timedelta(days=self.window_days)
        self.engagement_history[user_id] = [(ts, r) for ts, r in self.engagement_history[user_id] if ts > cutoff]

    def is_fatigued(self, user_id: str) -> bool:
        """Check if user shows signs of fatigue.

        Args:
            user_id: User identifier

        Returns:
            True if user engagement declining
        """
        if user_id not in self.engagement_history:
            return False

        history = self.engagement_history[user_id]

        if len(history) < 2:
            return False

        # Compare recent vs older engagement
        mid_point = len(history) // 2

        old_rate = sum(r for _, r in history[:mid_point]) / max(mid_point, 1)

        new_rate = sum(r for _, r in history[mid_point:]) / max(len(history) - mid_point, 1)

        decline = old_rate - new_rate

        return decline > self.fatigue_threshold

    def get_fatigued_users(self, all_users: list[str]) -> list[str]:
        """Get users showing fatigue.

        Args:
            all_users: List of user IDs

        Returns:
            List of fatigued user IDs
        """
        fatigued = []

        for user_id in all_users:
            if self.is_fatigued(user_id):
                fatigued.append(user_id)

        return fatigued


class ROICalculator:
    """Calculates ROI for notification campaigns."""

    def __init__(self, cost_per_notification: float = 0.001) -> None:
        """Initialize ROI calculator.

        Args:
            cost_per_notification: Cost per notification in currency units
        """
        self.cost_per_notification = cost_per_notification
        self.campaign_conversions: dict[str, list[float]] = {}

    def record_conversion(self, campaign_id: str, revenue: float) -> None:
        """Record conversion for campaign.

        Args:
            campaign_id: Campaign identifier
            revenue: Revenue from conversion
        """
        if campaign_id not in self.campaign_conversions:
            self.campaign_conversions[campaign_id] = []

        self.campaign_conversions[campaign_id].append(revenue)

    def calculate_campaign_roi(self, campaign_id: str, sent_count: int) -> float:
        """Calculate ROI for campaign.

        Args:
            campaign_id: Campaign identifier
            sent_count: Number of notifications sent

        Returns:
            ROI percentage
        """
        cost = sent_count * self.cost_per_notification

        if cost == 0:
            return 0.0

        if campaign_id not in self.campaign_conversions:
            revenue = 0.0
        else:
            revenue = sum(self.campaign_conversions[campaign_id])

        return ((revenue - cost) / cost) * 100

    def get_average_revenue_per_notification(self, campaign_id: str, sent_count: int) -> float:
        """Calculate average revenue per notification.

        Args:
            campaign_id: Campaign identifier
            sent_count: Number sent

        Returns:
            Revenue per notification
        """
        if sent_count == 0:
            return 0.0

        if campaign_id not in self.campaign_conversions:
            total_revenue = 0.0
        else:
            total_revenue = sum(self.campaign_conversions[campaign_id])

        return total_revenue / sent_count


class CohortAnalysis:
    """Analyzes engagement by cohort (e.g., signup date)."""

    def __init__(self) -> None:
        """Initialize cohort analysis."""
        self.cohort_metrics: dict[str, dict[str, int]] = {}

    def record_cohort_metric(self, cohort_id: str, metric_type: str, count: int = 1) -> None:
        """Record metric for cohort.

        Args:
            cohort_id: Cohort identifier
            metric_type: Metric name
            count: Count
        """
        if cohort_id not in self.cohort_metrics:
            self.cohort_metrics[cohort_id] = {}

        if metric_type not in self.cohort_metrics[cohort_id]:
            self.cohort_metrics[cohort_id][metric_type] = 0

        self.cohort_metrics[cohort_id][metric_type] += count

    def get_cohort_engagement_rate(self, cohort_id: str) -> float:
        """Get engagement rate for cohort.

        Args:
            cohort_id: Cohort identifier

        Returns:
            Engagement rate (0-1)
        """
        if cohort_id not in self.cohort_metrics:
            return 0.0

        metrics = self.cohort_metrics[cohort_id]

        sent = metrics.get("sent", 0)
        if sent == 0:
            return 0.0

        engaged = metrics.get("engaged", 0)

        return engaged / sent

    def get_cohort_retention(self, cohort_id: str) -> float:
        """Get retention rate for cohort.

        Args:
            cohort_id: Cohort identifier

        Returns:
            Retention rate (0-1)
        """
        if cohort_id not in self.cohort_metrics:
            return 0.0

        metrics = self.cohort_metrics[cohort_id]

        acquired = metrics.get("acquired", 1)
        retained = metrics.get("retained", 0)

        return retained / acquired if acquired > 0 else 0.0
