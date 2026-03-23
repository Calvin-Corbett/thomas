"""Tests for user management module."""

from uuid import uuid4

import pytest

from thomas.marketplace.social_platform import (
    AccountStatus,
    BlockedUserError,
    DuplicateActionError,
    InvalidEmailError,
    InvalidPasswordError,
    InvalidUsernameError,
    PrivacySetting,
    UserAlreadyExistsError,
    UserManager,
    UserNotFoundError,
)


class TestUserManager:
    """Test suite for UserManager."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.manager = UserManager()

    def test_register_user_success(self) -> None:
        """Test successful user registration."""
        user = self.manager.register_user(
            username="alice", email="alice@example.com", password="SecurePass123", display_name="Alice Smith"
        )

        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.display_name == "Alice Smith"
        assert user.status == AccountStatus.ACTIVE

    def test_register_user_invalid_username(self) -> None:
        """Test registration with invalid username."""
        with pytest.raises(InvalidUsernameError):
            self.manager.register_user(
                username="ab",  # Too short
                email="test@example.com",
                password="SecurePass123",
            )

        with pytest.raises(InvalidUsernameError):
            self.manager.register_user(
                username="test@user",  # Invalid chars
                email="test@example.com",
                password="SecurePass123",
            )

    def test_register_user_invalid_email(self) -> None:
        """Test registration with invalid email."""
        with pytest.raises(InvalidEmailError):
            self.manager.register_user(username="alice", email="not-an-email", password="SecurePass123")

    def test_register_user_weak_password(self) -> None:
        """Test registration with weak password."""
        with pytest.raises(InvalidPasswordError):
            self.manager.register_user(
                username="alice",
                email="alice@example.com",
                password="weak",  # Too short, no uppercase, no digit
            )

    def test_register_duplicate_username(self) -> None:
        """Test registering duplicate username."""
        self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        with pytest.raises(UserAlreadyExistsError):
            self.manager.register_user(username="alice", email="other@example.com", password="SecurePass123")

    def test_get_user_by_id(self) -> None:
        """Test retrieving user by ID."""
        user = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        retrieved = self.manager.get_user_by_id(user.id)
        assert retrieved.id == user.id
        assert retrieved.username == "bob"

    def test_get_user_by_username(self) -> None:
        """Test retrieving user by username."""
        user = self.manager.register_user(username="charlie", email="charlie@example.com", password="SecurePass123")

        retrieved = self.manager.get_user_by_username("charlie")
        assert retrieved.id == user.id

    def test_get_user_not_found(self) -> None:
        """Test retrieving non-existent user."""
        with pytest.raises(UserNotFoundError):
            self.manager.get_user_by_id(uuid4())

        with pytest.raises(UserNotFoundError):
            self.manager.get_user_by_username("nonexistent")

    def test_update_profile(self) -> None:
        """Test updating user profile."""
        user = self.manager.register_user(username="dave", email="dave@example.com", password="SecurePass123")

        updated = self.manager.update_profile(
            user.id,
            display_name="David Jones",
            bio="Software engineer",
            location="San Francisco",
            website="https://example.com",
        )

        assert updated.display_name == "David Jones"
        assert updated.bio == "Software engineer"
        assert updated.location == "San Francisco"

    def test_follow_user(self) -> None:
        """Test following a user."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        follow = self.manager.follow_user(alice.id, bob.id)

        assert follow.follower_id == alice.id
        assert follow.following_id == bob.id
        assert alice.following_count == 1
        assert bob.follower_count == 1

    def test_follow_self_error(self) -> None:
        """Test that user cannot follow themselves."""
        user = self.manager.register_user(username="self", email="self@example.com", password="SecurePass123")

        with pytest.raises(Exception):
            self.manager.follow_user(user.id, user.id)

    def test_follow_duplicate_error(self) -> None:
        """Test following same user twice."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        self.manager.follow_user(alice.id, bob.id)

        with pytest.raises(DuplicateActionError):
            self.manager.follow_user(alice.id, bob.id)

    def test_unfollow_user(self) -> None:
        """Test unfollowing a user."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        self.manager.follow_user(alice.id, bob.id)
        assert alice.following_count == 1

        self.manager.unfollow_user(alice.id, bob.id)
        assert alice.following_count == 0

    def test_get_followers(self) -> None:
        """Test getting user's followers."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        charlie = self.manager.register_user(username="charlie", email="charlie@example.com", password="SecurePass123")

        self.manager.follow_user(bob.id, alice.id)
        self.manager.follow_user(charlie.id, alice.id)

        followers = self.manager.get_followers(alice.id)
        assert len(followers) == 2

    def test_get_mutual_friends(self) -> None:
        """Test finding mutual friends."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        charlie = self.manager.register_user(username="charlie", email="charlie@example.com", password="SecurePass123")

        david = self.manager.register_user(username="david", email="david@example.com", password="SecurePass123")

        # Alice and Bob both follow Charlie
        self.manager.follow_user(alice.id, charlie.id)
        self.manager.follow_user(bob.id, charlie.id)
        # Only Alice follows David
        self.manager.follow_user(alice.id, david.id)

        mutuals = self.manager.get_mutual_friends(alice.id, bob.id)
        assert len(mutuals) == 1
        assert mutuals[0].id == charlie.id

    def test_block_user(self) -> None:
        """Test blocking a user."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        block = self.manager.block_user(alice.id, bob.id)
        assert block.blocker_id == alice.id
        assert block.blocked_id == bob.id

    def test_follow_blocked_user_error(self) -> None:
        """Test that cannot follow blocked user."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        self.manager.block_user(alice.id, bob.id)

        with pytest.raises(BlockedUserError):
            self.manager.follow_user(alice.id, bob.id)

    def test_is_blocked(self) -> None:
        """Test checking if user is blocked."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        assert not self.manager.is_blocked(bob.id, alice.id)

        self.manager.block_user(alice.id, bob.id)
        assert self.manager.is_blocked(bob.id, alice.id)

    def test_search_users(self) -> None:
        """Test searching users by prefix."""
        self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        self.manager.register_user(username="alex", email="alex@example.com", password="SecurePass123")

        self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        results = self.manager.search_users("al")
        assert len(results) == 2

        results = self.manager.search_users("bob")
        assert len(results) == 1

    def test_deactivate_account(self) -> None:
        """Test account deactivation."""
        user = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        assert user.status == AccountStatus.ACTIVE

        self.manager.deactivate_account(user.id)
        user = self.manager.get_user_by_id(user.id)
        assert user.status == AccountStatus.DEACTIVATED

    def test_reactivate_account(self) -> None:
        """Test account reactivation."""
        user = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        self.manager.deactivate_account(user.id)
        self.manager.reactivate_account(user.id)

        user = self.manager.get_user_by_id(user.id)
        assert user.status == AccountStatus.ACTIVE

    def test_get_user_stats(self) -> None:
        """Test retrieving user statistics."""
        user = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        stats = self.manager.get_user_stats(user.id)
        assert stats["follower_count"] == 0
        assert stats["following_count"] == 0
        assert stats["post_count"] == 0

    def test_check_can_view_profile_public(self) -> None:
        """Test profile visibility for public accounts."""
        user = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        # Public profile viewable by anyone
        assert self.manager.check_can_view_profile(None, user.id)
        assert self.manager.check_can_view_profile(uuid4(), user.id)

    def test_check_can_view_profile_private(self) -> None:
        """Test profile visibility for private accounts."""
        user = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        self.manager.update_profile(user.id, privacy_setting=PrivacySetting.PRIVATE)

        # Private profile only viewable by owner
        assert self.manager.check_can_view_profile(user.id, user.id)
        assert not self.manager.check_can_view_profile(uuid4(), user.id)

    def test_suggested_users(self) -> None:
        """Test user suggestions based on mutual connections."""
        alice = self.manager.register_user(username="alice", email="alice@example.com", password="SecurePass123")

        bob = self.manager.register_user(username="bob", email="bob@example.com", password="SecurePass123")

        charlie = self.manager.register_user(username="charlie", email="charlie@example.com", password="SecurePass123")

        david = self.manager.register_user(username="david", email="david@example.com", password="SecurePass123")

        # Alice -> Bob -> Charlie -> David chain
        self.manager.follow_user(alice.id, bob.id)
        self.manager.follow_user(bob.id, charlie.id)
        self.manager.follow_user(charlie.id, david.id)

        suggestions = self.manager.get_suggested_users(alice.id, limit=5)
        # Should suggest Charlie and David
        suggestion_ids = [s.id for s in suggestions]
        assert charlie.id in suggestion_ids
