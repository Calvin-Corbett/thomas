"""
Email header processing and parsing.

Implements RFC 5322 and RFC 2822 header parsing including address parsing,
date parsing, Message-ID generation, and header encoding.
"""

import re
import time
import uuid
from datetime import datetime, timezone

from thomas.email_protocol._types import EmailAddress


class HeaderParser:
    """Parser for email headers.

    Handles structured headers (From, To, Date, Message-ID) and
    unstructured headers (Subject, comments).
    """

    # RFC 5322 email address pattern
    EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"

    @staticmethod
    def parse_address(address_str: str) -> EmailAddress | None:
        """Parse RFC 5322 address format.

        Supports formats:
        - user@domain.com
        - Display Name <user@domain.com>
        - "Display Name" <user@domain.com>
        - user@domain.com (Display Name)

        Args:
            address_str: Raw address string

        Returns:
            Parsed EmailAddress or None if invalid

        Raises:
            ValueError: If address format is invalid
        """
        address_str = address_str.strip()

        if not address_str:
            return None

        display_name = None
        email_addr = None

        if "<" in address_str and ">" in address_str:
            match = re.match(r"^(.*?)\s*<([^>]+)>", address_str)
            if match:
                display_name = match.group(1).strip().strip('"')
                email_addr = match.group(2).strip()
        else:
            match = re.search(HeaderParser.EMAIL_PATTERN, address_str)
            if match:
                email_addr = match.group(0)
                display_name_part = address_str[: match.start()].strip()
                if display_name_part and not display_name_part.endswith("("):
                    display_name = display_name_part.strip('"')

        if email_addr:
            return EmailAddress(email_addr, display_name or None)

        raise ValueError(f"Invalid email address: {address_str}")

    @staticmethod
    def parse_address_list(address_list_str: str) -> list[EmailAddress]:
        """Parse comma-separated list of addresses.

        Args:
            address_list_str: Comma-separated addresses

        Returns:
            List of EmailAddress objects
        """
        addresses = []

        if not address_list_str:
            return addresses

        for addr in address_list_str.split(","):
            try:
                parsed = HeaderParser.parse_address(addr.strip())
                if parsed:
                    addresses.append(parsed)
            except ValueError:
                continue

        return addresses

    @staticmethod
    def parse_date(date_str: str) -> datetime | None:
        """Parse RFC 2822 date format.

        Supports formats:
        - Wed, 3 Nov 2021 12:34:56 +0000
        - 3 Nov 2021 12:34:56 +0000
        - Mon, 01 Jan 2001 00:00:00 GMT

        Args:
            date_str: Date string to parse

        Returns:
            Parsed datetime or None if parse fails
        """
        date_str = date_str.strip()

        if not date_str:
            return None

        import email.utils

        try:
            timestamp = email.utils.parsedate_to_datetime(date_str)
            return timestamp
        except (TypeError, ValueError):
            pass

        months = {
            "Jan": 1,
            "Feb": 2,
            "Mar": 3,
            "Apr": 4,
            "May": 5,
            "Jun": 6,
            "Jul": 7,
            "Aug": 8,
            "Sep": 9,
            "Oct": 10,
            "Nov": 11,
            "Dec": 12,
        }

        pattern = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun,?)?\s*(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})\s*([\+\-]\d{4})"
        match = re.search(pattern, date_str)

        if match:
            day, month_str, year, hour, minute, second, tz_str = match.groups()
            try:
                month = months[month_str]
                tz_hours = int(tz_str[:3])
                tz_minutes = int(tz_str[3:])
                tz_offset = timezone(timezone.utc.utcoffset(None) if tz_hours == 0 else timezone(timezone.utc).tzinfo)

                return datetime(int(year), month, int(day), int(hour), int(minute), int(second))
            except (ValueError, TypeError):
                pass

        return None

    @staticmethod
    def parse_message_id(message_id_str: str) -> str | None:
        """Extract and validate Message-ID.

        Args:
            message_id_str: Message-ID header value

        Returns:
            Validated Message-ID or None
        """
        message_id_str = message_id_str.strip()

        if not message_id_str:
            return None

        match = re.search(r"<([^>]+)>", message_id_str)
        if match:
            return match.group(1)

        if "@" in message_id_str and not message_id_str.startswith("<"):
            return message_id_str

        return None

    @staticmethod
    def parse_received_header(received_str: str) -> dict[str, str]:
        """Parse Received header chain for routing analysis.

        Args:
            received_str: Received header value

        Returns:
            Dictionary with extracted routing information
        """
        result = {
            "from": None,
            "by": None,
            "with": None,
            "date": None,
            "raw": received_str,
        }

        # Extract "from" field
        match = re.search(r"from\s+([^\s]+)", received_str, re.IGNORECASE)
        if match:
            result["from"] = match.group(1)

        # Extract "by" field
        match = re.search(r"by\s+([^\s]+)", received_str, re.IGNORECASE)
        if match:
            result["by"] = match.group(1)

        # Extract "with" field (protocol)
        match = re.search(r"with\s+([^\s]+)", received_str, re.IGNORECASE)
        if match:
            result["with"] = match.group(1)

        # Extract date (typically after "for" or at end)
        match = re.search(r";\s*(.+?)$", received_str)
        if match:
            date_str = match.group(1)
            result["date"] = HeaderParser.parse_date(date_str)

        return result


class HeaderBuilder:
    """Builder for constructing email headers."""

    def __init__(self) -> None:
        """Initialize header builder."""
        self.headers: dict[str, str] = {}

    def set_from(self, address: EmailAddress) -> None:
        """Set From header.

        Args:
            address: Sender address
        """
        self.headers["From"] = str(address)

    def set_to(self, addresses: list[EmailAddress]) -> None:
        """Set To header.

        Args:
            addresses: Recipient addresses
        """
        self.headers["To"] = ", ".join(str(addr) for addr in addresses)

    def set_cc(self, addresses: list[EmailAddress]) -> None:
        """Set Cc header.

        Args:
            addresses: CC addresses
        """
        if addresses:
            self.headers["Cc"] = ", ".join(str(addr) for addr in addresses)

    def set_bcc(self, addresses: list[EmailAddress]) -> None:
        """Set Bcc header (typically not included in message).

        Args:
            addresses: BCC addresses
        """
        if addresses:
            self.headers["Bcc"] = ", ".join(str(addr) for addr in addresses)

    def set_subject(self, subject: str) -> None:
        """Set Subject header.

        Args:
            subject: Subject line
        """
        self.headers["Subject"] = subject

    def set_date(self, dt: datetime | None = None) -> None:
        """Set Date header in RFC 2822 format.

        Args:
            dt: Datetime object (default: current time)
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        import email.utils

        date_str = email.utils.formatdate(timeval=dt.timestamp(), localtime=False, usegmt=True)
        self.headers["Date"] = date_str

    def set_message_id(self, hostname: str | None = None) -> None:
        """Set Message-ID header with unique identifier.

        Args:
            hostname: Hostname for Message-ID (default: local)
        """
        if hostname is None:
            hostname = "local"

        timestamp = int(time.time())
        unique_id = uuid.uuid4().hex[:12]
        message_id = f"<{timestamp}.{unique_id}@{hostname}>"
        self.headers["Message-ID"] = message_id

    def set_in_reply_to(self, message_id: str) -> None:
        """Set In-Reply-To header for threading.

        Args:
            message_id: Parent message-ID
        """
        self.headers["In-Reply-To"] = message_id

    def set_references(self, message_ids: list[str]) -> None:
        """Set References header for threading.

        Args:
            message_ids: List of parent message-IDs
        """
        if message_ids:
            self.headers["References"] = " ".join(message_ids)

    def set_reply_to(self, addresses: list[EmailAddress]) -> None:
        """Set Reply-To header.

        Args:
            addresses: Reply-to addresses
        """
        if addresses:
            self.headers["Reply-To"] = ", ".join(str(addr) for addr in addresses)

    def set_header(self, name: str, value: str) -> None:
        """Set arbitrary header.

        Args:
            name: Header name
            value: Header value
        """
        self.headers[name] = value

    def build(self) -> dict[str, str]:
        """Build header dictionary.

        Returns:
            Dictionary of headers
        """
        return self.headers.copy()

    def build_string(self) -> str:
        """Build headers as string.

        Returns:
            Headers formatted as string
        """
        lines = []
        for name, value in self.headers.items():
            lines.append(f"{name}: {value}")
        return "\r\n".join(lines) + "\r\n"


def normalize_subject(subject: str) -> str:
    """Normalize subject for threading (strip Re:/Fwd:).

    Args:
        subject: Original subject line

    Returns:
        Normalized subject
    """
    subject = subject.strip()

    while True:
        if subject.lower().startswith("re:"):
            subject = subject[3:].strip()
        elif subject.lower().startswith("fwd:"):
            subject = subject[4:].strip()
        elif subject.lower().startswith("fw:"):
            subject = subject[3:].strip()
        else:
            break

    return subject


def generate_message_id(hostname: str) -> str:
    """Generate unique Message-ID.

    Args:
        hostname: Hostname to include in ID

    Returns:
        Unique Message-ID string
    """
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:12]
    return f"<{timestamp}.{unique_id}@{hostname}>"
