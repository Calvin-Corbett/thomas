"""
POP3 protocol implementation.

Implements POP3 client for simple message retrieval with basic
message management and state handling.
"""

import builtins
from dataclasses import dataclass
from enum import Enum

from thomas.email_protocol._exceptions import (
    POP3AuthenticationError,
    POP3CommandError,
    POP3Error,
)
from thomas.email_protocol._types import EmailMessage


class POP3State(Enum):
    """POP3 client state machine states."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    TRANSACTION = "transaction"
    UPDATE = "update"


@dataclass
class POP3Response:
    """Represents POP3 server response.

    Attributes:
        status: Response status (+OK or -ERR)
        message: Status message
        lines: Multi-line response data
    """

    status: str
    message: str = ""
    lines: list[str] = None

    def __post_init__(self) -> None:
        """Initialize lines if None."""
        if self.lines is None:
            self.lines = []

    @property
    def is_success(self) -> bool:
        """Check if response indicates success."""
        return self.status == "+OK"


class POP3Client:
    """POP3 protocol client implementation.

    Handles message retrieval, deletion, and basic folder operations.
    POP3 has no folder support - all messages are in single mailbox.
    """

    def __init__(self, hostname: str, port: int = 995) -> None:
        """Initialize POP3 client.

        Args:
            hostname: POP3 server hostname
            port: POP3 server port (default 995 for SSL)
        """
        self.hostname = hostname
        self.port = port
        self.state = POP3State.DISCONNECTED
        self.authenticated = False
        self.messages: dict[int, EmailMessage] = {}
        self.deleted_messages: set = set()
        self.message_sizes: dict[int, int] = {}
        self.message_uids: dict[int, str] = {}
        self.greeting: str | None = None

    def connect(self) -> POP3Response:
        """Simulate POP3 connection.

        Returns:
            POP3 response with server greeting

        Raises:
            POP3Error: If already connected
        """
        if self.state != POP3State.DISCONNECTED:
            raise POP3Error("Already connected")

        self.state = POP3State.CONNECTED
        self.greeting = f"+OK {self.hostname} POP3 server ready"
        return self._parse_response(self.greeting)

    def user(self, username: str) -> POP3Response:
        """Send USER command with username.

        Args:
            username: Email or username

        Returns:
            POP3 response

        Raises:
            POP3Error: If command invalid
        """
        if self.state != POP3State.CONNECTED:
            raise POP3Error(f"Invalid state for USER: {self.state}")

        if not username or "@" not in username:
            raise POP3CommandError("-ERR Invalid user")

        return POP3Response("+OK", f"User {username} accepted")

    def password(self, password: str) -> POP3Response:
        """Send PASS command with password.

        Args:
            password: Password

        Returns:
            POP3 response

        Raises:
            POP3AuthenticationError: If authentication fails
        """
        if self.state not in (POP3State.CONNECTED, POP3State.TRANSACTION):
            raise POP3Error(f"Invalid state for PASS: {self.state}")

        if len(password) < 8:
            raise POP3AuthenticationError("-ERR Invalid password")

        self.authenticated = True
        self.state = POP3State.TRANSACTION
        self._populate_sample_messages()
        return POP3Response("+OK", "Password accepted, mailbox locked and ready")

    def stat(self) -> POP3Response:
        """Get mailbox status (message count and size).

        Returns:
            POP3 response with count and total size

        Raises:
            POP3Error: If not authenticated
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for STAT: {self.state}")

        message_count = len(self.messages) - len(self.deleted_messages)
        total_size = sum(size for msg_id, size in self.message_sizes.items() if msg_id not in self.deleted_messages)

        return POP3Response("+OK", f"{message_count} {total_size}")

    def list(self, message_id: int | None = None) -> POP3Response:
        """List message(s) with size.

        Args:
            message_id: Optional specific message ID

        Returns:
            POP3 response with message list

        Raises:
            POP3Error: If message not found
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for LIST: {self.state}")

        lines = []

        if message_id is not None:
            if message_id not in self.messages or message_id in self.deleted_messages:
                raise POP3CommandError(f"-ERR Message {message_id} not found")

            size = self.message_sizes.get(message_id, 0)
            return POP3Response("+OK", f"{message_id} {size}", [f"{message_id} {size}"])
        else:
            for msg_id, size in self.message_sizes.items():
                if msg_id not in self.deleted_messages:
                    lines.append(f"{msg_id} {size}")

            count = len(lines)
            return POP3Response("+OK", f"{count} messages", lines)

    def retr(self, message_id: int) -> POP3Response:
        """Retrieve full message.

        Args:
            message_id: Message ID to retrieve

        Returns:
            POP3 response with message lines

        Raises:
            POP3CommandError: If message not found
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for RETR: {self.state}")

        if message_id not in self.messages or message_id in self.deleted_messages:
            raise POP3CommandError(f"-ERR Message {message_id} not found")

        message = self.messages[message_id]
        lines = self._format_message(message)

        return POP3Response("+OK", f"{len(lines)} lines", lines)

    def dele(self, message_id: int) -> POP3Response:
        """Mark message for deletion.

        Args:
            message_id: Message ID to delete

        Returns:
            POP3 response

        Raises:
            POP3CommandError: If message not found
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for DELE: {self.state}")

        if message_id not in self.messages:
            raise POP3CommandError(f"-ERR Message {message_id} not found")

        if message_id in self.deleted_messages:
            raise POP3CommandError(f"-ERR Message {message_id} already deleted")

        self.deleted_messages.add(message_id)
        return POP3Response("+OK", f"Message {message_id} deleted")

    def rset(self) -> POP3Response:
        """Reset transaction (unmark deleted messages).

        Returns:
            POP3 response
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for RSET: {self.state}")

        self.deleted_messages.clear()
        return POP3Response("+OK", "Reset completed")

    def noop(self) -> POP3Response:
        """No operation (keep alive).

        Returns:
            POP3 response
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for NOOP: {self.state}")

        return POP3Response("+OK")

    def quit(self) -> POP3Response:
        """Close connection and commit deletions.

        Returns:
            POP3 response
        """
        if self.state == POP3State.TRANSACTION:
            self.state = POP3State.UPDATE
            for msg_id in self.deleted_messages:
                if msg_id in self.messages:
                    del self.messages[msg_id]
            self.deleted_messages.clear()

        self.state = POP3State.DISCONNECTED
        return POP3Response("+OK", "Server signing off")

    def top(self, message_id: int, lines: int = 0) -> POP3Response:
        """Retrieve message headers and first N lines.

        Args:
            message_id: Message ID
            lines: Number of body lines to include

        Returns:
            POP3 response with headers and body lines

        Raises:
            POP3CommandError: If message not found
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for TOP: {self.state}")

        if message_id not in self.messages or message_id in self.deleted_messages:
            raise POP3CommandError(f"-ERR Message {message_id} not found")

        message = self.messages[message_id]
        header_lines = self._format_message_headers(message)

        if lines > 0 and message.text_body:
            body_lines = message.text_body.split("\n")[:lines]
            header_lines.extend(body_lines)

        return POP3Response("+OK", f"Top of message {message_id}", header_lines)

    def uidl(self, message_id: int | None = None) -> POP3Response:
        """Get unique message identifier(s).

        Args:
            message_id: Optional specific message ID

        Returns:
            POP3 response with UID list

        Raises:
            POP3CommandError: If message not found
        """
        if self.state != POP3State.TRANSACTION:
            raise POP3Error(f"Invalid state for UIDL: {self.state}")

        lines = []

        if message_id is not None:
            if message_id not in self.messages or message_id in self.deleted_messages:
                raise POP3CommandError(f"-ERR Message {message_id} not found")

            uid = self.message_uids.get(message_id, f"uid_{message_id}")
            return POP3Response("+OK", f"{message_id} {uid}", [f"{message_id} {uid}"])
        else:
            for msg_id in self.messages:
                if msg_id not in self.deleted_messages:
                    uid = self.message_uids.get(msg_id, f"uid_{msg_id}")
                    lines.append(f"{msg_id} {uid}")

            return POP3Response("+OK", f"{len(lines)} messages", lines)

    def _populate_sample_messages(self) -> None:
        """Populate mailbox with sample messages."""
        sample_messages = [
            EmailMessage(),
            EmailMessage(),
            EmailMessage(),
        ]

        for idx, msg in enumerate(sample_messages, 1):
            msg.envelope.subject = f"Sample message {idx}"
            msg.text_body = f"This is sample message body {idx}"
            self.messages[idx] = msg
            self.message_sizes[idx] = len(self._format_message(msg))
            self.message_uids[idx] = f"uid_{self.hostname}_{idx}"

    def _format_message(self, message: EmailMessage) -> builtins.list[str]:
        """Format message for transmission.

        Args:
            message: Message to format

        Returns:
            List of message lines
        """
        lines = self._format_message_headers(message)
        lines.append("")

        if message.text_body:
            lines.extend(message.text_body.split("\n"))

        return lines

    def _format_message_headers(self, message: EmailMessage) -> builtins.list[str]:
        """Format message headers.

        Args:
            message: Message to format

        Returns:
            List of header lines
        """
        lines = []

        if message.envelope.from_addr:
            lines.append(f"From: {message.envelope.from_addr}")

        if message.envelope.to_addrs:
            to_list = ", ".join(str(addr) for addr in message.envelope.to_addrs)
            lines.append(f"To: {to_list}")

        if message.envelope.subject:
            lines.append(f"Subject: {message.envelope.subject}")

        if message.envelope.message_id:
            lines.append(f"Message-ID: {message.envelope.message_id}")

        return lines

    def _parse_response(self, response_line: str) -> POP3Response:
        """Parse POP3 response line.

        Args:
            response_line: Raw response line

        Returns:
            Parsed POP3 response

        Raises:
            POP3CommandError: If response malformed
        """
        parts = response_line.split(" ", 1)
        if not parts or parts[0] not in ("+OK", "-ERR"):
            raise POP3CommandError(f"Malformed response: {response_line}")

        status = parts[0]
        message = parts[1] if len(parts) > 1 else ""

        return POP3Response(status, message)
