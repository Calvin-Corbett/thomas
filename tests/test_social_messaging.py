"""Tests for direct messaging."""

from uuid import uuid4

import pytest

from thomas.social_platform import (
    ConversationNotFoundError,
    MessagingManager,
    ReactionType,
)


class TestMessagingManager:
    """Test suite for MessagingManager."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.manager = MessagingManager()
        self.user1 = uuid4()
        self.user2 = uuid4()
        self.user3 = uuid4()

    def test_create_1to1_conversation(self) -> None:
        """Test creating 1-to-1 conversation."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        assert conv.is_group is False
        assert len(conv.participant_ids) == 2
        assert self.user1 in conv.participant_ids

    def test_create_group_conversation(self) -> None:
        """Test creating group conversation."""
        conv = self.manager.create_conversation(
            {self.user1, self.user2, self.user3}, is_group=True, name="Friends Group"
        )

        assert conv.is_group is True
        assert conv.name == "Friends Group"
        assert len(conv.participant_ids) == 3

    def test_create_conversation_needs_participants(self) -> None:
        """Test conversation needs at least 2 participants."""
        with pytest.raises(ValueError):
            self.manager.create_conversation({self.user1})

    def test_find_existing_1to1(self) -> None:
        """Test finding existing 1-to-1 conversation."""
        conv1 = self.manager.create_conversation({self.user1, self.user2})

        # Creating another 1-to-1 with same users should return existing
        conv2 = self.manager.create_conversation({self.user1, self.user2})

        assert conv1.id == conv2.id

    def test_send_message(self) -> None:
        """Test sending message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Hello!")

        assert msg.text == "Hello!"
        assert msg.sender_id == self.user1
        assert msg.conversation_id == conv.id

    def test_send_message_not_participant(self) -> None:
        """Test non-participant cannot send message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        with pytest.raises(ValueError):
            self.manager.send_message(conv.id, self.user3, "Intruder!")

    def test_edit_message(self) -> None:
        """Test editing message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Original")
        edited = self.manager.edit_message(msg.id, self.user1, "Edited")

        assert edited.text == "Edited"
        assert edited.edited_at is not None

    def test_delete_message(self) -> None:
        """Test deleting message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Delete me")
        self.manager.delete_message(msg.id, self.user1)

        assert self.manager.messages[msg.id].is_deleted

    def test_mark_as_read(self) -> None:
        """Test marking message as read."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Read me")
        self.manager.mark_as_read(conv.id, self.user2, msg.id)

        assert msg.read_at is not None

    def test_typing_indicator(self) -> None:
        """Test typing indicators."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        self.manager.set_typing_indicator(conv.id, self.user1, True)
        typing = self.manager.get_typing_users(conv.id)

        assert self.user1 in typing

        self.manager.set_typing_indicator(conv.id, self.user1, False)
        typing = self.manager.get_typing_users(conv.id)

        assert self.user1 not in typing

    def test_read_receipts(self) -> None:
        """Test getting read receipts."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Test")
        self.manager.mark_as_read(conv.id, self.user2, msg.id)

        receipts = self.manager.get_read_receipts(msg.id)
        assert self.user2 in receipts

    def test_add_reaction(self) -> None:
        """Test adding reaction to message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "React!")
        reaction = self.manager.add_reaction(msg.id, self.user2, ReactionType.LOVE)

        assert reaction.reaction_type == ReactionType.LOVE
        assert len(msg.reactions) == 1

    def test_remove_reaction(self) -> None:
        """Test removing reaction from message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "React!")
        self.manager.add_reaction(msg.id, self.user2, ReactionType.LOVE)

        assert len(msg.reactions) == 1

        self.manager.remove_reaction(msg.id, self.user2, ReactionType.LOVE)
        assert len(msg.reactions) == 0

    def test_search_messages(self) -> None:
        """Test searching messages."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        self.manager.send_message(conv.id, self.user1, "Hello world")
        self.manager.send_message(conv.id, self.user2, "Hi there")
        self.manager.send_message(conv.id, self.user1, "How are you")

        results = self.manager.search_messages(conv.id, "world")
        assert len(results) == 1
        assert "world" in results[0].text

    def test_get_conversation(self) -> None:
        """Test retrieving conversation."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        retrieved = self.manager.get_conversation(conv.id)
        assert retrieved.id == conv.id

    def test_get_conversation_not_found(self) -> None:
        """Test retrieving non-existent conversation."""
        with pytest.raises(ConversationNotFoundError):
            self.manager.get_conversation(uuid4())

    def test_get_user_conversations(self) -> None:
        """Test getting all conversations for user."""
        conv1 = self.manager.create_conversation({self.user1, self.user2})
        conv2 = self.manager.create_conversation({self.user1, self.user3})

        convs = self.manager.get_user_conversations(self.user1)
        conv_ids = [c.id for c in convs]

        assert conv1.id in conv_ids
        assert conv2.id in conv_ids
        assert len(convs) == 2

    def test_get_conversation_messages(self) -> None:
        """Test retrieving messages from conversation."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        for i in range(5):
            self.manager.send_message(conv.id, self.user1, f"Message {i}")

        messages = self.manager.get_conversation_messages(conv.id, limit=10)
        assert len(messages) == 5

    def test_conversation_message_pagination(self) -> None:
        """Test message pagination."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        for i in range(5):
            self.manager.send_message(conv.id, self.user1, f"Message {i}")

        # Get first 2
        messages = self.manager.get_conversation_messages(conv.id, limit=2)
        assert len(messages) == 2

    def test_get_unread_count(self) -> None:
        """Test getting unread message count."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        self.manager.send_message(conv.id, self.user1, "Msg 1")
        self.manager.send_message(conv.id, self.user1, "Msg 2")
        self.manager.send_message(conv.id, self.user1, "Msg 3")

        unread = self.manager.get_unread_count(conv.id, self.user2)
        assert unread == 3

    def test_clear_typing_on_send(self) -> None:
        """Test that typing indicator is cleared when sending message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        self.manager.set_typing_indicator(conv.id, self.user1, True)
        self.manager.send_message(conv.id, self.user1, "Message")

        typing = self.manager.get_typing_users(conv.id)
        assert self.user1 not in typing

    def test_e2ee_setup(self) -> None:
        """Test E2EE key exchange setup."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        # E2EE keys should be established
        assert conv.id in self.manager.e2ee_keys

    def test_encrypted_message(self) -> None:
        """Test sending encrypted message."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg = self.manager.send_message(conv.id, self.user1, "Secret message", encrypt=True)

        # Message should be encrypted (hex string)
        assert len(msg.text) > len("Secret message")

    def test_multiple_messages_unread(self) -> None:
        """Test unread count with mixed read/unread."""
        conv = self.manager.create_conversation({self.user1, self.user2})

        msg1 = self.manager.send_message(conv.id, self.user1, "Msg 1")
        msg2 = self.manager.send_message(conv.id, self.user1, "Msg 2")
        msg3 = self.manager.send_message(conv.id, self.user1, "Msg 3")

        # Mark msg2 as read
        self.manager.mark_as_read(conv.id, self.user2, msg2.id)

        unread = self.manager.get_unread_count(conv.id, self.user2)
        assert unread == 2
