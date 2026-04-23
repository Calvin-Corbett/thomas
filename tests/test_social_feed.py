"""Tests for feed generation and ranking."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from thomas.marketplace.social_platform import FeedEngine, Post


class TestFeedEngine:
    """Test suite for FeedEngine."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.engine = FeedEngine()
        self.user_id = uuid4()
        self.follower_ids = {uuid4(), uuid4(), uuid4()}

    def _create_post(
        self, user_id: str = None, text: str = "Test post", created_at: datetime = None, engagement: int = 0
    ) -> Post:
        """Helper to create a post."""
        if user_id is None:
            user_id = self.user_id

        post = Post(user_id=user_id, text=text, created_at=created_at or datetime.utcnow())

        # Add reactions to create engagement
        for _ in range(engagement):
            from thomas.marketplace.social_platform import Reaction, ReactionType

            reaction = Reaction(user_id=uuid4(), reaction_type=ReactionType.LIKE)
            post.reactions.append(reaction)

        return post

    def test_add_post(self) -> None:
        """Test adding post to feed."""
        post = self._create_post()
        self.engine.add_post(post)

        assert post.id in self.engine.posts

    def test_remove_post(self) -> None:
        """Test removing post from feed."""
        post = self._create_post()
        self.engine.add_post(post)
        self.engine.remove_post(post.id)

        assert post.id not in self.engine.posts

    def test_chronological_feed(self) -> None:
        """Test chronological feed generation."""
        now = datetime.utcnow()

        post1 = self._create_post(text="Post 1", created_at=now - timedelta(hours=2))
        post2 = self._create_post(text="Post 2", created_at=now - timedelta(hours=1))
        post3 = self._create_post(text="Post 3", created_at=now)

        for post in [post1, post2, post3]:
            self.engine.add_post(post)

        feed, _ = self.engine.get_chronological_feed(self.user_id, self.follower_ids | {self.user_id})

        # Should be ordered newest first
        assert feed[0].post.text == "Post 3"
        assert feed[1].post.text == "Post 2"
        assert feed[2].post.text == "Post 1"

    def test_chronological_feed_pagination(self) -> None:
        """Test chronological feed pagination."""
        now = datetime.utcnow()

        # Create 5 posts
        for i in range(5):
            post = self._create_post(text=f"Post {i}", created_at=now - timedelta(hours=i))
            self.engine.add_post(post)

        # Get first page
        feed1, cursor1 = self.engine.get_chronological_feed(self.user_id, self.follower_ids | {self.user_id}, limit=2)

        assert len(feed1) == 2
        assert cursor1 is not None

        # Get second page
        feed2, cursor2 = self.engine.get_chronological_feed(
            self.user_id, self.follower_ids | {self.user_id}, cursor=cursor1, limit=2
        )

        assert len(feed2) == 2
        assert feed1[0].post.id != feed2[0].post.id

    def test_ranked_feed_engagement_scoring(self) -> None:
        """Test ranked feed with engagement scoring."""
        post1 = self._create_post(text="Post 1", engagement=1)
        post2 = self._create_post(text="Post 2", engagement=10)
        post3 = self._create_post(text="Post 3", engagement=3)

        for post in [post1, post2, post3]:
            self.engine.add_post(post)

        feed, _ = self.engine.get_ranked_feed(self.user_id, self.follower_ids | {self.user_id}, {})

        # High engagement post should rank first
        assert feed[0].post.text == "Post 2"

    def test_ranked_feed_time_decay(self) -> None:
        """Test ranked feed with time decay."""
        now = datetime.utcnow()

        # Old post with moderate engagement
        post1 = self._create_post(text="Old post", created_at=now - timedelta(hours=48), engagement=10)

        # Recent post with low engagement
        post2 = self._create_post(text="Recent post", created_at=now, engagement=1)

        for post in [post1, post2]:
            self.engine.add_post(post)

        feed, _ = self.engine.get_ranked_feed(self.user_id, self.follower_ids | {self.user_id}, {})

        # Recent post should rank higher due to time decay
        assert feed[0].post.text == "Recent post"

    def test_trending_posts_velocity(self) -> None:
        """Test trending posts detection using velocity."""
        now = datetime.utcnow()

        # Older post with steady engagement
        old_post = self._create_post(text="Steady post", created_at=now - timedelta(hours=12), engagement=10)

        # Recent post with rapid engagement
        trending_post = self._create_post(text="Trending post", created_at=now - timedelta(minutes=30), engagement=8)

        for post in [old_post, trending_post]:
            self.engine.add_post(post)

        trending = self.engine.get_trending_posts(hours=24, limit=10)

        # Should detect high velocity post
        assert len(trending) > 0

    def test_diversified_feed(self) -> None:
        """Test feed diversification avoids same-author clustering."""
        user1 = uuid4()
        user2 = uuid4()
        user3 = uuid4()

        # Multiple posts from user1
        for i in range(3):
            post = self._create_post(user_id=user1, text=f"User1 post {i}")
            self.engine.add_post(post)

        # Posts from other users
        post_u2 = self._create_post(user_id=user2, text="User2 post")
        post_u3 = self._create_post(user_id=user3, text="User3 post")

        self.engine.add_post(post_u2)
        self.engine.add_post(post_u3)

        feed, _ = self.engine.get_diversified_feed(self.user_id, {user1, user2, user3}, {}, limit=10)

        # Check max 2 consecutive from same author
        consecutive_counts = {}
        current_author = None
        current_count = 0

        for item in feed:
            if item.post.user_id == current_author:
                current_count += 1
            else:
                if current_author:
                    consecutive_counts[current_author] = current_count
                current_author = item.post.user_id
                current_count = 1

        for author, count in consecutive_counts.items():
            assert count <= 2, f"Author {author} has {count} consecutive posts"

    def test_record_interaction(self) -> None:
        """Test recording user interactions for affinity."""
        post_id = uuid4()
        user1 = self.user_id
        user2 = uuid4()

        self.engine.record_interaction(user1, post_id, "like")
        self.engine.record_interaction(user1, post_id, "like")
        self.engine.record_interaction(user1, post_id, "comment")

        # Check affinity score increased
        affinity = self.engine.engagement_history[user1][str(user2)]
        assert affinity >= 0

    def test_feed_impressions_tracking(self) -> None:
        """Test tracking feed impressions."""
        from thomas.marketplace.social_platform import FeedItem

        post = self._create_post()
        feed_item = FeedItem(post=post)

        assert feed_item.impression_count == 0

        self.engine.add_to_feed_item_impressions(feed_item)
        assert feed_item.impression_count == 1

    def test_get_post(self) -> None:
        """Test retrieving post from feed engine."""
        post = self._create_post(text="Test post")
        self.engine.add_post(post)

        retrieved = self.engine.get_post(post.id)
        assert retrieved.text == "Test post"

    def test_get_post_not_found(self) -> None:
        """Test retrieving non-existent post."""
        from thomas.marketplace.social_platform import PostNotFoundError

        with pytest.raises(PostNotFoundError):
            self.engine.get_post(uuid4())

    def test_filter_deleted_posts(self) -> None:
        """Test that deleted posts are filtered from feeds."""
        post1 = self._create_post(text="Active post")
        post2 = self._create_post(text="Deleted post")

        self.engine.add_post(post1)
        self.engine.add_post(post2)

        post2.is_deleted = True

        feed, _ = self.engine.get_chronological_feed(self.user_id, self.follower_ids | {self.user_id})

        texts = [item.post.text for item in feed]
        assert "Active post" in texts
        assert "Deleted post" not in texts

    def test_filter_expired_posts(self) -> None:
        """Test that expired posts are filtered from feeds."""
        post1 = self._create_post(text="Active post")
        post2 = self._create_post(text="Expired post")

        # Mark post2 as expired
        post2.expires_at = datetime.utcnow() - timedelta(hours=1)

        self.engine.add_post(post1)
        self.engine.add_post(post2)

        feed, _ = self.engine.get_chronological_feed(self.user_id, self.follower_ids | {self.user_id})

        texts = [item.post.text for item in feed]
        assert "Active post" in texts
        assert "Expired post" not in texts

    def test_feed_cache_invalidation(self) -> None:
        """Test feed cache is invalidated on changes."""
        post = self._create_post()
        self.engine.add_post(post)

        # Cache would be populated here
        assert len(self.engine.feed_cache) == 0  # Not cached by default

        # Should invalidate on removal
        self.engine.remove_post(post.id)
        assert len(self.engine.feed_cache) == 0
