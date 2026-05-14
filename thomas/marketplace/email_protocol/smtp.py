"""
SMTP protocol implementation.

Implements SMTP client state machine with command generation, response
parsing, authentication mechanisms, and message transmission.
"""

import base64
from dataclasses import dataclass
from enum import Enum

from thomas.marketplace.email_protocol._exceptions import (
    SMTPAuthenticationError,
    SMTPError,
    SMTPRecipientsRefused,
    SMTPSenderRefused,
)
from thomas.marketplace.email_protocol._types import EmailAddress, EmailMessage


class SMTPState(Enum):
    """SMTP client state machine states."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    EHLO_SENT = "ehlo_sent"
    AUTH_PLAIN = "auth_plain"
    AUTH_LOGIN = "auth_login"
    AUTHENTICATED = "authenticated"
    MAIL_FROM_SENT = "mail_from_sent"
    RCPT_TO_SENT = "rcpt_to_sent"
    DATA_SENT = "data_sent"
    MESSAGE_BODY_SENT = "message_body_sent"
    QUIT_SENT = "quit_sent"


@dataclass
class SMTPResponse:
    """Represents SMTP server response.

    Attributes:
        status_code: 3-digit SMTP response code
        message: Response text
        is_success: Whether response indicates success
        is_continuation: Whether response requires continuation
    """

    status_code: int
    message: str
    is_success: bool = False
    is_continuation: bool = False

    def __post_init__(self) -> None:
        """Determine success and continuation based on status code."""
        if 200 <= self.status_code < 300:
            self.is_success = True
        elif 300 <= self.status_code < 400:
            self.is_success = True
            self.is_continuation = True


class SMTPClient:
    """SMTP protocol client implementation.

    Handles connection state, command generation and parsing, authentication,
    and message transmission using proper state machine.
    """

    def __init__(self, hostname: str, port: int = 587) -> None:
        """Initialize SMTP client.

        Args:
            hostname: SMTP server hostname
            port: SMTP server port (default 587 for TLS)
        """
        self.hostname = hostname
        self.port = port
        self.state = SMTPState.DISCONNECTED
        self.extensions: dict[str, list[str]] = {}
        self.server_greeting: str | None = None
        self.authenticated = False
        self.current_from: EmailAddress | None = None
        self.current_recipients: list[EmailAddress] = []
        self.server_supports_8bitmime = False
        self.server_supports_pipelining = False

    def connect(self) -> SMTPResponse:
        """Simulate SMTP connection and capture server greeting.

        Returns:
            SMTP response from server

        Raises:
            SMTPError: If connection fails
        """
        if self.state != SMTPState.DISCONNECTED:
            raise SMTPError("Already connected")

        self.state = SMTPState.CONNECTED
        self.server_greeting = f"220 {self.hostname} ESMTP ready"
        return self._parse_response(self.server_greeting)

    def ehlo(self, client_hostname: str = "client.local") -> SMTPResponse:
        """Send EHLO command to initiate extended SMTP.

        Args:
            client_hostname: Client hostname to send in command

        Returns:
            SMTP response with server capabilities

        Raises:
            SMTPError: If command fails or invalid state
        """
        if self.state != SMTPState.CONNECTED:
            raise SMTPError(f"Invalid state for EHLO: {self.state}")

        self.state = SMTPState.EHLO_SENT

        response_lines = [
            f"250-{self.hostname} Hello {client_hostname}",
            "250-SIZE 52428800",
            "250-8BITMIME",
            "250-AUTH PLAIN LOGIN",
            "250-STARTTLS",
            "250-PIPELINING",
            "250 HELP",
        ]

        self._parse_extensions(response_lines)
        self.server_supports_8bitmime = "8BITMIME" in self.extensions
        self.server_supports_pipelining = "PIPELINING" in self.extensions

        return SMTPResponse(250, "\r\n".join(response_lines), is_success=True)

    def _parse_extensions(self, response_lines: list[str]) -> None:
        """Parse EHLO response to extract server extensions.

        Args:
            response_lines: Response lines from EHLO command
        """
        for line in response_lines[1:]:
            if len(line) > 3 and line[3] in "-+ ":
                remainder = line[4:]
            else:
                remainder = line

            parts = remainder.split()
            if len(parts) >= 1:
                ext_name = parts[0].upper()
                ext_params = parts[1:] if len(parts) > 1 else []
                self.extensions[ext_name] = ext_params

    def auth_plain(self, username: str, password: str) -> SMTPResponse:
        """Authenticate using PLAIN mechanism.

        Args:
            username: Email or username
            password: Password

        Returns:
            SMTP response

        Raises:
            SMTPAuthenticationError: If authentication fails
        """
        if self.state != SMTPState.EHLO_SENT:
            raise SMTPError(f"Invalid state for AUTH: {self.state}")

        if "AUTH" not in self.extensions:
            raise SMTPError("Server does not support AUTH")

        auth_string = f"\0{username}\0{password}"
        base64.b64encode(auth_string.encode()).decode()
        self.state = SMTPState.AUTH_PLAIN

        if self._simulate_auth_success(username, password):
            self.authenticated = True
            self.state = SMTPState.AUTHENTICATED
            return SMTPResponse(235, "2.7.0 Authentication successful", is_success=True)
        else:
            self.state = SMTPState.EHLO_SENT
            raise SMTPAuthenticationError("535 5.7.8 Authentication credentials invalid", 535)

    def auth_login(self, username: str, password: str) -> SMTPResponse:
        """Authenticate using LOGIN mechanism.

        Args:
            username: Email or username
            password: Password

        Returns:
            SMTP response

        Raises:
            SMTPAuthenticationError: If authentication fails
        """
        if self.state != SMTPState.EHLO_SENT:
            raise SMTPError(f"Invalid state for AUTH: {self.state}")

        self.state = SMTPState.AUTH_LOGIN

        if self._simulate_auth_success(username, password):
            self.authenticated = True
            self.state = SMTPState.AUTHENTICATED
            return SMTPResponse(235, "2.7.0 Authentication successful", is_success=True)
        else:
            self.state = SMTPState.EHLO_SENT
            raise SMTPAuthenticationError("535 5.7.8 Authentication credentials invalid", 535)

    def _simulate_auth_success(self, username: str, password: str) -> bool:
        """Simulate authentication validation.

        Args:
            username: Username to validate
            password: Password to validate

        Returns:
            True if credentials are valid (simulated)
        """
        return len(username) > 0 and len(password) >= 8

    def mail_from(self, from_addr: EmailAddress) -> SMTPResponse:
        """Send MAIL FROM command.

        Args:
            from_addr: Sender email address

        Returns:
            SMTP response

        Raises:
            SMTPError: If command fails or invalid state
        """
        if self.state != SMTPState.AUTHENTICATED:
            raise SMTPError(f"Invalid state for MAIL: {self.state}")

        self.current_from = from_addr
        self.current_recipients = []
        self.state = SMTPState.MAIL_FROM_SENT

        if self._simulate_sender_validation(from_addr):
            return SMTPResponse(250, "2.1.0 OK", is_success=True)
        else:
            raise SMTPSenderRefused(f"550 5.1.1 Sender rejected: {from_addr.address}", 550)

    def rcpt_to(self, to_addr: EmailAddress) -> SMTPResponse:
        """Send RCPT TO command.

        Args:
            to_addr: Recipient email address

        Returns:
            SMTP response

        Raises:
            SMTPError: If command fails or invalid state
        """
        if self.state not in (
            SMTPState.MAIL_FROM_SENT,
            SMTPState.RCPT_TO_SENT,
        ):
            raise SMTPError(f"Invalid state for RCPT: {self.state}")

        self.state = SMTPState.RCPT_TO_SENT

        if self._simulate_recipient_validation(to_addr):
            self.current_recipients.append(to_addr)
            return SMTPResponse(250, "2.1.5 OK", is_success=True)
        else:
            raise SMTPRecipientsRefused(f"550 5.1.1 Recipient rejected: {to_addr.address}", 550)

    def data(self, message: EmailMessage) -> SMTPResponse:
        """Send DATA command and message body.

        Args:
            message: Email message to send

        Returns:
            SMTP response

        Raises:
            SMTPError: If command fails or invalid state
        """
        if self.state != SMTPState.RCPT_TO_SENT:
            raise SMTPError(f"Invalid state for DATA: {self.state}")

        if not self.current_recipients:
            raise SMTPError("No recipients specified")

        self.state = SMTPState.DATA_SENT

        response = SMTPResponse(354, "Start mail input; end with <CRLF>.<CRLF>", is_success=True, is_continuation=True)

        self._build_message_body(message)
        self.state = SMTPState.MESSAGE_BODY_SENT

        return response

    def _build_message_body(self, message: EmailMessage) -> str:
        """Build message body from EmailMessage object.

        Args:
            message: Email message

        Returns:
            Formatted message body
        """
        lines = []

        if message.envelope.from_addr:
            lines.append(f"From: {message.envelope.from_addr}")

        if message.envelope.to_addrs:
            to_list = ", ".join(str(addr) for addr in message.envelope.to_addrs)
            lines.append(f"To: {to_list}")

        if message.envelope.cc_addrs:
            cc_list = ", ".join(str(addr) for addr in message.envelope.cc_addrs)
            lines.append(f"Cc: {cc_list}")

        if message.envelope.subject:
            lines.append(f"Subject: {message.envelope.subject}")

        if message.envelope.message_id:
            lines.append(f"Message-ID: {message.envelope.message_id}")

        lines.append("")
        if message.text_body:
            lines.append(message.text_body)

        return "\r\n".join(lines)

    def quit(self) -> SMTPResponse:
        """Send QUIT command to close connection.

        Returns:
            SMTP response
        """
        self.state = SMTPState.QUIT_SENT
        return SMTPResponse(221, "2.0.0 Goodbye", is_success=True)

    def _simulate_sender_validation(self, sender: EmailAddress) -> bool:
        """Simulate sender validation.

        Args:
            sender: Sender address to validate

        Returns:
            True if sender is valid (simulated)
        """
        return "@" in sender.address and len(sender.address) > 3

    def _simulate_recipient_validation(self, recipient: EmailAddress) -> bool:
        """Simulate recipient validation.

        Args:
            recipient: Recipient to validate

        Returns:
            True if recipient is valid (simulated)
        """
        return "@" in recipient.address and len(recipient.address) > 3

    def _parse_response(self, response_line: str) -> SMTPResponse:
        """Parse SMTP response line.

        Args:
            response_line: Raw response line from server

        Returns:
            Parsed SMTP response

        Raises:
            SMTPError: If response is malformed
        """
        parts = response_line.split(" ", 1)
        if not parts or not parts[0].isdigit():
            raise SMTPError(f"Malformed response: {response_line}")

        status_code = int(parts[0])
        message = parts[1] if len(parts) > 1 else ""

        return SMTPResponse(status_code, message)

    def reset(self) -> None:
        """Reset connection state for new message."""
        self.current_from = None
        self.current_recipients = []
        if self.authenticated:
            self.state = SMTPState.AUTHENTICATED
        else:
            self.state = SMTPState.EHLO_SENT
