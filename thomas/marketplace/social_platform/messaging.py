"""Direct messaging system with encryption simulation.

This module handles 1:1 and group conversations, message threading,
read receipts, typing indicators, message reactions, and simulates
end-to-end encryption with Diffie-Hellman key exchange and AES-CTR.
"""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from ._exceptions import ConversationNotFoundError, MessageNotFoundError
from ._types import Conversation, DirectMessage, Media, Reaction, ReactionType


class DiffieHellmanKeyExchange:
    """Simulated Diffie-Hellman key exchange for E2EE.

    For demonstration purposes, this is a simplified implementation.
    """

    # Small prime for demo (real implementation would use large prime)
    PRIME = 23
    BASE = 5

    def __init__(self) -> None:
        """Initialize DH key exchange."""
        self.private_key: int | None = None
        self.public_key: int | None = None
        self.shared_secret: int | None = None

    def generate_key_pair(self, private_key: int | None = None) -> int:
        """Generate public key from private key.

        Args:
            private_key: Private key (if None, use stored)

        Returns:
            Public key
        """
        if private_key is not None:
            self.private_key = private_key
        else:
            self.private_key = hash(datetime.utcnow()) % self.PRIME

        # public = base^private mod prime
        self.public_key = pow(self.BASE, self.private_key, self.PRIME)
        return self.public_key

    def compute_shared_secret(self, other_public_key: int) -> int:
        """Compute shared secret from other party's public key.

        Args:
            other_public_key: Other party's public key

        Returns:
            Shared secret
        """
        if self.private_key is None:
            raise ValueError("Must generate key pair first")

        # shared_secret = public_key^private mod prime
        self.shared_secret = pow(other_public_key, self.private_key, self.PRIME)
        return self.shared_secret


class AESCTREncryption:
    """Simplified AES-CTR encryption simulation."""

    def __init__(self, key: int) -> None:
        """Initialize with encryption key.

        Args:
            key: Encryption key
        """
        self.key = key
        self.counter = 0

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext using simple XOR with key.

        Args:
            plaintext: Text to encrypt

        Returns:
            Hex-encoded ciphertext
        """
        ciphertext = []
        for i, char in enumerate(plaintext):
            # Simple XOR with key and counter
            key_stream = (self.key + self.counter + i) % 256
            encrypted_char = ord(char) ^ key_stream
            ciphertext.append(f"{encrypted_char:02x}")

        self.counter += 1
        return "".join(ciphertext)

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext.

        Args:
            ciphertext: Hex-encoded ciphertext

        Returns:
            Plaintext
        """
        plaintext = []
        for i in range(0, len(ciphertext), 2):
            encrypted_byte = int(ciphertext[i : i + 2], 16)
            key_stream = (self.key + self.counter + i // 2) % 256
            decrypted_char = chr(encrypted_byte ^ key_stream)
            plaintext.append(decrypted_char)

        self.counter += 1
        return "".join(plaintext)


class MessagingManager:
    """Manages direct messages and conversations.

    Attributes:
        conversations: Dictionary mapping conversation_id to Conversation
        messages: Dictionary mapping message_id to DirectMessage
        user_conversations: Map of user_id to conversation_ids
        typing_indicators: Track who is typing
        read_receipts: Track message read status
        e2ee_keys: E2EE keys for conversations
    """

    def __init__(self) -> None:
        """Initialize messaging manager."""
        self.conversations: dict[UUID, Conversation] = {}
        self.messages: dict[UUID, DirectMessage] = {}
        self.user_conversations: dict[UUID, set[UUID]] = defaultdict(set)
        self.typing_indicators: dict[UUID, set[UUID]] = defaultdict(set)
        self.read_receipts: dict[UUID, dict[UUID, datetime]] = defaultdict(dict)
        self.e2ee_keys: dict[UUID, tuple[int, int]] = {}  # conv_id -> (pub_key_1, pub_key_2)
        self.message_reactions: dict[UUID, list[Reaction]] = defaultdict(list)

    def create_conversation(
        self, participant_ids: set[UUID], is_group: bool = False, name: str | None = None
    ) -> Conversation:
        """Create a new conversation.

        Args:
            participant_ids: Set of participant user IDs
            is_group: Whether this is a group conversation
            name: Conversation name (for groups)

        Returns:
            Created Conversation object
        """
        if len(participant_ids) < 2:
            raise ValueError("Conversation needs at least 2 participants")

        # Check for existing 1:1 conversation
        if not is_group and len(participant_ids) == 2:
            existing = self._find_existing_1to1(participant_ids)
            if existing:
                return existing

        conversation = Conversation(
            participant_ids=participant_ids, is_group=is_group, name=name, created_at=datetime.utcnow()
        )

        self.conversations[conversation.id] = conversation

        # Index for each participant
        for user_id in participant_ids:
            self.user_conversations[user_id].add(conversation.id)

        # Setup E2EE (simplified)
        self._setup_e2ee(conversation)

        return conversation

    def _find_existing_1to1(self, participant_ids: set[UUID]) -> Conversation | None:
        """Find existing 1:1 conversation between users.

        Args:
            participant_ids: Two user IDs

        Returns:
            Conversation if exists, else None
        """
        for conv in self.conversations.values():
            if not conv.is_group and conv.participant_ids == participant_ids:
                return conv
        return None

    def _setup_e2ee(self, conversation: Conversation) -> None:
        """Setup E2EE key exchange for conversation.

        Args:
            conversation: Conversation to setup E2EE for
        """
        # Create key pairs for first two participants
        if len(conversation.participant_ids) >= 2:
            list(conversation.participant_ids)

            # DH key exchange
            dh1 = DiffieHellmanKeyExchange()
            dh2 = DiffieHellmanKeyExchange()

            pub1 = dh1.generate_key_pair()
            pub2 = dh2.generate_key_pair()

            # Compute shared secrets
            dh1.compute_shared_secret(pub2)
            dh2.compute_shared_secret(pub1)

            # Store public keys (in real scenario, derive shared key)
            self.e2ee_keys[conversation.id] = (pub1, pub2)

    def send_message(
        self, conversation_id: UUID, sender_id: UUID, text: str, media: list[Media] | None = None, encrypt: bool = False
    ) -> DirectMessage:
        """Send a message in conversation.

        Args:
            conversation_id: Conversation ID
            sender_id: Sender user ID
            text: Message text
            media: Optional media attachments
            encrypt: Whether to use E2EE

        Returns:
            Created DirectMessage object

        Raises:
            ConversationNotFoundError: If conversation not found
        """
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation = self.conversations[conversation_id]

        if sender_id not in conversation.participant_ids:
            raise ValueError("Sender not in conversation")

        # Encrypt if requested
        message_text = text
        if encrypt and conversation_id in self.e2ee_keys:
            pub_key_1, pub_key_2 = self.e2ee_keys[conversation_id]
            encryption_key = (pub_key_1 + pub_key_2) % 256
            cipher = AESCTREncryption(encryption_key)
            message_text = cipher.encrypt(text)

        message = DirectMessage(
            conversation_id=conversation_id,
            sender_id=sender_id,
            text=message_text,
            media=media or [],
            created_at=datetime.utcnow(),
        )

        self.messages[message.id] = message
        conversation.messages.append(message)
        conversation.last_message_at = datetime.utcnow()

        # Clear typing indicator
        self.typing_indicators[conversation_id].discard(sender_id)

        return message

    def edit_message(self, message_id: UUID, user_id: UUID, new_text: str) -> DirectMessage:
        """Edit a message.

        Args:
            message_id: Message ID
            user_id: User making edit
            new_text: New message text

        Returns:
            Updated DirectMessage

        Raises:
            MessageNotFoundError: If message not found
        """
        if message_id not in self.messages:
            raise MessageNotFoundError(f"Message {message_id} not found")

        message = self.messages[message_id]

        if message.sender_id != user_id:
            raise ValueError("Can only edit your own messages")

        message.text = new_text
        message.edited_at = datetime.utcnow()

        return message

    def delete_message(self, message_id: UUID, user_id: UUID) -> None:
        """Soft delete a message.

        Args:
            message_id: Message ID
            user_id: User deleting message

        Raises:
            MessageNotFoundError: If message not found
        """
        if message_id not in self.messages:
            raise MessageNotFoundError(f"Message {message_id} not found")

        message = self.messages[message_id]

        if message.sender_id != user_id:
            raise ValueError("Can only delete your own messages")

        message.is_deleted = True

    def mark_as_read(self, conversation_id: UUID, user_id: UUID, message_id: UUID) -> None:
        """Mark message as read.

        Args:
            conversation_id: Conversation ID
            user_id: User marking as read
            message_id: Message ID

        Raises:
            MessageNotFoundError: If message not found
        """
        if message_id not in self.messages:
            raise MessageNotFoundError(f"Message {message_id} not found")

        message = self.messages[message_id]
        self.read_receipts[message_id][user_id] = datetime.utcnow()
        message.read_at = datetime.utcnow()

    def set_typing_indicator(self, conversation_id: UUID, user_id: UUID, is_typing: bool) -> None:
        """Set typing indicator for user in conversation.

        Args:
            conversation_id: Conversation ID
            user_id: User ID
            is_typing: Whether user is typing
        """
        if is_typing:
            self.typing_indicators[conversation_id].add(user_id)
        else:
            self.typing_indicators[conversation_id].discard(user_id)

    def get_typing_users(self, conversation_id: UUID) -> list[UUID]:
        """Get users currently typing in conversation.

        Args:
            conversation_id: Conversation ID

        Returns:
            List of typing user IDs
        """
        return list(self.typing_indicators.get(conversation_id, set()))

    def get_read_receipts(self, message_id: UUID) -> dict[UUID, datetime]:
        """Get read receipts for a message.

        Args:
            message_id: Message ID

        Returns:
            Dictionary mapping user_id to read_at timestamp
        """
        return self.read_receipts.get(message_id, {})

    def add_reaction(self, message_id: UUID, user_id: UUID, reaction_type: ReactionType) -> Reaction:
        """Add reaction to message.

        Args:
            message_id: Message ID
            user_id: User reacting
            reaction_type: Reaction type

        Returns:
            Reaction object

        Raises:
            MessageNotFoundError: If message not found
        """
        if message_id not in self.messages:
            raise MessageNotFoundError(f"Message {message_id} not found")

        reaction = Reaction(
            user_id=user_id, content_id=message_id, reaction_type=reaction_type, created_at=datetime.utcnow()
        )

        message = self.messages[message_id]
        message.reactions.append(reaction)

        return reaction

    def remove_reaction(self, message_id: UUID, user_id: UUID, reaction_type: ReactionType) -> None:
        """Remove reaction from message.

        Args:
            message_id: Message ID
            user_id: User removing reaction
            reaction_type: Reaction type

        Raises:
            MessageNotFoundError: If message not found
        """
        if message_id not in self.messages:
            raise MessageNotFoundError(f"Message {message_id} not found")

        message = self.messages[message_id]
        message.reactions = [
            r for r in message.reactions if not (r.user_id == user_id and r.reaction_type == reaction_type)
        ]

    def search_messages(self, conversation_id: UUID, query: str, limit: int = 20) -> list[DirectMessage]:
        """Search messages in conversation.

        Args:
            conversation_id: Conversation ID
            query: Search query
            limit: Maximum results

        Returns:
            List of matching messages
        """
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        conversation = self.conversations[conversation_id]
        query_lower = query.lower()

        results = [msg for msg in conversation.messages if query_lower in msg.text.lower() and not msg.is_deleted]

        results.sort(key=lambda m: m.created_at, reverse=True)
        return results[:limit]

    def get_conversation(self, conversation_id: UUID) -> Conversation:
        """Get conversation by ID.

        Args:
            conversation_id: Conversation ID

        Returns:
            Conversation object

        Raises:
            ConversationNotFoundError: If conversation not found
        """
        if conversation_id not in self.conversations:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")
        return self.conversations[conversation_id]

    def get_user_conversations(self, user_id: UUID) -> list[Conversation]:
        """Get all conversations for user.

        Args:
            user_id: User ID

        Returns:
            List of Conversation objects
        """
        conv_ids = self.user_conversations.get(user_id, set())
        return [self.conversations[cid] for cid in conv_ids]

    def get_conversation_messages(
        self, conversation_id: UUID, limit: int = 50, before_message_id: UUID | None = None
    ) -> list[DirectMessage]:
        """Get messages from conversation with pagination.

        Args:
            conversation_id: Conversation ID
            limit: Maximum messages
            before_message_id: Message ID to get messages before

        Returns:
            List of DirectMessage objects

        Raises:
            ConversationNotFoundError: If conversation not found
        """
        conversation = self.get_conversation(conversation_id)

        messages = [m for m in conversation.messages if not m.is_deleted]
        messages.sort(key=lambda m: m.created_at, reverse=True)

        if before_message_id:
            before_idx = next((i for i, m in enumerate(messages) if m.id == before_message_id), None)
            if before_idx is not None:
                messages = messages[before_idx + 1 :]

        return messages[:limit]

    def get_unread_count(self, conversation_id: UUID, user_id: UUID) -> int:
        """Get unread message count for user in conversation.

        Args:
            conversation_id: Conversation ID
            user_id: User ID

        Returns:
            Count of unread messages
        """
        conversation = self.get_conversation(conversation_id)
        unread = 0

        for message in conversation.messages:
            if message.sender_id != user_id and not message.is_deleted:
                if user_id not in self.read_receipts.get(message.id, {}):
                    unread += 1

        return unread
