"""Feed generation and ranking algorithms.

This module implements feed algorithms including chronological, ranked feeds
with engagement-based scoring, time decay, affinity scoring, and trending
content detection using velocity-based z-score.
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from ._exceptions import PostNotFoundError
from ._types import FeedItem, Post


class FeedEngine:
    """Generates ranked and chronological feeds with caching.

    Attributes:
        posts: Dictionary mapping post_id to Post objects
        feed_cache: Cache for computed feeds per user
        engagement_history: Track user interactions for affinity
        trending_cache: Cache for trending posts
    """

    # Engagement scoring weights
    LIKE_WEIGHT = 1
    COMMENT_WEIGHT = 3
    SHARE_WEIGHT = 5

    # Time decay half-life in hours
    TIME_DECAY_HALF_LIFE = 24

    def __init__(self) -> None:
        """Initialize feed engine."""
        self.posts: dict[UUID, Post] = {}
        self.feed_cache: dict[UUID, list[FeedItem]] = {}
        self.engagement_history: dict[UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.trending_cache: list[Post] = []
        self.trending_cache_time: datetime | None = None

    def add_post(self, post: Post) -> None:
        """Add post to feed engine.

        Args:
            post: Post object to add
        """
        self.posts[post.id] = post
        self._invalidate_cache()

    def remove_post(self, post_id: UUID) -> None:
        """Remove post from feed engine.

        Args:
            post_id: ID of post to remove
        """
        if post_id in self.posts:
            del self.posts[post_id]
            self._invalidate_cache()

    def get_chronological_feed(
        self, user_id: UUID, following_ids: set[UUID], cursor: str | None = None, limit: int = 20
    ) -> tuple[list[FeedItem], str | None]:
        """Get chronological feed for user.

        Posts ordered by creation time, newest first.

        Args:
            user_id: User requesting feed
            following_ids: Set of user IDs user is following
            cursor: Pagination cursor
            limit: Maximum items to return

        Returns:
            Tuple of (feed items, next cursor)
        """
        # Get posts from followed users and user's own posts
        relevant_posts = [
            post
            for post in self.posts.values()
            if post.user_id in following_ids or post.user_id == user_id
            if not post.is_deleted
            if post.expires_at is None or post.expires_at > datetime.utcnow()
        ]

        # Sort by creation time (newest first)
        relevant_posts.sort(key=lambda p: p.created_at, reverse=True)

        # Handle pagination
        start_idx = 0
        if cursor:
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                start_idx = 0

        end_idx = start_idx + limit
        paginated_posts = relevant_posts[start_idx:end_idx]

        # Convert to feed items
        feed_items = [FeedItem(post=post, reason="Following") for post in paginated_posts]

        # Generate next cursor
        next_cursor = str(end_idx) if end_idx < len(relevant_posts) else None

        return feed_items, next_cursor

    def get_ranked_feed(
        self,
        user_id: UUID,
        following_ids: set[UUID],
        user_interactions: dict[UUID, str],
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[FeedItem], str | None]:
        """Get ranked feed using engagement scoring and time decay.

        Ranking formula: score = engagement_score * time_decay * affinity_score

        Args:
            user_id: User requesting feed
            following_ids: Set of user IDs user is following
            user_interactions: Dict mapping post_id to interaction type
            cursor: Pagination cursor
            limit: Maximum items to return

        Returns:
            Tuple of (feed items, next cursor)
        """
        # Get relevant posts
        relevant_posts = [
            post
            for post in self.posts.values()
            if post.user_id in following_ids or post.user_id == user_id
            if not post.is_deleted
            if post.expires_at is None or post.expires_at > datetime.utcnow()
        ]

        # Score each post
        scored_posts = []
        for post in relevant_posts:
            score = self._calculate_post_score(post, user_id, user_interactions)
            scored_posts.append((post, score))

        # Sort by score (highest first)
        scored_posts.sort(key=lambda x: x[1], reverse=True)

        # Handle pagination
        start_idx = 0
        if cursor:
            try:
                start_idx = int(cursor)
            except (ValueError, TypeError):
                start_idx = 0

        end_idx = start_idx + limit
        paginated = scored_posts[start_idx:end_idx]

        # Convert to feed items
        feed_items = [FeedItem(post=post, score=score, reason="Ranked") for post, score in paginated]

        next_cursor = str(end_idx) if end_idx < len(scored_posts) else None

        return feed_items, next_cursor

    def _calculate_post_score(self, post: Post, user_id: UUID, user_interactions: dict[UUID, str]) -> float:
        """Calculate engagement score for a post.

        Args:
            post: Post to score
            user_id: User for affinity calculation
            user_interactions: User's interaction history

        Returns:
            Weighted engagement score
        """
        # Engagement score
        engagement_score = (
            len(post.reactions) * self.LIKE_WEIGHT
            + len(post.comments) * self.COMMENT_WEIGHT
            + post.share_count * self.SHARE_WEIGHT
        )

        # Time decay (exponential decay with half-life)
        time_diff = (datetime.utcnow() - post.created_at).total_seconds()
        time_diff_hours = time_diff / 3600
        time_decay = math.exp(-math.log(2) * time_diff_hours / self.TIME_DECAY_HALF_LIFE)

        # Affinity score (based on interaction history)
        affinity_score = self._calculate_affinity_score(post.user_id, user_id, user_interactions)

        return engagement_score * time_decay * affinity_score

    def _calculate_affinity_score(self, author_id: UUID, user_id: UUID, user_interactions: dict[UUID, str]) -> float:
        """Calculate affinity score between user and author.

        Higher score if user frequently interacts with author's posts.

        Args:
            author_id: Post author ID
            user_id: Viewing user ID
            user_interactions: User's interaction history

        Returns:
            Affinity score (0.1 to 1.0)
        """
        if author_id == user_id:
            return 1.0

        interactions = self.engagement_history[user_id].get(str(author_id), 0)
        # Logarithmic scaling for affinity
        return 0.1 + 0.9 * math.log1p(interactions) / math.log(100)

    def get_trending_posts(self, hours: int = 24, limit: int = 10) -> list[Post]:
        """Get trending posts using velocity-based z-score.

        Trending = posts with high velocity (recent engagement growth).
        Uses z-score to detect statistical outliers.

        Args:
            hours: Time window for trending detection
            limit: Maximum trending posts

        Returns:
            List of trending Post objects
        """
        # Check cache
        if self.trending_cache_time and (datetime.utcnow() - self.trending_cache_time).seconds < 300:
            return self.trending_cache[:limit]

        # Calculate engagement velocity for posts in time window
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        recent_posts = [post for post in self.posts.values() if post.created_at > cutoff_time and not post.is_deleted]

        if not recent_posts:
            return []

        # Calculate velocity (engagement per hour since creation)
        velocities = []
        for post in recent_posts:
            hours_old = (datetime.utcnow() - post.created_at).total_seconds() / 3600
            if hours_old > 0:
                engagement = len(post.reactions) + len(post.comments) * 2 + post.share_count * 3
                velocity = engagement / hours_old
                velocities.append((post, velocity))

        # Calculate z-scores
        if not velocities:
            return []

        velocities_only = [v[1] for v in velocities]
        mean = sum(velocities_only) / len(velocities_only)
        variance = sum((v - mean) ** 2 for v in velocities_only) / len(velocities_only)
        stddev = math.sqrt(variance)

        if stddev == 0:
            return []

        # Filter by z-score > 1.5 (above average)
        trending = [post for post, velocity in velocities if (velocity - mean) / stddev > 1.5]

        # Sort by velocity
        trending.sort(
            key=lambda p: (len(p.reactions) + len(p.comments) * 2 + p.share_count * 3)
            / max(1, (datetime.utcnow() - p.created_at).total_seconds() / 3600),
            reverse=True,
        )

        self.trending_cache = trending
        self.trending_cache_time = datetime.utcnow()

        return trending[:limit]

    def get_diversified_feed(
        self,
        user_id: UUID,
        following_ids: set[UUID],
        user_interactions: dict[UUID, str],
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[FeedItem], str | None]:
        """Get diversified ranked feed avoiding same-author clustering.

        Args:
            user_id: User requesting feed
            following_ids: Set of user IDs user is following
            user_interactions: User's interaction history
            cursor: Pagination cursor
            limit: Maximum items to return

        Returns:
            Tuple of (feed items, next cursor)
        """
        feed_items, _ = self.get_ranked_feed(
            user_id,
            following_ids,
            user_interactions,
            cursor=None,
            limit=limit * 2,  # Get more to diversify
        )

        # Diversify: no more than 2 consecutive posts from same author
        diversified = []
        author_counts = defaultdict(int)

        for item in feed_items:
            author_id = item.post.user_id
            if author_counts[author_id] < 2:
                diversified.append(item)
                author_counts[author_id] += 1

            if len(diversified) >= limit:
                break

        # Generate cursor
        next_cursor = str(len(diversified)) if len(diversified) >= limit else None

        return diversified, next_cursor

    def record_interaction(self, user_id: UUID, post_id: UUID, interaction_type: str) -> None:
        """Record user interaction with post for affinity calculation.

        Args:
            user_id: User ID
            post_id: Post ID
            interaction_type: Type of interaction (like, comment, share)
        """
        post = self.posts.get(post_id)
        if post:
            self.engagement_history[user_id][str(post.user_id)] += 1

    def _invalidate_cache(self) -> None:
        """Invalidate feed cache."""
        self.feed_cache.clear()
        self.trending_cache_time = None

    def add_to_feed_item_impressions(self, feed_item: FeedItem) -> None:
        """Record impression for analytics.

        Args:
            feed_item: Feed item shown
        """
        feed_item.impression_count += 1

    def add_to_feed_item_clicks(self, feed_item: FeedItem) -> None:
        """Record click for analytics.

        Args:
            feed_item: Feed item clicked
        """
        feed_item.click_count += 1

    def get_post(self, post_id: UUID) -> Post:
        """Get post by ID.

        Args:
            post_id: Post ID

        Returns:
            Post object

        Raises:
            PostNotFoundError: If post not found
        """
        if post_id not in self.posts:
            raise PostNotFoundError(f"Post {post_id} not found")
        return self.posts[post_id]
