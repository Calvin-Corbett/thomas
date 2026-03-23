"""
Tests for SMTP protocol implementation.

Tests SMTP client state machine, command generation, response parsing,
authentication, and message transmission.
"""

import pytest

from thomas.marketplace.email_protocol._exceptions import (
    SMTPAuthenticationError,
    SMTPError,
    SMTPRecipientsRefused,
    SMTPSenderRefused,
)
from thomas.marketplace.email_protocol._types import EmailAddress, EmailMessage
from thomas.marketplace.email_protocol.smtp import (
    SMTPClient,
    SMTPResponse,
    SMTPState,
)


class TestSMTPClient:
    """Test SMTP client implementation."""

    def test_client_initialization(self):
        """Test SMTP client initialization."""
        client = SMTPClient("smtp.example.com", 587)

        assert client.hostname == "smtp.example.com"
        assert client.port == 587
        assert client.state == SMTPState.DISCONNECTED

    def test_connect(self):
        """Test SMTP connection."""
        client = SMTPClient("smtp.example.com")
        response = client.connect()

        assert response.is_success
        assert client.state == SMTPState.CONNECTED

    def test_cannot_connect_twice(self):
        """Test cannot connect when already connected."""
        client = SMTPClient("smtp.example.com")
        client.connect()

        with pytest.raises(SMTPError):
            client.connect()

    def test_ehlo_command(self):
        """Test EHLO command."""
        client = SMTPClient("smtp.example.com")
        client.connect()

        response = client.ehlo("client.local")
        assert response.is_success
        assert "SIZE" in client.extensions
        assert "AUTH" in client.extensions

    def test_ehlo_parses_extensions(self):
        """Test EHLO parses server extensions."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()

        assert client.server_supports_8bitmime
        assert client.server_supports_pipelining

    def test_auth_plain(self):
        """Test PLAIN authentication."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()

        response = client.auth_plain("user@example.com", "password123")
        assert response.is_success
        assert client.authenticated

    def test_auth_plain_invalid_credentials(self):
        """Test PLAIN auth with invalid credentials."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()

        with pytest.raises(SMTPAuthenticationError):
            client.auth_plain("user@example.com", "short")

    def test_auth_login(self):
        """Test LOGIN authentication."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()

        response = client.auth_login("user@example.com", "password123")
        assert response.is_success
        assert client.authenticated

    def test_mail_from(self):
        """Test MAIL FROM command."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")

        sender = EmailAddress("sender@example.com")
        response = client.mail_from(sender)

        assert response.is_success
        assert client.current_from == sender

    def test_mail_from_invalid_sender(self):
        """Test MAIL FROM with invalid sender."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")

        with pytest.raises((SMTPSenderRefused, ValueError)):
            client.mail_from(EmailAddress("invalid"))

    def test_rcpt_to(self):
        """Test RCPT TO command."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")
        client.mail_from(EmailAddress("sender@example.com"))

        recipient = EmailAddress("recipient@example.com")
        response = client.rcpt_to(recipient)

        assert response.is_success
        assert recipient in client.current_recipients

    def test_rcpt_to_multiple(self):
        """Test multiple RCPT TO commands."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")
        client.mail_from(EmailAddress("sender@example.com"))

        client.rcpt_to(EmailAddress("recipient1@example.com"))
        client.rcpt_to(EmailAddress("recipient2@example.com"))

        assert len(client.current_recipients) == 2

    def test_rcpt_to_invalid_recipient(self):
        """Test RCPT TO with invalid recipient."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")
        client.mail_from(EmailAddress("sender@example.com"))

        with pytest.raises((SMTPRecipientsRefused, ValueError)):
            client.rcpt_to(EmailAddress("invalid"))

    def test_data_command(self):
        """Test DATA command."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")
        client.mail_from(EmailAddress("sender@example.com"))
        client.rcpt_to(EmailAddress("recipient@example.com"))

        message = EmailMessage()
        message.envelope.subject = "Test"
        response = client.data(message)

        assert response.is_continuation

    def test_data_requires_recipients(self):
        """Test DATA requires at least one recipient."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()
        client.auth_plain("user@example.com", "password123")
        client.mail_from(EmailAddress("sender@example.com"))

        message = EmailMessage()
        with pytest.raises(SMTPError):
            client.data(message)

    def test_quit(self):
        """Test QUIT command."""
        client = SMTPClient("smtp.example.com")
        client.connect()

        response = client.quit()
        assert response.is_success

    def test_state_machine_progression(self):
        """Test proper state machine progression."""
        client = SMTPClient("smtp.example.com")
        states = []

        client.connect()
        states.append(client.state)

        client.ehlo()
        states.append(client.state)

        client.auth_plain("user@example.com", "password123")
        states.append(client.state)

        client.mail_from(EmailAddress("sender@example.com"))
        states.append(client.state)

        client.rcpt_to(EmailAddress("recipient@example.com"))
        states.append(client.state)

        assert SMTPState.CONNECTED in states
        assert SMTPState.EHLO_SENT in states
        assert SMTPState.AUTHENTICATED in states


class TestSMTPResponse:
    """Test SMTP response handling."""

    def test_success_response(self):
        """Test successful response."""
        response = SMTPResponse(250, "OK")
        assert response.is_success

    def test_continuation_response(self):
        """Test continuation response."""
        response = SMTPResponse(354, "Start mail input")
        assert response.is_continuation
        assert response.is_success

    def test_error_response(self):
        """Test error response."""
        response = SMTPResponse(550, "User not found")
        assert not response.is_success

    def test_status_codes(self):
        """Test various SMTP status codes."""
        test_cases = [
            (220, True, False),
            (250, True, False),
            (354, True, True),
            (500, False, False),
            (550, False, False),
        ]

        for code, success, continuation in test_cases:
            response = SMTPResponse(code, "test")
            assert response.is_success == success
            assert response.is_continuation == continuation


class TestSMTPAuthentication:
    """Test authentication mechanisms."""

    def test_auth_string_generation(self):
        """Test PLAIN auth string generation."""
        username = "user@example.com"
        password = "password123"
        auth_string = f"\0{username}\0{password}"

        import base64

        encoded = base64.b64encode(auth_string.encode()).decode()
        assert len(encoded) > 0

    def test_multiple_auth_attempts(self):
        """Test multiple authentication attempts."""
        client = SMTPClient("smtp.example.com")
        client.connect()
        client.ehlo()

        with pytest.raises(SMTPAuthenticationError):
            client.auth_plain("user@example.com", "bad")

        response = client.auth_plain("user@example.com", "good_password")
        assert response.is_success


class TestSMTPMessageConstruction:
    """Test message construction for transmission."""

    def test_build_simple_message(self):
        """Test building simple message."""
        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")
        message.envelope.to_addrs = [EmailAddress("recipient@example.com")]
        message.envelope.subject = "Test"
        message.text_body = "Hello World"

        client = SMTPClient("smtp.example.com")
        body = client._build_message_body(message)

        assert "From: sender@example.com" in body
        assert "To: recipient@example.com" in body
        assert "Subject: Test" in body
        assert "Hello World" in body

    def test_build_message_with_cc(self):
        """Test building message with CC."""
        message = EmailMessage()
        message.envelope.from_addr = EmailAddress("sender@example.com")
        message.envelope.to_addrs = [EmailAddress("recipient@example.com")]
        message.envelope.cc_addrs = [EmailAddress("cc@example.com")]
        message.envelope.subject = "Test"
        message.text_body = "Content"

        client = SMTPClient("smtp.example.com")
        body = client._build_message_body(message)

        assert "Cc: cc@example.com" in body
