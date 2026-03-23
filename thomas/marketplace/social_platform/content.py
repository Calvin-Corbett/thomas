"""Content management and post operations.

This module handles post creation, editing, mentions/hashtags extraction,
content threading, reposts/quotes, content expiry, search with inverted index,
and rich text parsing.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from ._exceptions import (
    CommentNotFoundError,
    ContentTooLongError,
    PostNotFoundError,
)
from ._types import Comment, Hashtag, Media, Mention, Post, PrivacySetting


class ContentManager:
    """Manages post creation, editing, and discovery.

    Attributes:
        posts: Dictionary mapping post_id to Post objects
        comments: Dictionary mapping comment_id to Comment objects
        inverted_index: Index for full-text search
        post_versions: Track edit history for posts
    """

    # Content limits
    MAX_POST_LENGTH = 5000
    MAX_COMMENT_LENGTH = 1000
    MAX_HASHTAGS = 30
    MAX_MENTIONS = 50

    def __init__(self) -> None:
        """Initialize content manager."""
        self.posts: dict[UUID, Post] = {}
        self.comments: dict[UUID, Comment] = {}
        self.inverted_index: dict[str, set[UUID]] = defaultdict(set)
        self.post_versions: dict[UUID, list[tuple[datetime, str]]] = defaultdict(list)
        self.hashtag_index: dict[str, list[UUID]] = defaultdict(list)

    def create_post(
        self,
        user_id: UUID,
        text: str,
        media: list[Media] | None = None,
        visibility: PrivacySetting = PrivacySetting.PUBLIC,
        reply_to_post_id: UUID | None = None,
        repost_of_id: UUID | None = None,
        quote_of_id: UUID | None = None,
        expires_in_hours: int | None = None,
    ) -> Post:
        """Create a new post.

        Args:
            user_id: Author user ID
            text: Post text content
            media: List of Media objects
            visibility: Post visibility setting
            reply_to_post_id: ID of post being replied to
            repost_of_id: ID of post being reposted
            quote_of_id: ID of post being quoted
            expires_in_hours: Hours until post expires (None for permanent)

        Returns:
            Created Post object

        Raises:
            ContentTooLongError: If text exceeds limit
            InvalidMediaError: If media is invalid
        """
        if not text.strip():
            raise ValueError("Post text cannot be empty")

        if len(text) > self.MAX_POST_LENGTH:
            raise ContentTooLongError(f"Post must be {self.MAX_POST_LENGTH} characters or less")

        # Extract mentions and hashtags
        mentions = self._extract_mentions(text)
        hashtags = self._extract_hashtags(text)

        if len(mentions) > self.MAX_MENTIONS:
            raise ValueError(f"Cannot mention more than {self.MAX_MENTIONS} users")

        if len(hashtags) > self.MAX_HASHTAGS:
            raise ValueError(f"Cannot include more than {self.MAX_HASHTAGS} hashtags")

        post = Post(
            user_id=user_id,
            text=text,
            media=media or [],
            mentions=mentions,
            hashtags=hashtags,
            visibility=visibility,
            reply_to_post_id=reply_to_post_id,
            repost_of_id=repost_of_id,
            quote_of_id=quote_of_id,
            created_at=datetime.utcnow(),
        )

        if expires_in_hours:
            post.expires_at = datetime.utcnow() + timedelta(hours=expires_in_hours)

        self.posts[post.id] = post
        self._index_post(post)

        return post

    def _extract_mentions(self, text: str) -> list[Mention]:
        """Extract @mentions from text using regex.

        Args:
            text: Text to parse

        Returns:
            List of Mention objects
        """
        mentions = []
        # Match @username (alphanumeric, underscore, hyphen)
        pattern = r"@([a-zA-Z0-9_-]+)"
        for match in re.finditer(pattern, text):
            mention = Mention(username=match.group(1), position=match.start())
            mentions.append(mention)
        return mentions[: self.MAX_MENTIONS]

    def _extract_hashtags(self, text: str) -> list[Hashtag]:
        """Extract #hashtags from text using regex.

        Args:
            text: Text to parse

        Returns:
            List of Hashtag objects
        """
        hashtags = []
        # Match #hashtag (alphanumeric, underscore)
        pattern = r"#([a-zA-Z0-9_]+)"
        seen = set()
        for match in re.finditer(pattern, text):
            tag = match.group(1).lower()
            if tag not in seen:
                hashtag = Hashtag(tag=tag, created_at=datetime.utcnow())
                hashtags.append(hashtag)
                seen.add(tag)
        return hashtags[: self.MAX_HASHTAGS]

    def edit_post(self, post_id: UUID, user_id: UUID, new_text: str) -> Post:
        """Edit a post.

        Args:
            post_id: Post ID to edit
            user_id: User ID making edit
            new_text: New post text

        Returns:
            Updated Post object

        Raises:
            PostNotFoundError: If post not found
        """
        post = self.get_post(post_id)

        if post.user_id != user_id:
            raise ValueError("Can only edit your own posts")

        if len(new_text) > self.MAX_POST_LENGTH:
            raise ContentTooLongError(f"Post must be {self.MAX_POST_LENGTH} characters or less")

        # Store edit in history
        self.post_versions[post_id].append((datetime.utcnow(), post.text))
        post.edit_history.append((datetime.utcnow(), new_text))

        # Update content
        post.text = new_text
        post.edited_at = datetime.utcnow()

        # Re-extract mentions and hashtags
        post.mentions = self._extract_mentions(new_text)
        post.hashtags = self._extract_hashtags(new_text)

        # Re-index
        self._reindex_post(post)

        return post

    def delete_post(self, post_id: UUID, user_id: UUID) -> None:
        """Soft delete a post.

        Args:
            post_id: Post ID to delete
            user_id: User ID requesting delete

        Raises:
            PostNotFoundError: If post not found
        """
        post = self.get_post(post_id)

        if post.user_id != user_id:
            raise ValueError("Can only delete your own posts")

        post.is_deleted = True

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

    def create_comment(
        self, post_id: UUID, user_id: UUID, text: str, reply_to_comment_id: UUID | None = None
    ) -> Comment:
        """Create a comment on a post.

        Args:
            post_id: ID of post being commented on
            user_id: Comment author ID
            text: Comment text
            reply_to_comment_id: ID of comment being replied to

        Returns:
            Created Comment object

        Raises:
            PostNotFoundError: If post not found
            ContentTooLongError: If text too long
        """
        post = self.get_post(post_id)

        if len(text) > self.MAX_COMMENT_LENGTH:
            raise ContentTooLongError(f"Comment must be {self.MAX_COMMENT_LENGTH} characters or less")

        # Extract mentions and hashtags
        mentions = self._extract_mentions(text)
        hashtags = self._extract_hashtags(text)

        comment = Comment(
            post_id=post_id,
            user_id=user_id,
            text=text,
            mentions=mentions,
            hashtags=hashtags,
            reply_to_comment_id=reply_to_comment_id,
            created_at=datetime.utcnow(),
        )

        self.comments[comment.id] = comment
        post.comments.append(comment)
        self._index_comment(comment)

        return comment

    def edit_comment(self, comment_id: UUID, user_id: UUID, new_text: str) -> Comment:
        """Edit a comment.

        Args:
            comment_id: Comment ID to edit
            user_id: User ID making edit
            new_text: New comment text

        Returns:
            Updated Comment object

        Raises:
            CommentNotFoundError: If comment not found
        """
        if comment_id not in self.comments:
            raise CommentNotFoundError(f"Comment {comment_id} not found")

        comment = self.comments[comment_id]

        if comment.user_id != user_id:
            raise ValueError("Can only edit your own comments")

        if len(new_text) > self.MAX_COMMENT_LENGTH:
            raise ContentTooLongError(f"Comment must be {self.MAX_COMMENT_LENGTH} characters or less")

        comment.text = new_text
        comment.edited_at = datetime.utcnow()
        comment.mentions = self._extract_mentions(new_text)
        comment.hashtags = self._extract_hashtags(new_text)

        return comment

    def delete_comment(self, comment_id: UUID, user_id: UUID) -> None:
        """Soft delete a comment.

        Args:
            comment_id: Comment ID to delete
            user_id: User ID requesting delete

        Raises:
            CommentNotFoundError: If comment not found
        """
        if comment_id not in self.comments:
            raise CommentNotFoundError(f"Comment {comment_id} not found")

        comment = self.comments[comment_id]

        if comment.user_id != user_id:
            raise ValueError("Can only delete your own comments")

        comment.is_deleted = True

    def get_post_thread(self, post_id: UUID) -> list[Post]:
        """Get conversation thread for a post (reply chain).

        Args:
            post_id: Post ID

        Returns:
            List of posts in thread

        Raises:
            PostNotFoundError: If post not found
        """
        post = self.get_post(post_id)
        thread = [post]

        # Find root post
        current = post
        while current.reply_to_post_id:
            current = self.get_post(current.reply_to_post_id)
            thread.insert(0, current)

        # Find replies to this post
        def find_replies(post_id: UUID) -> list[Post]:
            replies = []
            for p in self.posts.values():
                if p.reply_to_post_id == post_id and not p.is_deleted:
                    replies.append(p)
                    replies.extend(find_replies(p.id))
            return sorted(replies, key=lambda p: p.created_at)

        thread.extend(find_replies(post_id))
        return thread

    def search_posts(self, query: str, limit: int = 20) -> list[Post]:
        """Search posts using inverted index.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching posts

        Raises:
            ValueError: If query is empty
        """
        if not query.strip():
            raise ValueError("Search query cannot be empty")

        # Tokenize query
        tokens = query.lower().split()

        # Find posts matching all tokens
        matching_post_ids = None
        for token in tokens:
            if token in self.inverted_index:
                token_posts = self.inverted_index[token]
                if matching_post_ids is None:
                    matching_post_ids = token_posts.copy()
                else:
                    matching_post_ids &= token_posts
            else:
                return []  # No results if any token not found

        if matching_post_ids is None:
            return []

        # Get posts and filter deleted
        results = [self.posts[pid] for pid in matching_post_ids if pid in self.posts and not self.posts[pid].is_deleted]

        # Sort by creation time
        results.sort(key=lambda p: p.created_at, reverse=True)

        return results[:limit]

    def search_by_hashtag(self, hashtag: str, limit: int = 20) -> list[Post]:
        """Search posts by hashtag.

        Args:
            hashtag: Hashtag to search (without #)
            limit: Maximum results

        Returns:
            List of posts with hashtag
        """
        hashtag_lower = hashtag.lower()
        post_ids = self.hashtag_index.get(hashtag_lower, [])

        results = [self.posts[pid] for pid in post_ids if pid in self.posts and not self.posts[pid].is_deleted]

        results.sort(key=lambda p: p.created_at, reverse=True)
        return results[:limit]

    def _index_post(self, post: Post) -> None:
        """Index post for full-text search.

        Args:
            post: Post to index
        """
        # Index text tokens
        tokens = post.text.lower().split()
        for token in tokens:
            # Remove punctuation
            token = re.sub(r"[^\w]", "", token)
            if token:
                self.inverted_index[token].add(post.id)

        # Index hashtags
        for hashtag in post.hashtags:
            self.hashtag_index[hashtag.tag].append(post.id)

    def _reindex_post(self, post: Post) -> None:
        """Re-index post after edit.

        Args:
            post: Post to re-index
        """
        # Clear old index
        old_tokens = set()
        for token_set in self.inverted_index.values():
            if post.id in token_set:
                old_tokens.add(token_set)

        for token_set in old_tokens:
            token_set.discard(post.id)

        # Re-index
        self._index_post(post)

    def _index_comment(self, comment: Comment) -> None:
        """Index comment for search.

        Args:
            comment: Comment to index
        """
        tokens = comment.text.lower().split()
        for token in tokens:
            token = re.sub(r"[^\w]", "", token)
            if token:
                self.inverted_index[token].add(comment.id)

    def parse_rich_text(self, text: str) -> str:
        """Parse markdown-like syntax in text.

        Supports: **bold**, *italic*, `code`, [link](url), @mention, #hashtag

        Args:
            text: Text to parse

        Returns:
            HTML formatted text
        """
        # Convert **bold** to <strong>
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

        # Convert *italic* to <em>
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

        # Convert `code` to <code>
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)

        # Convert [text](url) to <a>
        text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)

        # Convert @mention to styled text
        text = re.sub(r"@([a-zA-Z0-9_-]+)", r'<span class="mention">@\1</span>', text)

        # Convert #hashtag to styled text
        text = re.sub(r"#([a-zA-Z0-9_]+)", r'<span class="hashtag">#\1</span>', text)

        return text

    def get_posts_by_user(self, user_id: UUID, limit: int = 20) -> list[Post]:
        """Get all posts by a user.

        Args:
            user_id: User ID
            limit: Maximum posts

        Returns:
            List of posts by user
        """
        user_posts = [post for post in self.posts.values() if post.user_id == user_id and not post.is_deleted]

        user_posts.sort(key=lambda p: p.created_at, reverse=True)
        return user_posts[:limit]
