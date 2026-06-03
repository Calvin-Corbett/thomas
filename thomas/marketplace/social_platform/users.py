"""User management and social graph operations.

This module handles user registration, profile management, follower/following
relationships, and user discovery with efficient graph algorithms.
"""

import hashlib
import re
import secrets
from collections import defaultdict
from datetime import datetime
from uuid import UUID, uuid4

from ._exceptions import (
    BlockedUserError,
    DuplicateActionError,
    InvalidEmailError,
    InvalidPasswordError,
    InvalidUsernameError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from ._types import AccountStatus, Block, Follow, PrivacySetting, User


class UserManager:
    """Manages user accounts and social relationships.

    Attributes:
        users: Dictionary mapping user_id to User objects
        username_index: Dictionary mapping username to user_id (for fast lookup)
        email_index: Dictionary mapping email to user_id
        follower_graph: Adjacency list for follower relationships
        following_graph: Adjacency list for following relationships
    """

    def __init__(self) -> None:
        """Initialize the user manager."""
        self.users: dict[UUID, User] = {}
        self.username_index: dict[str, UUID] = {}
        self.email_index: dict[str, UUID] = {}
        self.follower_graph: dict[UUID, set[UUID]] = defaultdict(set)
        self.following_graph: dict[UUID, set[UUID]] = defaultdict(set)
        self.username_trie: dict = {}

    @staticmethod
    def _validate_username(username: str) -> None:
        """Validate username format.

        Args:
            username: Username to validate

        Raises:
            InvalidUsernameError: If username is invalid
        """
        if not username or len(username) < 3 or len(username) > 30:
            raise InvalidUsernameError("Username must be 3-30 characters")

        if not re.match(r"^[a-zA-Z0-9_-]+$", username):
            raise InvalidUsernameError("Username can only contain letters, numbers, underscore, hyphen")

    @staticmethod
    def _validate_email(email: str) -> None:
        """Validate email format.

        Args:
            email: Email to validate

        Raises:
            InvalidEmailError: If email is invalid
        """
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(pattern, email):
            raise InvalidEmailError("Invalid email format")

    @staticmethod
    def _validate_password(password: str) -> None:
        """Validate password strength.

        Args:
            password: Password to validate

        Raises:
            InvalidPasswordError: If password is too weak
        """
        if len(password) < 8:
            raise InvalidPasswordError("Password must be at least 8 characters")

        if not re.search(r"[A-Z]", password):
            raise InvalidPasswordError("Password must contain uppercase letter")

        if not re.search(r"[a-z]", password):
            raise InvalidPasswordError("Password must contain lowercase letter")

        if not re.search(r"[0-9]", password):
            raise InvalidPasswordError("Password must contain digit")

    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash a password with PBKDF2-HMAC-SHA256.

        Uses a random per-password salt and a high iteration count so the stored
        value is a slow, salted password hash rather than a fast unsalted digest.

        Args:
            password: Password to hash

        Returns:
            Self-describing hash string: ``pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>``
        """
        iterations = 600_000
        salt = secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
        return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"

    def register_user(self, username: str, email: str, password: str, display_name: str | None = None) -> User:
        """Register a new user.

        Args:
            username: Unique username
            email: User email address
            password: User password (will be hashed)
            display_name: User's display name

        Returns:
            Created User object

        Raises:
            InvalidUsernameError: If username is invalid
            InvalidEmailError: If email is invalid
            InvalidPasswordError: If password is weak
            UserAlreadyExistsError: If username/email already exists
        """
        self._validate_username(username)
        self._validate_email(email)
        self._validate_password(password)

        username_lower = username.lower()
        if username_lower in self.username_index:
            raise UserAlreadyExistsError(f"Username '{username}' already taken")

        if email.lower() in self.email_index:
            raise UserAlreadyExistsError(f"Email '{email}' already registered")

        user_id = uuid4()
        user = User(
            id=user_id,
            username=username,
            email=email,
            password_hash=self._hash_password(password),
            display_name=display_name or username,
            created_at=datetime.utcnow(),
        )

        self.users[user_id] = user
        self.username_index[username_lower] = user_id
        self.email_index[email.lower()] = user_id
        self._add_to_trie(username)

        return user

    def get_user_by_id(self, user_id: UUID) -> User:
        """Get user by ID.

        Args:
            user_id: User ID

        Returns:
            User object

        Raises:
            UserNotFoundError: If user not found
        """
        if user_id not in self.users:
            raise UserNotFoundError(f"User {user_id} not found")
        return self.users[user_id]

    def get_user_by_username(self, username: str) -> User:
        """Get user by username.

        Args:
            username: Username to lookup

        Returns:
            User object

        Raises:
            UserNotFoundError: If user not found
        """
        user_id = self.username_index.get(username.lower())
        if user_id is None:
            raise UserNotFoundError(f"User '{username}' not found")
        return self.users[user_id]

    def update_profile(
        self,
        user_id: UUID,
        display_name: str | None = None,
        bio: str | None = None,
        location: str | None = None,
        website: str | None = None,
        privacy_setting: PrivacySetting | None = None,
    ) -> User:
        """Update user profile.

        Args:
            user_id: User ID to update
            display_name: New display name
            bio: New bio
            location: New location
            website: New website
            privacy_setting: New privacy setting

        Returns:
            Updated User object

        Raises:
            UserNotFoundError: If user not found
        """
        user = self.get_user_by_id(user_id)

        if display_name is not None:
            user.display_name = display_name
        if bio is not None:
            user.bio = bio[:500]  # Limit bio to 500 chars
        if location is not None:
            user.location = location
        if website is not None:
            user.website = website
        if privacy_setting is not None:
            user.privacy_setting = privacy_setting

        user.updated_at = datetime.utcnow()
        return user

    def follow_user(self, follower_id: UUID, following_id: UUID) -> Follow:
        """Create follow relationship.

        Args:
            follower_id: User doing the following
            following_id: User being followed

        Returns:
            Follow object

        Raises:
            UserNotFoundError: If either user not found
            DuplicateActionError: If already following
            BlockedUserError: If blocked
        """
        self.get_user_by_id(follower_id)
        self.get_user_by_id(following_id)

        if follower_id == following_id:
            raise InvalidOperationError("Cannot follow yourself")

        # Check if blocked
        if following_id in self.users[follower_id].blocking_users:
            raise BlockedUserError("Cannot follow blocked user")

        if following_id in self.users[follower_id].blocked_users:
            raise BlockedUserError("Blocked user cannot follow you")

        if following_id in self.following_graph[follower_id]:
            raise DuplicateActionError("Already following this user")

        follow = Follow(follower_id=follower_id, following_id=following_id, created_at=datetime.utcnow())

        self.following_graph[follower_id].add(following_id)
        self.follower_graph[following_id].add(follower_id)
        self.users[follower_id].following[following_id] = follow
        self.users[following_id].followers[follower_id] = follow

        self.users[follower_id].following_count += 1
        self.users[following_id].follower_count += 1

        return follow

    def unfollow_user(self, follower_id: UUID, following_id: UUID) -> None:
        """Remove follow relationship.

        Args:
            follower_id: User doing the unfollowing
            following_id: User being unfollowed

        Raises:
            UserNotFoundError: If user not found
        """
        self.get_user_by_id(follower_id)
        self.get_user_by_id(following_id)

        if following_id not in self.following_graph[follower_id]:
            return

        self.following_graph[follower_id].discard(following_id)
        self.follower_graph[following_id].discard(follower_id)
        self.users[follower_id].following.pop(following_id, None)
        self.users[following_id].followers.pop(follower_id, None)

        self.users[follower_id].following_count -= 1
        self.users[following_id].follower_count -= 1

    def get_followers(self, user_id: UUID) -> list[User]:
        """Get user's followers.

        Args:
            user_id: User ID

        Returns:
            List of User objects who follow this user

        Raises:
            UserNotFoundError: If user not found
        """
        self.get_user_by_id(user_id)
        return [self.users[fid] for fid in self.follower_graph[user_id]]

    def get_following(self, user_id: UUID) -> list[User]:
        """Get user's following list.

        Args:
            user_id: User ID

        Returns:
            List of User objects this user follows

        Raises:
            UserNotFoundError: If user not found
        """
        self.get_user_by_id(user_id)
        return [self.users[uid] for uid in self.following_graph[user_id]]

    def get_mutual_friends(self, user_id_1: UUID, user_id_2: UUID) -> list[User]:
        """Get mutual friends between two users.

        Uses intersection of follower/following sets for O(min(n,m)) complexity.

        Args:
            user_id_1: First user ID
            user_id_2: Second user ID

        Returns:
            List of users that both follow

        Raises:
            UserNotFoundError: If either user not found
        """
        self.get_user_by_id(user_id_1)
        self.get_user_by_id(user_id_2)

        # Get users that user_id_1 follows
        user1_following = self.following_graph[user_id_1]
        # Get users that user_id_2 follows
        user2_following = self.following_graph[user_id_2]

        # Mutual friends are intersection
        mutual_ids = user1_following & user2_following
        return [self.users[uid] for uid in mutual_ids]

    def block_user(self, blocker_id: UUID, blocked_id: UUID) -> Block:
        """Block a user.

        Args:
            blocker_id: User doing the blocking
            blocked_id: User being blocked

        Returns:
            Block object

        Raises:
            UserNotFoundError: If user not found
        """
        self.get_user_by_id(blocker_id)
        self.get_user_by_id(blocked_id)

        if blocker_id == blocked_id:
            raise InvalidOperationError("Cannot block yourself")

        block = Block(blocker_id=blocker_id, blocked_id=blocked_id)
        self.users[blocker_id].blocking_users[blocked_id] = block

        # Remove follow relationships
        self.unfollow_user(blocker_id, blocked_id)
        self.unfollow_user(blocked_id, blocker_id)

        return block

    def unblock_user(self, blocker_id: UUID, blocked_id: UUID) -> None:
        """Unblock a user.

        Args:
            blocker_id: User doing the unblocking
            blocked_id: User being unblocked

        Raises:
            UserNotFoundError: If user not found
        """
        self.get_user_by_id(blocker_id)
        self.get_user_by_id(blocked_id)

        self.users[blocker_id].blocking_users.pop(blocked_id, None)

    def is_blocked(self, user_id: UUID, other_user_id: UUID) -> bool:
        """Check if user is blocked.

        Args:
            user_id: User to check
            other_user_id: Potential blocker

        Returns:
            True if other_user blocks user_id
        """
        if user_id not in self.users or other_user_id not in self.users:
            return False
        return other_user_id in self.users[user_id].blocking_users

    def search_users(self, query: str, limit: int = 20) -> list[User]:
        """Search users by username prefix using trie.

        Args:
            query: Username prefix to search
            limit: Maximum results to return

        Returns:
            List of matching users
        """
        results = self._search_trie(query.lower())
        users = [self.users[uid] for uid in results if uid in self.users]
        return users[:limit]

    def _add_to_trie(self, username: str) -> None:
        """Add username to trie for prefix search.

        Args:
            username: Username to add
        """
        node = self.username_trie
        for char in username.lower():
            if char not in node:
                node[char] = {}
            node = node[char]

        if "_users" not in node:
            node["_users"] = []
        node["_users"].append(self.username_index[username.lower()])

    def _search_trie(self, prefix: str) -> list[UUID]:
        """Search trie for usernames with given prefix.

        Args:
            prefix: Username prefix

        Returns:
            List of user IDs matching prefix
        """
        node = self.username_trie
        for char in prefix.lower():
            if char not in node:
                return []
            node = node[char]

        # Collect all users from this node and below
        users = []
        self._collect_users_from_trie(node, users)
        return users

    def _collect_users_from_trie(self, node: dict, users: list[UUID]) -> None:
        """Recursively collect users from trie node.

        Args:
            node: Trie node
            users: List to accumulate user IDs
        """
        for key, value in node.items():
            if key == "_users":
                users.extend(value)
            else:
                self._collect_users_from_trie(value, users)

    def deactivate_account(self, user_id: UUID) -> None:
        """Deactivate user account.

        Args:
            user_id: User ID to deactivate

        Raises:
            UserNotFoundError: If user not found
        """
        user = self.get_user_by_id(user_id)
        user.status = AccountStatus.DEACTIVATED
        user.updated_at = datetime.utcnow()

    def reactivate_account(self, user_id: UUID) -> None:
        """Reactivate user account.

        Args:
            user_id: User ID to reactivate

        Raises:
            UserNotFoundError: If user not found
        """
        user = self.get_user_by_id(user_id)
        user.status = AccountStatus.ACTIVE
        user.updated_at = datetime.utcnow()

    def get_user_stats(self, user_id: UUID) -> dict[str, int]:
        """Get user statistics.

        Args:
            user_id: User ID

        Returns:
            Dictionary with stats

        Raises:
            UserNotFoundError: If user not found
        """
        user = self.get_user_by_id(user_id)
        return {
            "follower_count": user.follower_count,
            "following_count": user.following_count,
            "post_count": user.post_count,
            "joined_days": (datetime.utcnow() - user.created_at).days,
        }

    def check_can_view_profile(self, viewer_id: UUID | None, profile_user_id: UUID) -> bool:
        """Check if viewer can see user's profile.

        Args:
            viewer_id: User viewing the profile (None for anonymous)
            profile_user_id: User whose profile is being viewed

        Returns:
            True if profile is viewable
        """
        if profile_user_id not in self.users:
            return False

        target = self.users[profile_user_id]

        # Deactivated accounts not viewable
        if target.status != AccountStatus.ACTIVE:
            return False

        # Public profiles viewable by anyone
        if target.privacy_setting == PrivacySetting.PUBLIC:
            return True

        # Private profiles only by owner
        if target.privacy_setting == PrivacySetting.PRIVATE:
            return viewer_id == profile_user_id

        # Friends-only viewable by followers
        if target.privacy_setting == PrivacySetting.FRIENDS_ONLY:
            if viewer_id is None:
                return False
            return viewer_id in self.follower_graph[profile_user_id]

        return False

    def get_suggested_users(self, user_id: UUID, limit: int = 10) -> list[User]:
        """Get user suggestions based on mutual connections.

        Args:
            user_id: User ID
            limit: Maximum suggestions

        Returns:
            List of suggested users
        """
        self.get_user_by_id(user_id)
        suggestions = {}

        # Find friends of friends
        for friend_id in self.following_graph[user_id]:
            self.users[friend_id]
            for friend_of_friend in self.following_graph[friend_id]:
                if friend_of_friend == user_id:
                    continue
                if friend_of_friend in self.following_graph[user_id]:
                    continue
                if friend_of_friend in suggestions:
                    suggestions[friend_of_friend] += 1
                else:
                    suggestions[friend_of_friend] = 1

        # Sort by mutual friend count
        sorted_suggestions = sorted(suggestions.items(), key=lambda x: x[1], reverse=True)

        return [self.users[uid] for uid, _ in sorted_suggestions[:limit]]


class InvalidOperationError(Exception):
    """Raised for invalid operations."""

    pass
