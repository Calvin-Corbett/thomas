"""
Email protocol module: SMTP, IMAP, POP3, and MIME implementations.

This package provides complete implementations of email protocols with
full type annotations, docstrings, and real algorithms.
"""

from thomas.marketplace.email_protocol._exceptions import (
    AuthenticationError,
    ConnectionError,
    EmailProtocolError,
    IMAPError,
    MIMEError,
    POP3Error,
    SMTPError,
)
from thomas.marketplace.email_protocol._types import (
    Attachment,
    ContentType,
    EmailAddress,
    EmailMessage,
    Encoding,
    Envelope,
    Flag,
    Folder,
    Header,
    IMAPCommand,
    Mailbox,
    MIMEPart,
    Priority,
    ReturnReceipt,
    SearchCriteria,
    SMTPCommand,
)

__all__ = [
    "EmailMessage",
    "EmailAddress",
    "Header",
    "MIMEPart",
    "Attachment",
    "Envelope",
    "Mailbox",
    "Folder",
    "Flag",
    "SearchCriteria",
    "SMTPCommand",
    "IMAPCommand",
    "ContentType",
    "Encoding",
    "Priority",
    "ReturnReceipt",
    "EmailProtocolError",
    "SMTPError",
    "IMAPError",
    "POP3Error",
    "MIMEError",
    "AuthenticationError",
    "ConnectionError",
]

__version__ = "1.0.0"
