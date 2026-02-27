"""
Exception classes for email protocol implementations.

Provides specific exception types for different protocol errors and
conditions encountered during email operations.
"""


class EmailProtocolError(Exception):
    """Base exception for all email protocol errors."""

    pass


class SMTPError(EmailProtocolError):
    """Base exception for SMTP protocol errors."""

    def __init__(self, message: str, status_code: int = 0) -> None:
        """Initialize SMTP error with optional status code.

        Args:
            message: Error message
            status_code: SMTP response status code
        """
        super().__init__(message)
        self.status_code = status_code


class SMTPAuthenticationError(SMTPError):
    """Raised when SMTP authentication fails."""

    pass


class SMTPDataError(SMTPError):
    """Raised when SMTP data transmission fails."""

    pass


class SMTPSenderRefused(SMTPError):
    """Raised when SMTP server refuses sender."""

    pass


class SMTPRecipientsRefused(SMTPError):
    """Raised when SMTP server refuses one or more recipients."""

    pass


class IMAPError(EmailProtocolError):
    """Base exception for IMAP protocol errors."""

    pass


class IMAPAuthenticationError(IMAPError):
    """Raised when IMAP authentication fails."""

    pass


class IMAPParseError(IMAPError):
    """Raised when IMAP response parsing fails."""

    pass


class IMAPProtocolError(IMAPError):
    """Raised when IMAP protocol violation occurs."""

    pass


class POP3Error(EmailProtocolError):
    """Base exception for POP3 protocol errors."""

    pass


class POP3AuthenticationError(POP3Error):
    """Raised when POP3 authentication fails."""

    pass


class POP3CommandError(POP3Error):
    """Raised when POP3 command fails."""

    pass


class MIMEError(EmailProtocolError):
    """Base exception for MIME processing errors."""

    pass


class MIMEParseError(MIMEError):
    """Raised when MIME parsing fails."""

    pass


class MIMEEncodingError(MIMEError):
    """Raised when MIME encoding/decoding fails."""

    pass


class AuthenticationError(EmailProtocolError):
    """Raised when authentication fails across protocols."""

    pass


class ConnectionError(EmailProtocolError):
    """Raised when connection establishment fails."""

    pass


class TimeoutError(EmailProtocolError):
    """Raised when operation times out."""

    pass
