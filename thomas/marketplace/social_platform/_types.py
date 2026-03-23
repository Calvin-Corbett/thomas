"""Type definitions for the social platform.

This module contains all data structures, enums, and type definitions
used throughout the social platform.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4


class UserRole(Enum):
    """User role enumeration."""

    STANDARD = "standard"
    VERIFIED = "verified"
    MODERATOR = "moderator"
    ADMIN = "admin"


class PrivacySetting(Enum):
    """Privacy level enumeration."""

    PUBLIC = "public"
    FRIENDS_ONLY = "friends_only"
    PRIVATE = "private"
    CUSTOM = "custom"


class AccountStatus(Enum):
    """Account status enumeration."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    DELETED = "deleted"


class ModerationAction(Enum):
    """Moderation action types."""

    WARNING = "warning"
    MUTE = "mute"
    SUPPRESS = "suppress"
    REMOVE = "remove"
    BAN = "ban"


class NotificationType(Enum):
    """Notification type enumeration."""

    LIKE = "like"
    COMMENT = "comment"
    FOLLOW = "follow"
    MENTION = "mention"
    DIRECT_MESSAGE = "direct_message"
    REPOST = "repost"
    SYSTEM = "system"
    QUOTE = "quote"


class ContentType(Enum):
    """Content type enumeration."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    LINK = "link"
    MIXED = "mixed"


class ReactionType(Enum):
    """Emoji reaction types."""

    LIKE = "like"
    LOVE = "love"
    HAHA = "haha"
    WOW = "wow"
    SAD = "sad"
    ANGRY = "angry"


@dataclass
class Media:
    """Media attachment representation."""

    id: UUID = field(default_factory=uuid4)
    url: str = ""
    media_type: ContentType = ContentType.IMAGE
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    alt_text: str | None = None
    uploaded_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0


@dataclass
class Hashtag:
    """Hashtag representation."""

    id: UUID = field(default_factory=uuid4)
    tag: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    usage_count: int = 0
    trending_score: float = 0.0


@dataclass
class Mention:
    """User mention in content."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    username: str = ""
    position: int = 0  # Position in text where mention starts


@dataclass
class Reaction:
    """User reaction to content."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    content_id: UUID = field(default_factory=uuid4)
    reaction_type: ReactionType = ReactionType.LIKE
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Comment:
    """Comment on a post."""

    id: UUID = field(default_factory=uuid4)
    post_id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    text: str = ""
    mentions: list[Mention] = field(default_factory=list)
    hashtags: list[Hashtag] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    reply_to_comment_id: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    edited_at: datetime | None = None
    is_deleted: bool = False


@dataclass
class Post:
    """Social media post."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    text: str = ""
    media: list[Media] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    hashtags: list[Hashtag] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    reply_to_post_id: UUID | None = None
    repost_of_id: UUID | None = None
    quote_of_id: UUID | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    edited_at: datetime | None = None
    expires_at: datetime | None = None
    is_pinned: bool = False
    visibility: PrivacySetting = PrivacySetting.PUBLIC
    is_deleted: bool = False
    share_count: int = 0
    edit_history: list[tuple[datetime, str]] = field(default_factory=list)


@dataclass
class Follow:
    """Follow relationship."""

    id: UUID = field(default_factory=uuid4)
    follower_id: UUID = field(default_factory=uuid4)
    following_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_muted: bool = False
    is_close_friend: bool = False


@dataclass
class Block:
    """Block relationship."""

    id: UUID = field(default_factory=uuid4)
    blocker_id: UUID = field(default_factory=uuid4)
    blocked_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    reason: str | None = None


@dataclass
class Report:
    """Content or user report."""

    id: UUID = field(default_factory=uuid4)
    reporter_id: UUID = field(default_factory=uuid4)
    reported_user_id: UUID | None = None
    reported_content_id: UUID | None = None
    reason: str = ""
    details: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"  # pending, reviewing, resolved, dismissed
    action_taken: ModerationAction | None = None
    moderator_notes: str | None = None


@dataclass
class DirectMessage:
    """Direct message."""

    id: UUID = field(default_factory=uuid4)
    conversation_id: UUID = field(default_factory=uuid4)
    sender_id: UUID = field(default_factory=uuid4)
    text: str = ""
    media: list[Media] = field(default_factory=list)
    reactions: list[Reaction] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    edited_at: datetime | None = None
    is_deleted: bool = False
    read_at: datetime | None = None


@dataclass
class Conversation:
    """Direct message conversation."""

    id: UUID = field(default_factory=uuid4)
    participant_ids: set[UUID] = field(default_factory=set)
    messages: list[DirectMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_message_at: datetime | None = None
    is_group: bool = False
    name: str | None = None


@dataclass
class Notification:
    """User notification."""

    id: UUID = field(default_factory=uuid4)
    user_id: UUID = field(default_factory=uuid4)
    type: NotificationType = NotificationType.SYSTEM
    actor_ids: list[UUID] = field(default_factory=list)
    content_id: UUID | None = None
    title: str = ""
    body: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    read_at: datetime | None = None
    action_url: str | None = None


@dataclass
class FeedItem:
    """Feed item with engagement metadata."""

    post: Post
    score: float = 0.0  # Ranking score
    reason: str = ""  # Why included (trending, follow, etc.)
    is_pinned: bool = False
    impression_count: int = 0
    click_count: int = 0


@dataclass
class User:
    """User account."""

    id: UUID = field(default_factory=uuid4)
    username: str = ""
    email: str = ""
    password_hash: str = ""
    display_name: str = ""
    bio: str = ""
    profile_picture_url: str | None = None
    header_image_url: str | None = None
    location: str | None = None
    website: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_active_at: datetime = field(default_factory=datetime.utcnow)
    role: UserRole = UserRole.STANDARD
    status: AccountStatus = AccountStatus.ACTIVE
    followers: dict[UUID, Follow] = field(default_factory=dict)  # follower_id -> Follow
    following: dict[UUID, Follow] = field(default_factory=dict)  # following_id -> Follow
    blocked_users: dict[UUID, Block] = field(default_factory=dict)
    blocking_users: dict[UUID, Block] = field(default_factory=dict)
    privacy_setting: PrivacySetting = PrivacySetting.PUBLIC
    is_verified: bool = False
    post_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    notification_preferences: dict[NotificationType, bool] = field(
        default_factory=lambda: {nt: True for nt in NotificationType}
    )
    muted_users: set[UUID] = field(default_factory=set)
    muted_hashtags: set[str] = field(default_factory=set)


@dataclass
class ContentPolicy:
    """Content policy for moderation."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    severity: int = 0  # 1-10, higher = more severe
    action: ModerationAction = ModerationAction.WARNING
    created_at: datetime = field(default_factory=datetime.utcnow)
    enabled: bool = True


@dataclass
class ModerationLog:
    """Moderation action log."""

    id: UUID = field(default_factory=uuid4)
    moderator_id: UUID = field(default_factory=uuid4)
    target_user_id: UUID | None = None
    target_content_id: UUID | None = None
    action: ModerationAction = ModerationAction.WARNING
    reason: str = ""
    duration_hours: int | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    appeal_deadline: datetime | None = None


@dataclass
class UserStats:
    """User engagement statistics."""

    user_id: UUID = field(default_factory=uuid4)
    total_posts: int = 0
    total_reactions: int = 0
    total_comments_received: int = 0
    total_comments_made: int = 0
    avg_engagement_per_post: float = 0.0
    posts_this_month: int = 0
    followers_gained_this_month: int = 0
    reach_this_month: int = 0
    impressions_this_month: int = 0
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class PostStats:
    """Post engagement statistics."""

    post_id: UUID = field(default_factory=uuid4)
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    reach: int = 0
    impressions: int = 0
    engagement_rate: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HashtagStats:
    """Hashtag statistics."""

    hashtag: str = ""
    usage_count: int = 0
    unique_users: int = 0
    posts_count: int = 0
    trending_rank: int | None = None
    trending_score: float = 0.0
    updated_at: datetime = field(default_factory=datetime.utcnow)
