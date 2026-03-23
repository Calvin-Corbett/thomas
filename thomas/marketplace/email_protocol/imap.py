"""
IMAP protocol implementation.

Implements IMAP client with folder management, message fetching,
searching, flagging, and response parsing.
"""

import re
from dataclasses import dataclass, field
from enum import Enum

from thomas.marketplace.email_protocol._exceptions import (
    IMAPAuthenticationError,
    IMAPError,
    IMAPParseError,
    IMAPProtocolError,
)
from thomas.marketplace.email_protocol._types import (
    EmailMessage,
    Flag,
    Folder,
    SearchCriteria,
)


class IMAPState(Enum):
    """IMAP client state machine states."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    SELECTED = "selected"
    IDLE = "idle"


@dataclass
class IMAPResponse:
    """Represents IMAP server response.

    Attributes:
        status: Response status (OK, NO, BAD)
        code: Optional response code (e.g., EXISTS, EXPUNGE)
        message: Response text
        data: Additional response data
    """

    status: str
    code: str | None = None
    message: str = ""
    data: dict[str, any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if response indicates success."""
        return self.status.upper() == "OK"


class IMAPClient:
    """IMAP protocol client implementation.

    Handles mailbox selection, message retrieval, searching, flagging,
    and folder operations.
    """

    def __init__(self, hostname: str, port: int = 993) -> None:
        """Initialize IMAP client.

        Args:
            hostname: IMAP server hostname
            port: IMAP server port (default 993 for SSL)
        """
        self.hostname = hostname
        self.port = port
        self.state = IMAPState.DISCONNECTED
        self.authenticated = False
        self.current_folder: str | None = None
        self.tag_counter = 0
        self.capabilities: set[str] = set()
        self.mailbox_data: dict[str, dict[str, int]] = {}
        self.messages: dict[int, EmailMessage] = {}
        self.selected_folder_stats = {"EXISTS": 0, "RECENT": 0, "UNSEEN": 0}

    def connect(self) -> IMAPResponse:
        """Simulate IMAP connection.

        Returns:
            IMAP response
        """
        if self.state != IMAPState.DISCONNECTED:
            raise IMAPError("Already connected")

        self.state = IMAPState.CONNECTED
        self.capabilities = {"IMAP4REV1", "STARTTLS", "AUTH=PLAIN", "AUTH=LOGIN"}
        return IMAPResponse("OK", "IMAP4REV1 ready")

    def login(self, username: str, password: str) -> IMAPResponse:
        """Authenticate with username and password.

        Args:
            username: Email or username
            password: Password

        Returns:
            IMAP response

        Raises:
            IMAPAuthenticationError: If authentication fails
        """
        if self.state != IMAPState.CONNECTED:
            raise IMAPError(f"Invalid state for LOGIN: {self.state}")

        if len(password) < 8:
            raise IMAPAuthenticationError("NO [AUTHENTICATIONFAILED] Invalid credentials")

        self.authenticated = True
        self.state = IMAPState.AUTHENTICATED
        return IMAPResponse("OK", message="LOGIN completed")

    def select(self, mailbox: str) -> IMAPResponse:
        """Select a mailbox for operations.

        Args:
            mailbox: Mailbox name (e.g., 'INBOX')

        Returns:
            IMAP response with mailbox statistics

        Raises:
            IMAPError: If mailbox cannot be selected
        """
        if self.state != IMAPState.AUTHENTICATED:
            raise IMAPError(f"Invalid state for SELECT: {self.state}")

        if not self._validate_mailbox(mailbox):
            raise IMAPProtocolError(f"NO [CANNOT] Cannot open mailbox {mailbox}")

        self.current_folder = mailbox
        self.state = IMAPState.SELECTED

        self.selected_folder_stats = self._get_mailbox_stats(mailbox)

        response = IMAPResponse("OK", code="READ-WRITE")
        response.data = self.selected_folder_stats
        return response

    def fetch(
        self,
        sequence: int | str | list[int],
        items: list[str] | None = None,
    ) -> list[tuple[int, EmailMessage]]:
        """Fetch message(s) from current mailbox.

        Args:
            sequence: Message number, UID, or range (e.g., 1, 1:10, [1,3,5])
            items: FETCH data items (FLAGS, ENVELOPE, BODY, etc.)

        Returns:
            List of (sequence_number, message) tuples

        Raises:
            IMAPError: If fetch fails
        """
        if self.state != IMAPState.SELECTED:
            raise IMAPError(f"Invalid state for FETCH: {self.state}")

        if items is None:
            items = ["FLAGS", "ENVELOPE", "BODY"]

        messages = []
        sequence_nums = self._parse_sequence(sequence)

        for seq_num in sequence_nums:
            if seq_num in self.messages:
                messages.append((seq_num, self.messages[seq_num]))

        return messages

    def search(self, criteria: SearchCriteria) -> list[int]:
        """Search for messages matching criteria.

        Args:
            criteria: Search criteria

        Returns:
            List of matching message sequence numbers
        """
        if self.state != IMAPState.SELECTED:
            raise IMAPError(f"Invalid state for SEARCH: {self.state}")

        results = []

        for seq_num, message in self.messages.items():
            if self._matches_criteria(message, criteria):
                results.append(seq_num)

        return sorted(results)

    def _matches_criteria(self, message: EmailMessage, criteria: SearchCriteria) -> bool:
        """Check if message matches search criteria.

        Args:
            message: Message to check
            criteria: Search criteria

        Returns:
            True if message matches all criteria
        """
        if criteria.from_addr:
            if not message.envelope.from_addr:
                return False
            if criteria.from_addr.lower() not in message.envelope.from_addr.address.lower():
                return False

        if criteria.to_addr:
            to_addresses = [addr.address.lower() for addr in message.envelope.to_addrs]
            if criteria.to_addr.lower() not in to_addresses:
                return False

        if criteria.subject:
            if criteria.subject.lower() not in message.envelope.subject.lower():
                return False

        if criteria.body and message.text_body:
            if criteria.body.lower() not in message.text_body.lower():
                return False

        if criteria.since and message.envelope.date:
            if message.envelope.date < criteria.since:
                return False

        if criteria.before and message.envelope.date:
            if message.envelope.date > criteria.before:
                return False

        if criteria.seen is not None:
            has_seen = Flag.SEEN in message.flags
            if has_seen != criteria.seen:
                return False

        if criteria.flagged is not None:
            has_flagged = Flag.FLAGGED in message.flags
            if has_flagged != criteria.flagged:
                return False

        if criteria.size_min and message.size < criteria.size_min:
            return False

        if criteria.size_max and message.size > criteria.size_max:
            return False

        return True

    def store(
        self,
        sequence: int | str | list[int],
        flags: set[Flag],
        action: str = "FLAGS",
    ) -> dict[int, set[Flag]]:
        """Store/modify flags on messages.

        Args:
            sequence: Message number(s)
            flags: Flags to store
            action: Action type (FLAGS, +FLAGS, -FLAGS)

        Returns:
            Dictionary of sequence -> flags
        """
        if self.state != IMAPState.SELECTED:
            raise IMAPError(f"Invalid state for STORE: {self.state}")

        results = {}
        sequence_nums = self._parse_sequence(sequence)

        for seq_num in sequence_nums:
            if seq_num in self.messages:
                message = self.messages[seq_num]
                if action == "FLAGS":
                    message.flags = flags.copy()
                elif action == "+FLAGS":
                    message.flags.update(flags)
                elif action == "-FLAGS":
                    message.flags -= flags

                results[seq_num] = message.flags.copy()

        return results

    def copy(
        self,
        sequence: int | str | list[int],
        mailbox: str,
    ) -> IMAPResponse:
        """Copy message(s) to another mailbox.

        Args:
            sequence: Message number(s)
            mailbox: Destination mailbox

        Returns:
            IMAP response
        """
        if self.state != IMAPState.SELECTED:
            raise IMAPError(f"Invalid state for COPY: {self.state}")

        if not self._validate_mailbox(mailbox):
            raise IMAPProtocolError(f"NO [TRYCREATE] Cannot copy to {mailbox}")

        sequence_nums = self._parse_sequence(sequence)

        for seq_num in sequence_nums:
            if seq_num in self.messages:
                if mailbox not in self.mailbox_data:
                    self.mailbox_data[mailbox] = {"EXISTS": 0, "RECENT": 0}
                self.mailbox_data[mailbox]["EXISTS"] += 1

        return IMAPResponse("OK", message=f"COPY completed for {len(sequence_nums)} messages")

    def expunge(self) -> list[int]:
        """Permanently delete messages marked with DELETED flag.

        Returns:
            List of expunged message sequence numbers
        """
        if self.state != IMAPState.SELECTED:
            raise IMAPError(f"Invalid state for EXPUNGE: {self.state}")

        expunged = []
        to_delete = [seq for seq, msg in self.messages.items() if Flag.DELETED in msg.flags]

        for seq in sorted(to_delete, reverse=True):
            del self.messages[seq]
            expunged.append(seq)

        return expunged

    def create(self, mailbox: str) -> IMAPResponse:
        """Create a new mailbox.

        Args:
            mailbox: Mailbox name

        Returns:
            IMAP response
        """
        if not self.authenticated:
            raise IMAPError("Not authenticated")

        if mailbox in self.mailbox_data:
            raise IMAPProtocolError(f"NO [ALREADYEXISTS] Mailbox {mailbox} already exists")

        self.mailbox_data[mailbox] = {"EXISTS": 0, "RECENT": 0}
        return IMAPResponse("OK", message=f"CREATE completed for {mailbox}")

    def delete(self, mailbox: str) -> IMAPResponse:
        """Delete a mailbox.

        Args:
            mailbox: Mailbox name

        Returns:
            IMAP response
        """
        if not self.authenticated:
            raise IMAPError("Not authenticated")

        if mailbox not in self.mailbox_data:
            raise IMAPProtocolError(f"NO [NONEXISTENT] Mailbox {mailbox} does not exist")

        del self.mailbox_data[mailbox]
        return IMAPResponse("OK", message=f"DELETE completed for {mailbox}")

    def list_mailboxes(self, reference: str = "", pattern: str = "*") -> list[Folder]:
        """List mailboxes matching pattern.

        Args:
            reference: Reference name (typically empty)
            pattern: Mailbox pattern (default: all)

        Returns:
            List of Folder objects
        """
        if not self.authenticated:
            raise IMAPError("Not authenticated")

        folders = []
        for mailbox_name in self.mailbox_data.keys():
            if self._matches_pattern(mailbox_name, pattern):
                stats = self.mailbox_data[mailbox_name]
                folder = Folder(
                    name=mailbox_name,
                    path=f"/{mailbox_name}",
                    message_count=stats.get("EXISTS", 0),
                    unread_count=stats.get("UNSEEN", 0),
                )
                folders.append(folder)

        return folders

    def _parse_sequence(self, sequence: int | str | list[int]) -> list[int]:
        """Parse message sequence specification.

        Args:
            sequence: Sequence specification (1, "1:5", [1,3,5])

        Returns:
            List of sequence numbers
        """
        if isinstance(sequence, int):
            return [sequence]
        elif isinstance(sequence, list):
            return sequence
        elif isinstance(sequence, str):
            if ":" in sequence:
                start, end = sequence.split(":")
                return list(range(int(start), int(end) + 1))
            else:
                return [int(sequence)]
        else:
            raise IMAPParseError(f"Invalid sequence: {sequence}")

    def _validate_mailbox(self, mailbox: str) -> bool:
        """Validate mailbox exists.

        Args:
            mailbox: Mailbox name

        Returns:
            True if mailbox exists
        """
        return mailbox in self.mailbox_data or mailbox == "INBOX"

    def _get_mailbox_stats(self, mailbox: str) -> dict[str, int]:
        """Get mailbox statistics.

        Args:
            mailbox: Mailbox name

        Returns:
            Dictionary with EXISTS, RECENT, UNSEEN counts
        """
        if mailbox == "INBOX":
            return {"EXISTS": 10, "RECENT": 2, "UNSEEN": 3}
        return self.mailbox_data.get(mailbox, {"EXISTS": 0, "RECENT": 0, "UNSEEN": 0})

    def _matches_pattern(self, mailbox_name: str, pattern: str) -> bool:
        """Check if mailbox matches LIST pattern.

        Args:
            mailbox_name: Mailbox name
            pattern: Pattern (supports * and %)

        Returns:
            True if mailbox matches
        """
        if pattern == "*":
            return True
        pattern_regex = pattern.replace("*", ".*").replace("%", "[^/]*")
        return re.match(f"^{pattern_regex}$", mailbox_name) is not None

    def logout(self) -> IMAPResponse:
        """Disconnect from server.

        Returns:
            IMAP response
        """
        self.state = IMAPState.DISCONNECTED
        self.authenticated = False
        return IMAPResponse("OK", message="LOGOUT completed")
