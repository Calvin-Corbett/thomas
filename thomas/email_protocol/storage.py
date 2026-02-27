"""
Email storage formats and indexing.

Implements Maildir and mbox format support, message indexing,
folder management, quota tracking, and message deduplication.
"""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from thomas.email_protocol._types import EmailMessage, Flag


@dataclass
class MaildirMessage:
    """Represents a message in Maildir format.

    Attributes:
        filename: Unique filename
        flags: Flags encoded in filename
        size: Message size in bytes
        content: Message content
    """

    filename: str
    flags: set[Flag] = field(default_factory=set)
    size: int = 0
    content: bytes = field(default_factory=bytes)

    @staticmethod
    def from_flags(flags: set[Flag]) -> str:
        """Convert flags to Maildir filename suffix.

        Format: :2,<flags>
        Flags: P=Passed, R=Replied, S=Seen, T=Trashed, D=Draft, F=Flagged

        Args:
            flags: Set of flags

        Returns:
            Flag string for filename
        """
        flag_chars = []

        if Flag.DRAFT in flags:
            flag_chars.append("D")
        if Flag.FLAGGED in flags:
            flag_chars.append("F")
        if Flag.ANSWERED in flags:
            flag_chars.append("R")
        if Flag.SEEN in flags:
            flag_chars.append("S")
        if Flag.DELETED in flags:
            flag_chars.append("T")

        flag_str = "".join(sorted(set(flag_chars)))
        return f":2,{flag_str}" if flag_str else ""

    @staticmethod
    def generate_unique_filename(timestamp: int | None = None, hostname: str = "localhost") -> str:
        """Generate unique Maildir filename.

        Format: <timestamp>.<unique_id>.{hostname}

        Args:
            timestamp: Unix timestamp (default: current time)
            hostname: Server hostname

        Returns:
            Unique filename
        """
        if timestamp is None:
            timestamp = int(time.time())

        unique_id = hashlib.md5(str(time.time_ns()).encode()).hexdigest()[:12]
        return f"{timestamp}.{unique_id}.{hostname}"


class MaildirStorage:
    """Maildir format storage implementation.

    Uses directory structure: cur/ (read), new/ (unread), tmp/ (temp)
    """

    def __init__(self, root_path: str) -> None:
        """Initialize Maildir storage.

        Args:
            root_path: Root directory for Maildir structure
        """
        self.root_path = Path(root_path)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create required Maildir directories."""
        for subdir in ["cur", "new", "tmp"]:
            (self.root_path / subdir).mkdir(parents=True, exist_ok=True)

    def store_message(
        self,
        message: EmailMessage,
        seen: bool = False,
    ) -> str:
        """Store message in Maildir format.

        Args:
            message: Message to store
            seen: Whether message has been read

        Returns:
            Stored filename
        """
        content = self._serialize_message(message)
        subdir = "cur" if seen else "new"
        filename = MaildirMessage.generate_unique_filename()

        flag_suffix = MaildirMessage.from_flags(message.flags)
        full_filename = filename + flag_suffix

        filepath = self.root_path / subdir / full_filename
        filepath.write_bytes(content)

        return full_filename

    def retrieve_message(self, filename: str) -> bytes | None:
        """Retrieve message by filename.

        Args:
            filename: Maildir filename

        Returns:
            Message content or None
        """
        for subdir in ["cur", "new"]:
            filepath = self.root_path / subdir / filename
            if filepath.exists():
                return filepath.read_bytes()

        return None

    def list_messages(self) -> list[tuple[str, bytes]]:
        """List all messages.

        Returns:
            List of (filename, content) tuples
        """
        messages = []

        for subdir in ["cur", "new"]:
            subdir_path = self.root_path / subdir
            if subdir_path.exists():
                for filepath in subdir_path.iterdir():
                    if filepath.is_file():
                        messages.append((filepath.name, filepath.read_bytes()))

        return messages

    def _serialize_message(self, message: EmailMessage) -> bytes:
        """Serialize message to bytes.

        Args:
            message: Message to serialize

        Returns:
            Serialized message bytes
        """
        lines = []

        if message.envelope.from_addr:
            lines.append(f"From: {message.envelope.from_addr}")

        if message.envelope.to_addrs:
            to_list = ", ".join(str(addr) for addr in message.envelope.to_addrs)
            lines.append(f"To: {to_list}")

        if message.envelope.subject:
            lines.append(f"Subject: {message.envelope.subject}")

        lines.append("")
        if message.text_body:
            lines.append(message.text_body)

        return "\r\n".join(lines).encode()


class MboxStorage:
    """mbox format storage implementation.

    Stores all messages in single file with From_ line separators.
    """

    def __init__(self, filepath: str) -> None:
        """Initialize mbox storage.

        Args:
            filepath: Path to mbox file
        """
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def store_message(self, message: EmailMessage) -> None:
        """Append message to mbox file.

        Args:
            message: Message to store
        """
        content = self._serialize_message(message)

        with open(self.filepath, "ab") as f:
            f.write(content)

    def retrieve_messages(self) -> list[bytes]:
        """Retrieve all messages from mbox.

        Returns:
            List of message bytes
        """
        if not self.filepath.exists():
            return []

        messages = []
        with open(self.filepath, "rb") as f:
            content = f.read()

        parts = content.split(b"\nFrom ")
        for i, part in enumerate(parts):
            if i > 0:
                part = b"From " + part
            if part.strip():
                messages.append(part)

        return messages

    def _serialize_message(self, message: EmailMessage) -> bytes:
        """Serialize message in mbox format.

        Args:
            message: Message to serialize

        Returns:
            Serialized message bytes (with From_ line)
        """
        from_addr = "unknown"
        if message.envelope.from_addr:
            from_addr = message.envelope.from_addr.address

        timestamp = time.strftime("%a %b %d %H:%M:%S %Y")
        from_line = f"From {from_addr} {timestamp}\n"

        lines = []
        if message.envelope.from_addr:
            lines.append(f"From: {message.envelope.from_addr}")

        if message.envelope.to_addrs:
            to_list = ", ".join(str(addr) for addr in message.envelope.to_addrs)
            lines.append(f"To: {to_list}")

        if message.envelope.subject:
            lines.append(f"Subject: {message.envelope.subject}")

        lines.append("")
        if message.text_body:
            lines.append(message.text_body)

        message_content = "\r\n".join(lines) + "\r\n"

        return (from_line + message_content).encode()


class MessageIndex:
    """Inverted index for fast message searching."""

    def __init__(self) -> None:
        """Initialize message index."""
        self.from_index: dict[str, set[int]] = {}
        self.to_index: dict[str, set[int]] = {}
        self.subject_index: dict[str, set[int]] = {}
        self.date_index: dict[str, set[int]] = {}
        self.uid_map: dict[int, str] = {}

    def index_message(self, message_id: int, message: EmailMessage) -> None:
        """Add message to index.

        Args:
            message_id: Message ID
            message: Message to index
        """
        if message.envelope.from_addr:
            from_addr = message.envelope.from_addr.address.lower()
            if from_addr not in self.from_index:
                self.from_index[from_addr] = set()
            self.from_index[from_addr].add(message_id)

        for addr in message.envelope.to_addrs:
            to_addr = addr.address.lower()
            if to_addr not in self.to_index:
                self.to_index[to_addr] = set()
            self.to_index[to_addr].add(message_id)

        subject = message.envelope.subject.lower()
        for word in subject.split():
            if word not in self.subject_index:
                self.subject_index[word] = set()
            self.subject_index[word].add(message_id)

        if message.envelope.date:
            date_key = message.envelope.date.strftime("%Y-%m-%d")
            if date_key not in self.date_index:
                self.date_index[date_key] = set()
            self.date_index[date_key].add(message_id)

        if message.envelope.message_id:
            self.uid_map[message_id] = message.envelope.message_id

    def search_from(self, address: str) -> set[int]:
        """Find messages from address.

        Args:
            address: Sender address

        Returns:
            Set of message IDs
        """
        return self.from_index.get(address.lower(), set()).copy()

    def search_to(self, address: str) -> set[int]:
        """Find messages to address.

        Args:
            address: Recipient address

        Returns:
            Set of message IDs
        """
        return self.to_index.get(address.lower(), set()).copy()

    def search_subject(self, word: str) -> set[int]:
        """Find messages by subject word.

        Args:
            word: Subject word

        Returns:
            Set of message IDs
        """
        return self.subject_index.get(word.lower(), set()).copy()

    def search_date(self, date_str: str) -> set[int]:
        """Find messages by date.

        Args:
            date_str: Date string (YYYY-MM-DD)

        Returns:
            Set of message IDs
        """
        return self.date_index.get(date_str, set()).copy()


@dataclass
class QuotaInfo:
    """Mailbox quota information.

    Attributes:
        usage: Current usage in bytes
        limit: Quota limit in bytes
        message_count: Number of messages
        message_limit: Maximum message count
    """

    usage: int = 0
    limit: int = 0
    message_count: int = 0
    message_limit: int = 0

    def usage_percent(self) -> float:
        """Get usage percentage."""
        if self.limit == 0:
            return 0.0
        return (self.usage / self.limit) * 100

    def messages_percent(self) -> float:
        """Get message count percentage."""
        if self.message_limit == 0:
            return 0.0
        return (self.message_count / self.message_limit) * 100

    def is_over_limit(self) -> bool:
        """Check if quota exceeded."""
        return self.usage > self.limit

    def is_over_message_limit(self) -> bool:
        """Check if message limit exceeded."""
        return self.message_limit > 0 and self.message_count > self.message_limit


class MessageDeduplicator:
    """Deduplicate messages by Message-ID."""

    def __init__(self) -> None:
        """Initialize deduplicator."""
        self.seen_message_ids: set[str] = set()
        self.duplicates: dict[str, list[int]] = {}

    def check_duplicate(self, message: EmailMessage, message_id: int) -> bool:
        """Check if message is duplicate.

        Args:
            message: Message to check
            message_id: Message database ID

        Returns:
            True if message is duplicate
        """
        msg_id = message.envelope.message_id
        if not msg_id:
            return False

        if msg_id in self.seen_message_ids:
            if msg_id not in self.duplicates:
                self.duplicates[msg_id] = []
            self.duplicates[msg_id].append(message_id)
            return True

        self.seen_message_ids.add(msg_id)
        return False

    def get_duplicates(self, message_id: str) -> list[int]:
        """Get duplicate message IDs.

        Args:
            message_id: Message-ID header value

        Returns:
            List of duplicate message IDs
        """
        return self.duplicates.get(message_id, [])

    def remove_duplicate(self, message_id: str, db_id: int) -> None:
        """Mark duplicate as removed.

        Args:
            message_id: Message-ID
            db_id: Database ID to remove
        """
        if message_id in self.duplicates:
            self.duplicates[message_id] = [mid for mid in self.duplicates[message_id] if mid != db_id]
