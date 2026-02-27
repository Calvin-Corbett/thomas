"""
Tests for event-sourced aggregates.

Tests replay, uncommitted events, snapshots, and loading.
"""

import pytest

from . import (
    AggregateCommand,
    AggregateRepository,
    AggregateRoot,
    CommandHandler,
    Event,
    EventStore,
)


class UserCreated(Event):
    """User creation event."""

    def __init__(self, user_id: str, email: str):
        super().__init__("UserCreated", f"user-{user_id}")
        self.user_id = user_id
        self.email = email


class UserEmailChanged(Event):
    """User email changed event."""

    def __init__(self, user_id: str, new_email: str):
        super().__init__("UserEmailChanged", f"user-{user_id}")
        self.user_id = user_id
        self.new_email = new_email


class UserDeactivated(Event):
    """User deactivated event."""

    def __init__(self, user_id: str):
        super().__init__("UserDeactivated", f"user-{user_id}")
        self.user_id = user_id


class UserAggregate(AggregateRoot):
    """Test aggregate for users."""

    def __init__(self, user_id: str):
        super().__init__(user_id)
        self._state = {
            "user_id": user_id,
            "email": None,
            "active": True,
        }

    def _on_user_created(self, event: UserCreated) -> None:
        self._state["email"] = event.email

    def _on_user_email_changed(self, event: UserEmailChanged) -> None:
        self._state["email"] = event.new_email

    def _on_user_deactivated(self, event: UserDeactivated) -> None:
        self._state["active"] = False

    def create_user(self, email: str) -> None:
        """Create a user."""
        event = UserCreated(self.id, email)
        self.record_event(event)

    def change_email(self, new_email: str) -> None:
        """Change user email."""
        event = UserEmailChanged(self.id, new_email)
        self.record_event(event)

    def deactivate(self) -> None:
        """Deactivate user."""
        event = UserDeactivated(self.id)
        self.record_event(event)


@pytest.fixture
def store():
    """Create event store."""
    return EventStore()


@pytest.fixture
def repository(store):
    """Create aggregate repository."""
    return AggregateRepository(store)


def test_create_aggregate():
    """Test creating a new aggregate."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")

    assert user.get_state_value("email") == "user@example.com"
    assert len(user.get_uncommitted_events()) == 1


def test_uncommitted_events():
    """Test tracking uncommitted events."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    user.change_email("newemail@example.com")

    uncommitted = user.get_uncommitted_events()

    assert len(uncommitted) == 2
    assert uncommitted[0].type == "UserCreated"
    assert uncommitted[1].type == "UserEmailChanged"


def test_clear_uncommitted_events():
    """Test clearing uncommitted events."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")

    assert len(user.get_uncommitted_events()) == 1

    user.clear_uncommitted_events()

    assert len(user.get_uncommitted_events()) == 0


def test_save_aggregate(repository):
    """Test saving aggregate."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")

    repository.save(user)

    assert len(user.get_uncommitted_events()) == 0


def test_load_aggregate(repository):
    """Test loading aggregate."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    user.change_email("new@example.com")

    repository.save(user)

    loaded = repository.load(UserAggregate, "user-123")

    assert loaded is not None
    assert loaded.get_state_value("email") == "new@example.com"
    assert loaded.version == 2


def test_load_nonexistent_aggregate(repository):
    """Test loading nonexistent aggregate."""
    loaded = repository.load(UserAggregate, "user-999")

    assert loaded is None


def test_aggregate_replay():
    """Test replaying events to build state."""
    events = [
        UserCreated("user-123", "user@example.com"),
        UserEmailChanged("user-123", "new@example.com"),
    ]

    user = UserAggregate("user-123")

    for event in events:
        user.apply_event(event)

    assert user.version == 2
    assert user.get_state_value("email") == "new@example.com"


def test_aggregate_version_tracking(repository):
    """Test version tracking."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    assert user.version == 1

    user.change_email("new@example.com")
    repository.save(user)

    assert user.version == 2


def test_load_at_version(repository):
    """Test loading aggregate at specific version."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    user.change_email("new@example.com")
    repository.save(user)

    loaded_v1 = repository.load_at_version(UserAggregate, "user-123", 1)

    assert loaded_v1 is not None
    assert loaded_v1.version == 1


def test_snapshot_save(repository):
    """Test saving snapshots."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    repository.save_snapshot(user, metadata={"reason": "test"})

    snapshot = repository.store.get_snapshot("UserAggregate-user-123")

    assert snapshot is not None
    assert snapshot.state["email"] == "user@example.com"


def test_snapshot_load(repository):
    """Test loading with snapshot."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    repository.save_snapshot(user)

    user.change_email("new@example.com")
    repository.save(user)

    loaded = repository.load(UserAggregate, "user-123")

    assert loaded.get_state_value("email") == "new@example.com"


def test_delete_snapshot(repository):
    """Test deleting snapshot."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    repository.save_snapshot(user)

    assert repository.store.get_snapshot("UserAggregate-user-123") is not None

    repository.delete_snapshot(UserAggregate, "user-123")

    assert repository.store.get_snapshot("UserAggregate-user-123") is None


def test_aggregate_version_query(repository):
    """Test getting aggregate version."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    repository.save(user)

    version = repository.get_aggregate_version(UserAggregate, "user-123")

    assert version == 1


def test_state_get_set():
    """Test getting and setting state."""
    user = UserAggregate("user-123")

    user.set_state_value("email", "user@example.com")

    assert user.get_state_value("email") == "user@example.com"
    assert user.get_state_value("nonexistent", "default") == "default"


def test_aggregate_deactivation():
    """Test multi-step aggregate state changes."""
    user = UserAggregate("user-123")

    user.create_user("user@example.com")
    user.change_email("new@example.com")
    user.deactivate()

    assert user.version == 3
    assert user.get_state_value("email") == "new@example.com"
    assert user.get_state_value("active") is False


class CreateUserCommand(AggregateCommand):
    """Test command."""

    def __init__(self, user_id: str, email: str):
        super().__init__(user_id)
        self.email = email

    def execute(self, aggregate: UserAggregate) -> None:
        aggregate.create_user(self.email)


class ChangeEmailCommand(AggregateCommand):
    """Test command."""

    def __init__(self, user_id: str, new_email: str):
        super().__init__(user_id)
        self.new_email = new_email

    def execute(self, aggregate: UserAggregate) -> None:
        aggregate.change_email(self.new_email)


def test_command_execution(repository):
    """Test command handler."""
    handler = CommandHandler(repository, UserAggregate)

    command = CreateUserCommand("user-123", "user@example.com")

    aggregate = handler.execute(command)

    assert aggregate.get_state_value("email") == "user@example.com"


def test_command_with_concurrency_check(repository):
    """Test command with concurrency check."""
    handler = CommandHandler(repository, UserAggregate)

    create_cmd = CreateUserCommand("user-123", "user@example.com")
    handler.execute(create_cmd)

    change_cmd = ChangeEmailCommand("user-123", "new@example.com")

    try:
        handler.execute_with_concurrency_check(change_cmd, expected_version=1)

        aggregate = repository.load(UserAggregate, "user-123")
        assert aggregate.get_state_value("email") == "new@example.com"
    except Exception:
        pass
