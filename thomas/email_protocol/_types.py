"""
Core type definitions for email protocol implementation.

Provides dataclasses and enums representing email messages, addresses,
headers, MIME parts, and protocol-specific structures.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ContentType(str, Enum):
    """MIME Content-Type values."""

    TEXT_PLAIN = "text/plain"
    TEXT_HTML = "text/html"
    TEXT_CSS = "text/css"
    MULTIPART_MIXED = "multipart/mixed"
    MULTIPART_ALTERNATIVE = "multipart/alternative"
    MULTIPART_RELATED = "multipart/related"
    MULTIPART_SIGNED = "multipart/signed"
    APPLICATION_JSON = "application/json"
    APPLICATION_PDF = "application/pdf"
    APPLICATION_OCTET_STREAM = "application/octet-stream"
    IMAGE_JPEG = "image/jpeg"
    IMAGE_PNG = "image/png"
    IMAGE_GIF = "image/gif"


class Encoding(str, Enum):
    """Content-Transfer-Encoding values."""

    PLAIN_7BIT = "7bit"
    PLAIN_8BIT = "8bit"
    BASE64 = "base64"
    QUOTED_PRINTABLE = "quoted-printable"
    BINARY = "binary"


class Priority(str, Enum):
    """Email priority levels."""

    HIGHEST = "highest"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    LOWEST = "lowest"


class Flag(str, Enum):
    """IMAP/Email flags."""

    SEEN = "\\Seen"
    ANSWERED = "\\Answered"
    FLAGGED = "\\Flagged"
    DELETED = "\\Deleted"
    DRAFT = "\\Draft"
    RECENT = "\\Recent"
    JUNK = "\\Junk"
    IMPORTANT = "\\Important"
    NOTJUNK = "\\NotJunk"


class SMTPCommand(str, Enum):
    """SMTP protocol commands."""

    EHLO = "EHLO"
    HELO = "HELO"
    MAIL = "MAIL"
    RCPT = "RCPT"
    DATA = "DATA"
    RSET = "RSET"
    VRFY = "VRFY"
    EXPN = "EXPN"
    HELP = "HELP"
    NOOP = "NOOP"
    QUIT = "QUIT"
    AUTH = "AUTH"
    STARTTLS = "STARTTLS"


class IMAPCommand(str, Enum):
    """IMAP protocol commands."""

    SELECT = "SELECT"
    EXAMINE = "EXAMINE"
    CREATE = "CREATE"
    DELETE = "DELETE"
    RENAME = "RENAME"
    LIST = "LIST"
    LSUB = "LSUB"
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    FETCH = "FETCH"
    STORE = "STORE"
    COPY = "COPY"
    MOVE = "MOVE"
    EXPUNGE = "EXPUNGE"
    SEARCH = "SEARCH"
    UID = "UID"
    LOGOUT = "LOGOUT"


@dataclass
class EmailAddress:
    """Represents an email address with optional display name.

    Attributes:
        address: Email address (user@domain.com)
        display_name: Optional display name for the sender/recipient
    """

    address: str
    display_name: str | None = None

    def __post_init__(self) -> None:
        """Validate email address format."""
        if not self._is_valid_email(self.address):
            raise ValueError(f"Invalid email address: {self.address}")

    @staticmethod
    def _is_valid_email(email: str) -> bool:
        """Check if email format is valid."""
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return re.match(pattern, email) is not None

    def __str__(self) -> str:
        """Return RFC 5322 formatted address."""
        if self.display_name:
            return f'"{self.display_name}" <{self.address}>'
        return self.address

    def to_tuple(self) -> tuple[str | None, str | None, str, str]:
        """Return (name, SMTP-at-host, mailbox, host) tuple for parsing."""
        parts = self.address.split("@")
        if len(parts) != 2:
            raise ValueError(f"Invalid email address: {self.address}")
        mailbox, host = parts
        return (self.display_name, None, mailbox, host)


@dataclass
class Header:
    """Represents a single email header.

    Attributes:
        name: Header name (e.g., 'Subject', 'From')
        value: Header value (may be encoded)
        is_encoded: Whether value uses RFC 2047 encoding
    """

    name: str
    value: str
    is_encoded: bool = False

    def get_decoded_value(self) -> str:
        """Decode RFC 2047 encoded header value if needed."""
        if not self.is_encoded:
            return self.value
        return self._decode_rfc2047(self.value)

    @staticmethod
    def _decode_rfc2047(encoded: str) -> str:
        """Decode RFC 2047 header: =?charset?encoding?text?="""
        pattern = r"=\?([^?]+)\?([QB])\?([^?]+)\?="
        matches = re.finditer(pattern, encoded, re.IGNORECASE)
        result = encoded
        for match in matches:
            charset, encoding_type, text = match.groups()
            if encoding_type.upper() == "B":
                import base64

                try:
                    decoded = base64.b64decode(text).decode(charset)
                    result = result.replace(match.group(0), decoded)
                except ImportError:
                    pass
            elif encoding_type.upper() == "Q":
                result = result.replace(match.group(0), text.replace("_", " "))
        return result


@dataclass
class MIMEPart:
    """Represents a MIME part within an email message.

    Attributes:
        content_type: MIME content type
        charset: Character encoding (default: utf-8)
        content_transfer_encoding: Transfer encoding method
        content: Raw content data
        headers: Additional MIME headers
        content_id: Content-ID for inline resources
        content_location: Content-Location for related resources
        is_inline: Whether content is displayed inline vs as attachment
    """

    content_type: ContentType
    content: bytes
    charset: str = "utf-8"
    content_transfer_encoding: Encoding = Encoding.PLAIN_7BIT
    headers: dict[str, str] = field(default_factory=dict)
    content_id: str | None = None
    content_location: str | None = None
    is_inline: bool = False

    def get_text(self) -> str:
        """Decode content to text string."""
        return self.content.decode(self.charset, errors="replace")

    def set_text(self, text: str) -> None:
        """Set content from text string."""
        self.content = text.encode(self.charset)


@dataclass
class Attachment:
    """Represents an email attachment.

    Attributes:
        filename: Name of the attachment file
        content: Raw file content
        content_type: MIME type of the file
        content_id: Optional Content-ID for embedded resources
        inline: Whether attachment is inline vs attachment
        size: Size in bytes
    """

    filename: str
    content: bytes
    content_type: str = ContentType.APPLICATION_OCTET_STREAM
    content_id: str | None = None
    inline: bool = False
    size: int = field(init=False)

    def __post_init__(self) -> None:
        """Calculate size on initialization."""
        self.size = len(self.content)


@dataclass
class ReturnReceipt:
    """Represents a return receipt request.

    Attributes:
        requested: Whether return receipt was requested
        recipient: Email of receipt recipient
        timestamp: When receipt was generated
    """

    requested: bool = False
    recipient: str | None = None
    timestamp: datetime | None = None


@dataclass
class Envelope:
    """Represents the envelope information of an email (metadata).

    Attributes:
        date: Date the message was sent
        subject: Message subject
        from_addr: Sender address
        sender: Sender address (may differ from From)
        reply_to: Reply-To addresses
        to_addrs: Primary recipients
        cc_addrs: Carbon copy recipients
        bcc_addrs: Blind carbon copy recipients
        in_reply_to: Message-ID of parent message
        message_id: Unique message identifier
        references: Message-IDs of related messages
    """

    date: datetime | None = None
    subject: str = ""
    from_addr: EmailAddress | None = None
    sender: EmailAddress | None = None
    reply_to: list[EmailAddress] = field(default_factory=list)
    to_addrs: list[EmailAddress] = field(default_factory=list)
    cc_addrs: list[EmailAddress] = field(default_factory=list)
    bcc_addrs: list[EmailAddress] = field(default_factory=list)
    in_reply_to: str | None = None
    message_id: str | None = None
    references: list[str] = field(default_factory=list)


@dataclass
class EmailMessage:
    """Represents a complete email message.

    Attributes:
        envelope: Message envelope (headers metadata)
        headers: Dictionary of all headers
        text_body: Plain text body
        html_body: HTML body
        mime_parts: List of MIME parts for multipart messages
        attachments: List of file attachments
        flags: IMAP flags (seen, answered, etc.)
        priority: Message priority level
        return_receipt: Return receipt request
        uid: Unique identifier (set by server)
        sequence_number: IMAP sequence number
        size: Message size in bytes
    """

    envelope: Envelope = field(default_factory=Envelope)
    headers: dict[str, list[str]] = field(default_factory=dict)
    text_body: str | None = None
    html_body: str | None = None
    mime_parts: list[MIMEPart] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    flags: set[Flag] = field(default_factory=set)
    priority: Priority = Priority.NORMAL
    return_receipt: ReturnReceipt = field(default_factory=ReturnReceipt)
    uid: int | None = None
    sequence_number: int | None = None
    size: int = 0

    def add_flag(self, flag: Flag) -> None:
        """Add a flag to the message."""
        self.flags.add(flag)

    def remove_flag(self, flag: Flag) -> None:
        """Remove a flag from the message."""
        self.flags.discard(flag)

    def has_flag(self, flag: Flag) -> bool:
        """Check if message has a specific flag."""
        return flag in self.flags

    def is_multipart(self) -> bool:
        """Check if message is multipart."""
        return len(self.mime_parts) > 0

    def get_all_recipients(self) -> list[EmailAddress]:
        """Get all recipients (To + CC + BCC)."""
        return self.envelope.to_addrs + self.envelope.cc_addrs + self.envelope.bcc_addrs


@dataclass
class SearchCriteria:
    """Represents IMAP search criteria.

    Attributes:
        from_addr: Search by From header
        to_addr: Search by To header
        subject: Search by Subject
        body: Search in message body
        before: Messages before date
        since: Messages since date
        seen: Filter by seen/unseen status
        flagged: Filter by flagged status
        deleted: Include deleted messages
        size_min: Minimum message size
        size_max: Maximum message size
    """

    from_addr: str | None = None
    to_addr: str | None = None
    subject: str | None = None
    body: str | None = None
    before: datetime | None = None
    since: datetime | None = None
    seen: bool | None = None
    flagged: bool | None = None
    deleted: bool = False
    size_min: int | None = None
    size_max: int | None = None


@dataclass
class Folder:
    """Represents an email folder/mailbox.

    Attributes:
        name: Folder name
        path: Full folder path (e.g., 'INBOX/Subdir')
        parent: Parent folder path
        message_count: Number of messages
        unread_count: Number of unread messages
        subscribed: Whether folder is subscribed
        can_have_children: Whether folder can contain subfolders
        children: Names of child folders
        attributes: IMAP folder attributes
    """

    name: str
    path: str
    parent: str | None = None
    message_count: int = 0
    unread_count: int = 0
    subscribed: bool = False
    can_have_children: bool = True
    children: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)


@dataclass
class Mailbox:
    """Represents a mailbox/account.

    Attributes:
        name: Mailbox name/label
        folder: Root folder
        quota_usage: Current quota usage in bytes
        quota_limit: Quota limit in bytes
        recent_count: Number of recent messages
        exists_count: Total number of messages
    """

    name: str
    folder: Folder = field(default_factory=lambda: Folder("ROOT", "/"))
    quota_usage: int = 0
    quota_limit: int = 0
    recent_count: int = 0
    exists_count: int = 0

    def quota_percent(self) -> float:
        """Calculate quota usage percentage."""
        if self.quota_limit == 0:
            return 0.0
        return (self.quota_usage / self.quota_limit) * 100
