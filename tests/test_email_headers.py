"""
Tests for email header processing.

Tests RFC 5322 address parsing, date parsing, header building,
and Message-ID generation.
"""

from datetime import datetime, timezone

import pytest

from thomas.email_protocol._types import EmailAddress
from thomas.email_protocol.headers import (
    HeaderBuilder,
    HeaderParser,
    generate_message_id,
    normalize_subject,
)


class TestHeaderParser:
    """Test header parsing functionality."""

    def test_parse_simple_address(self):
        """Test parsing simple email address."""
        addr_str = "user@example.com"
        addr = HeaderParser.parse_address(addr_str)

        assert addr.address == "user@example.com"
        assert addr.display_name is None

    def test_parse_address_with_display_name(self):
        """Test parsing address with display name."""
        addr_str = "John Doe <john@example.com>"
        addr = HeaderParser.parse_address(addr_str)

        assert addr.address == "john@example.com"
        assert addr.display_name == "John Doe"

    def test_parse_quoted_display_name(self):
        """Test parsing quoted display name."""
        addr_str = '"John Doe" <john@example.com>'
        addr = HeaderParser.parse_address(addr_str)

        assert addr.address == "john@example.com"
        assert addr.display_name == "John Doe"

    def test_parse_invalid_address_raises_error(self):
        """Test invalid address raises ValueError."""
        with pytest.raises(ValueError):
            HeaderParser.parse_address("not_an_email")

    def test_parse_address_list(self):
        """Test parsing comma-separated addresses."""
        addr_list_str = "user1@example.com, user2@example.com"
        addrs = HeaderParser.parse_address_list(addr_list_str)

        assert len(addrs) == 2
        assert addrs[0].address == "user1@example.com"
        assert addrs[1].address == "user2@example.com"

    def test_parse_address_list_with_display_names(self):
        """Test parsing addresses with display names."""
        addr_list_str = "John <john@example.com>, Jane <jane@example.com>"
        addrs = HeaderParser.parse_address_list(addr_list_str)

        assert len(addrs) == 2
        assert addrs[0].display_name == "John"
        assert addrs[1].display_name == "Jane"

    def test_parse_rfc2822_date(self):
        """Test parsing RFC 2822 date format."""
        date_str = "Wed, 3 Nov 2021 12:34:56 +0000"
        dt = HeaderParser.parse_date(date_str)

        assert dt is not None
        assert dt.year == 2021
        assert dt.month == 11
        assert dt.day == 3

    def test_parse_date_without_weekday(self):
        """Test parsing date without weekday."""
        date_str = "3 Nov 2021 12:34:56 +0000"
        dt = HeaderParser.parse_date(date_str)

        assert dt is not None
        assert dt.year == 2021

    def test_parse_invalid_date_returns_none(self):
        """Test invalid date returns None."""
        date_str = "not a date"
        dt = HeaderParser.parse_date(date_str)

        assert dt is None

    def test_parse_empty_date_returns_none(self):
        """Test empty date returns None."""
        dt = HeaderParser.parse_date("")
        assert dt is None

    def test_parse_message_id(self):
        """Test parsing Message-ID."""
        msg_id_str = "<12345.67890@example.com>"
        msg_id = HeaderParser.parse_message_id(msg_id_str)

        assert msg_id == "12345.67890@example.com"

    def test_parse_message_id_without_brackets(self):
        """Test parsing Message-ID without brackets."""
        msg_id_str = "12345.67890@example.com"
        msg_id = HeaderParser.parse_message_id(msg_id_str)

        assert msg_id == "12345.67890@example.com"

    def test_parse_invalid_message_id_returns_none(self):
        """Test invalid Message-ID returns None."""
        msg_id = HeaderParser.parse_message_id("invalid")
        assert msg_id is None

    def test_parse_received_header(self):
        """Test parsing Received header."""
        received = "from mail.example.com by mail.dest.com with SMTP id 12345"
        result = HeaderParser.parse_received_header(received)

        assert result["from"] == "mail.example.com"
        assert result["by"] == "mail.dest.com"
        assert result["with"] == "SMTP"


class TestHeaderBuilder:
    """Test header construction."""

    def test_set_from(self):
        """Test setting From header."""
        builder = HeaderBuilder()
        addr = EmailAddress("sender@example.com", "Sender Name")
        builder.set_from(addr)

        headers = builder.build()
        assert "From" in headers
        assert "Sender Name" in headers["From"]

    def test_set_to(self):
        """Test setting To header."""
        builder = HeaderBuilder()
        addrs = [
            EmailAddress("user1@example.com"),
            EmailAddress("user2@example.com"),
        ]
        builder.set_to(addrs)

        headers = builder.build()
        assert "To" in headers
        assert "user1@example.com" in headers["To"]
        assert "user2@example.com" in headers["To"]

    def test_set_cc(self):
        """Test setting CC header."""
        builder = HeaderBuilder()
        addrs = [EmailAddress("cc@example.com")]
        builder.set_cc(addrs)

        headers = builder.build()
        assert "Cc" in headers

    def test_set_subject(self):
        """Test setting Subject header."""
        builder = HeaderBuilder()
        builder.set_subject("Test Subject")

        headers = builder.build()
        assert headers["Subject"] == "Test Subject"

    def test_set_date(self):
        """Test setting Date header."""
        builder = HeaderBuilder()
        dt = datetime(2021, 11, 3, 12, 30, 0, tzinfo=timezone.utc)
        builder.set_date(dt)

        headers = builder.build()
        assert "Date" in headers

    def test_set_date_default(self):
        """Test setting Date header with default (current time)."""
        builder = HeaderBuilder()
        builder.set_date()

        headers = builder.build()
        assert "Date" in headers

    def test_set_message_id(self):
        """Test setting Message-ID header."""
        builder = HeaderBuilder()
        builder.set_message_id("example.com")

        headers = builder.build()
        assert "Message-ID" in headers
        assert headers["Message-ID"].startswith("<")
        assert headers["Message-ID"].endswith(">")
        assert "example.com" in headers["Message-ID"]

    def test_set_in_reply_to(self):
        """Test setting In-Reply-To header."""
        builder = HeaderBuilder()
        builder.set_in_reply_to("<parent@example.com>")

        headers = builder.build()
        assert headers["In-Reply-To"] == "<parent@example.com>"

    def test_set_references(self):
        """Test setting References header."""
        builder = HeaderBuilder()
        refs = ["<msg1@example.com>", "<msg2@example.com>"]
        builder.set_references(refs)

        headers = builder.build()
        assert "References" in headers
        assert "<msg1@example.com>" in headers["References"]
        assert "<msg2@example.com>" in headers["References"]

    def test_set_reply_to(self):
        """Test setting Reply-To header."""
        builder = HeaderBuilder()
        addrs = [EmailAddress("reply@example.com")]
        builder.set_reply_to(addrs)

        headers = builder.build()
        assert "Reply-To" in headers

    def test_set_custom_header(self):
        """Test setting custom header."""
        builder = HeaderBuilder()
        builder.set_header("X-Custom", "value")

        headers = builder.build()
        assert headers["X-Custom"] == "value"

    def test_build_string(self):
        """Test building headers as string."""
        builder = HeaderBuilder()
        builder.set_subject("Test")
        builder.set_header("From", "user@example.com")

        headers_str = builder.build_string()
        assert "Subject: Test" in headers_str
        assert "From: user@example.com" in headers_str

    def test_multiple_headers_no_overwrite(self):
        """Test building multiple headers without overwriting."""
        builder = HeaderBuilder()
        builder.set_subject("Subject 1")
        builder.set_subject("Subject 2")

        headers = builder.build()
        assert headers["Subject"] == "Subject 2"


class TestSubjectNormalization:
    """Test subject line normalization."""

    def test_normalize_re_prefix(self):
        """Test normalizing Re: prefix."""
        subject = "Re: Test Subject"
        normalized = normalize_subject(subject)

        assert normalized == "Test Subject"

    def test_normalize_fwd_prefix(self):
        """Test normalizing Fwd: prefix."""
        subject = "Fwd: Original Subject"
        normalized = normalize_subject(subject)

        assert normalized == "Original Subject"

    def test_normalize_multiple_prefixes(self):
        """Test normalizing multiple prefixes."""
        subject = "Re: Fwd: Original"
        normalized = normalize_subject(subject)

        assert normalized == "Original"

    def test_normalize_case_insensitive(self):
        """Test prefix normalization is case insensitive."""
        subject = "RE: Test"
        normalized = normalize_subject(subject)

        assert normalized == "Test"

    def test_normalize_plain_subject(self):
        """Test normalizing plain subject."""
        subject = "Original Subject"
        normalized = normalize_subject(subject)

        assert normalized == "Original Subject"


class TestMessageIDGeneration:
    """Test Message-ID generation."""

    def test_generate_message_id(self):
        """Test generating unique Message-ID."""
        msg_id = generate_message_id("example.com")

        assert msg_id.startswith("<")
        assert msg_id.endswith(">")
        assert "example.com" in msg_id
        assert "@" in msg_id

    def test_generate_unique_message_ids(self):
        """Test generating unique IDs."""
        msg_id1 = generate_message_id("example.com")
        msg_id2 = generate_message_id("example.com")

        assert msg_id1 != msg_id2


class TestEmailAddress:
    """Test EmailAddress type."""

    def test_create_address_without_display_name(self):
        """Test creating address without display name."""
        addr = EmailAddress("user@example.com")

        assert addr.address == "user@example.com"
        assert addr.display_name is None

    def test_create_address_with_display_name(self):
        """Test creating address with display name."""
        addr = EmailAddress("user@example.com", "User Name")

        assert addr.address == "user@example.com"
        assert addr.display_name == "User Name"

    def test_address_str_without_display_name(self):
        """Test string representation without display name."""
        addr = EmailAddress("user@example.com")
        assert str(addr) == "user@example.com"

    def test_address_str_with_display_name(self):
        """Test string representation with display name."""
        addr = EmailAddress("user@example.com", "User Name")
        assert '"User Name" <user@example.com>' in str(addr)

    def test_invalid_address_raises_error(self):
        """Test invalid address raises ValueError."""
        with pytest.raises(ValueError):
            EmailAddress("invalid_email")
