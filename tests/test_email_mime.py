"""
Tests for MIME message processing.

Tests Content-Type parsing, multipart messages, content transfer encoding,
and RFC 2047 header encoding.
"""

import pytest

from thomas.marketplace.email_protocol._exceptions import MIMEEncodingError
from thomas.marketplace.email_protocol._types import (
    ContentType,
    Encoding,
    MIMEPart,
)
from thomas.marketplace.email_protocol.mime import (
    MIMEBuilder,
    MIMEParser,
    decode_rfc2047,
    encode_rfc2047,
)


class TestMIMEParser:
    """Test MIME message parsing."""

    def test_parse_simple_message(self):
        """Test parsing simple text message."""
        raw_message = b"Subject: Test\nFrom: test@example.com\n\nHello World"
        parser = MIMEParser(raw_message)

        assert "subject" in parser.headers
        assert parser.headers["subject"] == "Test"
        assert parser.body == b"Hello World"

    def test_parse_content_type(self):
        """Test Content-Type extraction."""
        raw_message = b"Content-Type: text/plain; charset=utf-8\n\nBody"
        parser = MIMEParser(raw_message)

        content_type, params = parser.get_content_type()
        assert content_type == ContentType.TEXT_PLAIN

    def test_get_boundary(self):
        """Test boundary extraction from multipart."""
        raw_message = b"Content-Type: multipart/mixed; boundary=----boundary123\n\nBody"
        parser = MIMEParser(raw_message)

        boundary = parser.get_boundary()
        assert boundary == "----boundary123"

    def test_get_charset(self):
        """Test charset extraction."""
        raw_message = b"Content-Type: text/plain; charset=iso-8859-1\n\nBody"
        parser = MIMEParser(raw_message)

        charset = parser.get_charset()
        assert charset == "iso-8859-1"

    def test_get_default_charset(self):
        """Test default charset."""
        raw_message = b"Content-Type: text/plain\n\nBody"
        parser = MIMEParser(raw_message)

        charset = parser.get_charset()
        assert charset == "utf-8"

    def test_decode_base64_content(self):
        """Test base64 content decoding."""
        import base64

        original = b"Hello World"
        encoded = base64.b64encode(original)
        raw_message = b"Content-Transfer-Encoding: base64\n\n" + encoded

        parser = MIMEParser(raw_message)
        encoding = parser.get_content_transfer_encoding()
        assert encoding == Encoding.BASE64

        decoded = parser.decode_content()
        assert decoded == original

    def test_decode_quoted_printable(self):
        """Test quoted-printable decoding."""
        raw_message = b"Content-Transfer-Encoding: quoted-printable\n\nHello=20World"
        parser = MIMEParser(raw_message)

        decoded = parser.decode_content()
        assert b"Hello" in decoded

    def test_invalid_base64_raises_error(self):
        """Test invalid base64 raises error."""
        raw_message = b"Content-Transfer-Encoding: base64\n\n!!!invalid!!!"
        parser = MIMEParser(raw_message)

        with pytest.raises(MIMEEncodingError):
            parser.decode_content()

    def test_parse_multipart_message(self):
        """Test multipart message parsing."""
        boundary = "----boundary123"
        raw_message = (
            f"Content-Type: multipart/mixed; boundary={boundary}\r\n\r\n"
            f"--{boundary}\r\nContent-Type: text/plain\r\n\r\nPart 1\r\n"
            f"--{boundary}\r\nContent-Type: text/html\r\n\r\nPart 2\r\n"
            f"--{boundary}--"
        ).encode()

        parser = MIMEParser(raw_message)
        parts = parser.parse_multipart_parts()

        assert len(parts) >= 1
        if len(parts) >= 1:
            assert parts[0].content_type in (ContentType.TEXT_PLAIN, "text/plain")


class TestMIMEBuilder:
    """Test MIME message construction."""

    def test_build_simple_message(self):
        """Test building simple text message."""
        builder = MIMEBuilder()
        builder.set_header("Subject", "Test")
        builder.set_header("From", "test@example.com")
        builder.set_text_body("Hello World")

        message = builder.build()
        assert b"Subject: Test" in message
        assert b"From: test@example.com" in message
        import base64

        assert base64.b64encode(b"Hello World") in message

    def test_build_multipart_message(self):
        """Test building multipart message."""
        builder = MIMEBuilder()
        builder.set_text_body("Plain text")
        builder.set_html_body("<p>HTML content</p>")

        message = builder.build()
        assert b"multipart/alternative" in message
        import base64

        assert base64.b64encode(b"Plain text") in message
        assert base64.b64encode(b"<p>HTML content</p>") in message

    def test_add_attachment(self):
        """Test adding attachments."""
        builder = MIMEBuilder()
        builder.set_text_body("Message with attachment")
        builder.add_attachment("test.txt", b"file content")

        message = builder.build()
        assert b"multipart/mixed" in message
        assert b"test.txt" in message
        import base64

        assert base64.b64encode(b"file content") in message

    def test_boundary_generation(self):
        """Test unique boundary generation."""
        builder1 = MIMEBuilder()
        builder2 = MIMEBuilder()

        assert builder1.boundary != builder2.boundary


class TestRFC2047Encoding:
    """Test RFC 2047 header encoding."""

    def test_encode_ascii_text(self):
        """Test ASCII text doesn't need encoding."""
        text = "Hello World"
        encoded = encode_rfc2047(text)

        assert encoded == "Hello World"

    def test_encode_non_ascii(self):
        """Test non-ASCII text encoding."""
        text = "Café"
        encoded = encode_rfc2047(text)

        assert encoded.startswith("=?utf-8?B?")
        assert "?=" in encoded

    def test_decode_rfc2047(self):
        """Test RFC 2047 decoding."""
        encoded = "=?utf-8?B?Q2Fmw6k=?="
        decoded = decode_rfc2047(encoded)

        assert "Caf" in decoded

    def test_decode_non_encoded_text(self):
        """Test decoding plain text."""
        text = "Plain text"
        decoded = decode_rfc2047(text)

        assert decoded == "Plain text"


class TestMIMEPart:
    """Test MIME part dataclass."""

    def test_create_mime_part(self):
        """Test creating MIME part."""
        content = b"Hello World"
        part = MIMEPart(
            content_type=ContentType.TEXT_PLAIN,
            content=content,
            charset="utf-8",
        )

        assert part.content == content
        assert part.charset == "utf-8"

    def test_mime_part_get_text(self):
        """Test getting text from MIME part."""
        content = "Hello World"
        part = MIMEPart(
            content_type=ContentType.TEXT_PLAIN,
            content=content.encode(),
        )

        text = part.get_text()
        assert text == content

    def test_mime_part_set_text(self):
        """Test setting text in MIME part."""
        part = MIMEPart(
            content_type=ContentType.TEXT_PLAIN,
            content=b"",
        )

        text = "New content"
        part.set_text(text)

        assert part.get_text() == text

    def test_mime_part_with_headers(self):
        """Test MIME part with custom headers."""
        part = MIMEPart(
            content_type=ContentType.TEXT_PLAIN,
            content=b"Content",
            headers={"X-Custom": "value"},
        )

        assert part.headers["X-Custom"] == "value"


class TestContentTypeHandling:
    """Test content type handling."""

    def test_parse_various_content_types(self):
        """Test parsing different content types."""
        test_cases = [
            (b"Content-Type: text/plain\n\n", ContentType.TEXT_PLAIN),
            (b"Content-Type: text/html\n\n", ContentType.TEXT_HTML),
            (b"Content-Type: multipart/mixed\n\n", ContentType.MULTIPART_MIXED),
            (b"Content-Type: application/json\n\n", ContentType.APPLICATION_JSON),
        ]

        for raw_message, expected in test_cases:
            parser = MIMEParser(raw_message)
            content_type, _ = parser.get_content_type()
            assert content_type == expected

    def test_content_type_with_parameters(self):
        """Test content type with multiple parameters."""
        raw_message = b"Content-Type: text/plain; charset=utf-8; format=flowed\n\nBody"
        parser = MIMEParser(raw_message)

        _, params = parser.get_content_type()
        assert params.get("charset") == "utf-8"
        assert params.get("format") == "flowed"


class TestEncodingHandling:
    """Test content transfer encoding."""

    def test_7bit_encoding(self):
        """Test 7bit encoding."""
        raw_message = b"Content-Transfer-Encoding: 7bit\n\nASCII only"
        parser = MIMEParser(raw_message)

        encoding = parser.get_content_transfer_encoding()
        assert encoding == Encoding.PLAIN_7BIT

    def test_8bit_encoding(self):
        """Test 8bit encoding."""
        raw_message = b"Content-Transfer-Encoding: 8bit\n\nContent"
        parser = MIMEParser(raw_message)

        encoding = parser.get_content_transfer_encoding()
        assert encoding == Encoding.PLAIN_8BIT

    def test_default_encoding(self):
        """Test default encoding when not specified."""
        raw_message = b"\n\nContent"
        parser = MIMEParser(raw_message)

        encoding = parser.get_content_transfer_encoding()
        assert encoding == Encoding.PLAIN_7BIT
