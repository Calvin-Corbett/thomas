"""
Core type definitions for the notification system.
Defines all data models used across the notification platform.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import uuid4


class ChannelType(str, Enum):
    """Supported notification channels."""

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"
    SLACK = "slack"
    WEBHOOK = "webhook"


# Backward-compatible alias retained for existing imports.
Channel = ChannelType


class DeliveryStatus(str, Enum):
    """Delivery status of a notification."""

    QUEUED = "queued"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"
    DEFERRED = "deferred"


class Priority(str, Enum):
    """Notification priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Category(str, Enum):
    """Notification categories for preference management."""

    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"
    SYSTEM = "system"
    SOCIAL = "social"
    SECURITY = "security"
    UPDATES = "updates"


class InAppType(str, Enum):
    """Types of in-app notifications."""

    BANNER = "banner"
    MODAL = "modal"
    TOAST = "toast"


@dataclass
class ContentBlock:
    """Content block for templated messages."""

    block_type: str  # "text", "image", "section", "divider"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "block_type": self.block_type,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass
class Recipient:
    """Recipient of a notification."""

    user_id: str
    email: str | None = None
    phone_number: str | None = None
    slack_user_id: str | None = None
    webhook_url: str | None = None
    timezone: str = "UTC"
    locale: str = "en_US"
    attributes: dict[str, Any] = field(default_factory=dict)

    def get_channel_address(self, channel_type: ChannelType) -> str | None:
        """Get the address for a specific channel."""
        mapping = {
            ChannelType.EMAIL: self.email,
            ChannelType.SMS: self.phone_number,
            ChannelType.SLACK: self.slack_user_id,
            ChannelType.WEBHOOK: self.webhook_url,
        }
        return mapping.get(channel_type)


@dataclass
class Template:
    """Notification template with variable substitution."""

    template_id: str
    name: str
    channel_type: ChannelType
    body: str
    subject: str = ""
    html_body: str | None = None
    plain_text_fallback: str | None = None
    blocks: list[ContentBlock] = field(default_factory=list)
    variables: set[str] = field(default_factory=set)
    version: int = 1
    locale: str = "en_US"
    base_template_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_required_variables(self) -> set[str]:
        """Extract required variables from template."""
        return self.variables


@dataclass
class Notification:
    """Core notification object."""

    recipient: Recipient
    template_id: str
    channel_type: ChannelType
    notification_id: str = field(default_factory=lambda: str(uuid4()))
    variables: dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    category: Category = Category.TRANSACTIONAL
    scheduled_at: datetime | None = None
    expires_at: datetime | None = None
    tags: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    attempt_count: int = 0
    max_attempts: int = 3

    def should_skip_quiet_hours(self) -> bool:
        """Check if notification should bypass quiet hours."""
        return self.priority in (Priority.HIGH, Priority.URGENT)

    def is_expired(self) -> bool:
        """Check if notification has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


@dataclass
class DeliveryResult:
    """Result of a delivery attempt."""

    notification_id: str
    recipient_id: str
    channel_type: ChannelType
    status: DeliveryStatus
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error_message: str | None = None
    delivery_time_ms: float | None = None
    bounce_type: str | None = None  # "hard", "soft"
    metadata: dict[str, Any] = field(default_factory=dict)

    def was_successful(self) -> bool:
        """Check if delivery was successful."""
        return self.status == DeliveryStatus.DELIVERED


@dataclass
class NotificationPreference:
    """User notification preferences."""

    user_id: str
    preferences: dict[Category, dict[ChannelType, bool]] = field(default_factory=dict)
    global_opt_out: bool = False
    quiet_hours_enabled: bool = True
    quiet_hours_start: str = "22:00"  # HH:MM format
    quiet_hours_end: str = "08:00"
    max_per_channel_per_day: dict[ChannelType, int] = field(default_factory=dict)
    preferred_channels: list[ChannelType] = field(default_factory=list)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_category_enabled(self, category: Category, channel: ChannelType) -> bool:
        """Check if a category is enabled for a channel."""
        if self.global_opt_out:
            return False
        if category not in self.preferences:
            return True
        if channel not in self.preferences[category]:
            return True
        return self.preferences[category][channel]

    def get_preferred_channels(self) -> list[ChannelType]:
        """Get preferred channels in priority order."""
        return self.preferred_channels or [
            ChannelType.PUSH,
            ChannelType.EMAIL,
            ChannelType.SMS,
        ]


@dataclass
class Schedule:
    """Notification schedule."""

    schedule_type: str  # "once", "daily", "weekly", "monthly"
    start_time: datetime
    end_time: datetime | None = None
    recurrence_rule: str | None = None  # RFC 5545 RRULE
    timezone: str = "UTC"

    def get_next_occurrence(self, from_time: datetime) -> datetime | None:
        """Calculate next occurrence time."""
        if self.schedule_type == "once":
            if from_time < self.start_time:
                return self.start_time
            return None
        return self.start_time


@dataclass
class Digest:
    """Notification digest configuration."""

    user_id: str
    frequency: str  # "daily", "weekly"
    digest_id: str = field(default_factory=lambda: str(uuid4()))
    preferred_time: str = "09:00"  # HH:MM format
    timezone: str = "UTC"
    categories: list[Category] = field(default_factory=list)
    channel_type: ChannelType = ChannelType.EMAIL
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)

    def is_time_to_send(self, current_time: datetime) -> bool:
        """Check if it's time to send digest."""
        return True  # Simplified; real implementation would check frequency/time


@dataclass
class Audience:
    """Target audience for a campaign."""

    name: str
    audience_id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    filters: list[dict[str, Any]] = field(default_factory=list)
    segment_ids: list[str] = field(default_factory=list)
    user_ids: set[str] | None = None
    size: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Segment:
    """User segment definition."""

    name: str
    segment_id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    user_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Campaign:
    """Notification campaign."""

    name: str
    template_id: str
    audience: Audience
    campaign_id: str = field(default_factory=lambda: str(uuid4()))
    description: str = ""
    channel_types: list[ChannelType] = field(default_factory=list)
    schedule: Schedule | None = None
    priority: Priority = Priority.NORMAL
    category: Category = Category.MARKETING
    ab_test: Optional["ABTest"] = None
    status: str = "draft"  # "draft", "scheduled", "running", "completed"
    sent_count: int = 0
    delivered_count: int = 0
    opened_count: int = 0
    clicked_count: int = 0
    converted_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def get_delivery_rate(self) -> float:
        """Calculate delivery rate."""
        if self.sent_count == 0:
            return 0.0
        return self.delivered_count / self.sent_count

    def get_engagement_rate(self) -> float:
        """Calculate engagement rate."""
        if self.delivered_count == 0:
            return 0.0
        return self.opened_count / self.delivered_count


@dataclass
class ABTest:
    """A/B test configuration."""

    control_template_id: str
    variant_template_id: str
    test_id: str = field(default_factory=lambda: str(uuid4()))
    split_percentage: float = 0.5
    metric: str = "open_rate"  # "open_rate", "click_rate", "conversion_rate"
    sample_size: int = 1000
    confidence_level: float = 0.95
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: datetime | None = None
    winner_template_id: str | None = None
    p_value: float | None = None
    is_significant: bool = False


@dataclass
class EngagementMetric:
    """Engagement metric for tracking."""

    notification_id: str
    user_id: str
    metric_type: str  # "open", "click", "conversion"
    metric_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    url_clicked: str | None = None
    time_to_action_seconds: int | None = None

    def is_engagement(self) -> bool:
        """Check if this represents actual engagement."""
        return self.metric_type in ("open", "click", "conversion")
