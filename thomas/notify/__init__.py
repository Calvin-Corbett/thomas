"""
Thomas Notification Module
A multi-channel notification and messaging platform supporting email, SMS, push,
in-app, Slack, and webhook channels with advanced features like templating,
routing, engagement tracking, and analytics.
"""

from thomas.notify._exceptions import (
    ChannelException,
    DeliveryException,
    NotifyException,
    PreferenceException,
    RoutingException,
    TemplateException,
)
from thomas.notify._types import (
    ABTest,
    Audience,
    Campaign,
    Category,
    Channel,
    ChannelType,
    ContentBlock,
    DeliveryResult,
    DeliveryStatus,
    Digest,
    EngagementMetric,
    Notification,
    NotificationPreference,
    Priority,
    Recipient,
    Schedule,
    Segment,
    Template,
)

__all__ = [
    "Notification",
    "Channel",
    "ChannelType",
    "Recipient",
    "Template",
    "DeliveryResult",
    "NotificationPreference",
    "Schedule",
    "Digest",
    "Campaign",
    "Audience",
    "Segment",
    "EngagementMetric",
    "ABTest",
    "ContentBlock",
    "Priority",
    "Category",
    "DeliveryStatus",
    "NotifyException",
    "ChannelException",
    "TemplateException",
    "RoutingException",
    "PreferenceException",
    "DeliveryException",
]

__version__ = "1.0.0"
