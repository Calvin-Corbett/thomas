"""
MIME message processing and parsing.

Implements RFC 2045-2049 MIME standards for multipart messages,
content-type handling, content-transfer-encoding, header decoding.
"""

import base64
import quopri
import re
from dataclasses import dataclass

from thomas.email_protocol._exceptions import MIMEEncodingError, MIMEParseError
from thomas.email_protocol._types import (
    ContentType,
    Encoding,
    MIMEPart,
)


@dataclass
class MIMEBoundary:
    """Represents a MIME boundary delimiter.

    Attributes:
        boundary: The boundary string
        is_closing: Whether this is a closing boundary
        epilogue: Text after final boundary
    """

    boundary: str
    is_closing: bool = False
    epilogue: str | None = None


class MIMEParser:
    """Parser for MIME messages with multipart support.

    Handles Content-Type detection, boundary parsing, recursive multipart
    parsing, content transfer decoding, and RFC 2047 header decoding.
    """

    def __init__(self, raw_message: bytes) -> None:
        """Initialize parser with raw message bytes.

        Args:
            raw_message: Raw message bytes including headers and body
        """
        self.raw_message = raw_message
        self.headers: dict[str, str] = {}
        self.body: bytes = b""
        self._parse_headers_and_body()

    def _parse_headers_and_body(self) -> None:
        """Split message into headers and body sections."""
        separator = b"\r\n\r\n"
        if separator not in self.raw_message:
            separator = b"\n\n"
            if separator not in self.raw_message:
                self.body = self.raw_message
                return

        header_section, body = self.raw_message.split(separator, 1)
        self.body = body
        self._parse_headers(header_section.decode("utf-8", errors="replace"))

    def _parse_headers(self, header_text: str) -> None:
        """Parse email headers, handling line continuation.

        Args:
            header_text: Raw header text with potential line continuations
        """
        lines = header_text.split("\n")
        current_header = ""
        current_value = ""

        for line in lines:
            if line and line[0] in (" ", "\t"):
                current_value += line
            else:
                if current_header:
                    self.headers[current_header.lower()] = current_value.strip()
                if ":" in line:
                    current_header, current_value = line.split(":", 1)
                    current_header = current_header.strip()
                    current_value = current_value.strip()

        if current_header:
            self.headers[current_header.lower()] = current_value.strip()

    def get_content_type(self) -> tuple[str, dict[str, str]]:
        """Extract Content-Type header and parameters.

        Returns:
            Tuple of (content_type, parameters_dict)

        Raises:
            MIMEParseError: If Content-Type is malformed
        """
        content_type_header = self.headers.get("content-type", "text/plain")
        parts = content_type_header.split(";")
        media_type = parts[0].strip().lower()

        params = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                key = key.strip().lower()
                value = value.strip().strip('"')
                params[key] = value

        try:
            return ContentType(media_type), params
        except ValueError:
            return media_type, params

    def get_boundary(self) -> str | None:
        """Extract boundary from Content-Type if multipart.

        Returns:
            Boundary string or None if not multipart
        """
        _, params = self.get_content_type()
        return params.get("boundary")

    def get_charset(self) -> str:
        """Extract charset parameter from Content-Type.

        Returns:
            Character set name (default: utf-8)
        """
        _, params = self.get_content_type()
        return params.get("charset", "utf-8")

    def get_content_transfer_encoding(self) -> Encoding:
        """Extract Content-Transfer-Encoding header.

        Returns:
            Encoding type (default: 7bit)
        """
        encoding = self.headers.get("content-transfer-encoding", "7bit").lower()
        try:
            return Encoding(encoding)
        except ValueError:
            return Encoding.PLAIN_7BIT

    def decode_content(self) -> bytes:
        """Decode body based on Content-Transfer-Encoding.

        Returns:
            Decoded body content

        Raises:
            MIMEEncodingError: If decoding fails
        """
        encoding = self.get_content_transfer_encoding()

        if encoding == Encoding.BASE64:
            return self._decode_base64(self.body)
        elif encoding == Encoding.QUOTED_PRINTABLE:
            return self._decode_quoted_printable(self.body)
        elif encoding in (Encoding.PLAIN_7BIT, Encoding.PLAIN_8BIT):
            return self.body
        else:
            return self.body

    @staticmethod
    def _decode_base64(data: bytes) -> bytes:
        """Decode base64 encoded data.

        Args:
            data: Base64 encoded bytes

        Returns:
            Decoded bytes

        Raises:
            MIMEEncodingError: If decoding fails
        """
        try:
            return base64.b64decode(data)
        except Exception as e:
            raise MIMEEncodingError(f"Base64 decoding failed: {e}")

    @staticmethod
    def _decode_quoted_printable(data: bytes) -> bytes:
        """Decode quoted-printable encoded data.

        Args:
            data: Quoted-printable encoded bytes

        Returns:
            Decoded bytes
        """
        return quopri.decodestring(data)

    def parse_multipart_parts(self) -> list[MIMEPart]:
        """Parse multipart message into component parts.

        Returns:
            List of MIME parts

        Raises:
            MIMEParseError: If parsing fails
        """
        boundary = self.get_boundary()
        if not boundary:
            raise MIMEParseError("Multipart message missing boundary")

        parts = []
        content_type = self.get_content_type()
        is_multipart_alternative = content_type == ContentType.MULTIPART_ALTERNATIVE

        boundary_marker = f"--{boundary}".encode()
        closing_marker = f"--{boundary}--".encode()

        body_lines = self.body.split(b"\r\n")
        current_part_lines = []
        in_part = False

        for line in body_lines:
            if line.startswith(boundary_marker):
                if in_part and current_part_lines:
                    part_data = b"\r\n".join(current_part_lines)
                    parts.append(self._parse_single_part(part_data))
                    current_part_lines = []

                if line == closing_marker:
                    break
                in_part = True
            elif in_part:
                current_part_lines.append(line)

        if in_part and current_part_lines:
            part_data = b"\r\n".join(current_part_lines)
            parts.append(self._parse_single_part(part_data))

        return parts

    def _parse_single_part(self, part_data: bytes) -> MIMEPart:
        """Parse a single MIME part from raw bytes.

        Args:
            part_data: Raw part data including headers

        Returns:
            Parsed MIME part
        """
        parser = MIMEParser(part_data)
        content_type, _ = parser.get_content_type()
        charset = parser.get_charset()
        encoding = parser.get_content_transfer_encoding()

        content = parser.decode_content()

        return MIMEPart(
            content_type=content_type,
            content=content,
            charset=charset,
            content_transfer_encoding=encoding,
            headers=parser.headers,
        )


class MIMEBuilder:
    """Builder for constructing MIME messages.

    Supports creating multipart messages, adding attachments,
    setting headers, and proper encoding.
    """

    def __init__(self) -> None:
        """Initialize MIME message builder."""
        self.headers: dict[str, str] = {}
        self.text_body: str | None = None
        self.html_body: str | None = None
        self.attachments: list[tuple[str, bytes]] = []
        self.boundary = self._generate_boundary()

    def set_header(self, name: str, value: str) -> None:
        """Set an email header.

        Args:
            name: Header name
            value: Header value
        """
        self.headers[name] = value

    def set_text_body(self, text: str) -> None:
        """Set plain text body.

        Args:
            text: Plain text content
        """
        self.text_body = text

    def set_html_body(self, html: str) -> None:
        """Set HTML body.

        Args:
            html: HTML content
        """
        self.html_body = html

    def add_attachment(self, filename: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        """Add file attachment.

        Args:
            filename: Attachment filename
            content: File content bytes
            content_type: MIME content type
        """
        self.attachments.append((filename, content, content_type))

    def build(self) -> bytes:
        """Build complete MIME message.

        Returns:
            Complete message as bytes
        """
        message_parts = []

        for header_name, header_value in self.headers.items():
            message_parts.append(f"{header_name}: {header_value}\r\n")

        if self.text_body or self.html_body or self.attachments:
            if self.attachments:
                content_type = f"multipart/mixed; boundary={self.boundary}"
            else:
                content_type = f"multipart/alternative; boundary={self.boundary}"
            message_parts.append(f"Content-Type: {content_type}\r\n\r\n")

            if self.text_body:
                message_parts.append(f"--{self.boundary}\r\n")
                message_parts.append("Content-Type: text/plain; charset=utf-8\r\n")
                message_parts.append("Content-Transfer-Encoding: base64\r\n\r\n")
                encoded = base64.b64encode(self.text_body.encode()).decode()
                message_parts.append(f"{encoded}\r\n")

            if self.html_body:
                message_parts.append(f"--{self.boundary}\r\n")
                message_parts.append("Content-Type: text/html; charset=utf-8\r\n")
                message_parts.append("Content-Transfer-Encoding: base64\r\n\r\n")
                encoded = base64.b64encode(self.html_body.encode()).decode()
                message_parts.append(f"{encoded}\r\n")

            for filename, content, content_type in self.attachments:
                message_parts.append(f"--{self.boundary}\r\n")
                message_parts.append(f"Content-Type: {content_type}\r\n")
                message_parts.append(f"Content-Disposition: attachment; filename={filename}\r\n")
                message_parts.append("Content-Transfer-Encoding: base64\r\n\r\n")
                encoded = base64.b64encode(content).decode()
                message_parts.append(f"{encoded}\r\n")

            message_parts.append(f"--{self.boundary}--\r\n")
        else:
            message_parts.append("Content-Type: text/plain; charset=utf-8\r\n")
            message_parts.append("Content-Transfer-Encoding: 7bit\r\n\r\n")

        return "".join(message_parts).encode()

    @staticmethod
    def _generate_boundary() -> str:
        """Generate unique MIME boundary string.

        Returns:
            Random boundary string
        """
        import uuid

        return f"boundary_{uuid.uuid4().hex[:16]}"


def encode_rfc2047(text: str, charset: str = "utf-8") -> str:
    """Encode text using RFC 2047 header encoding.

    Args:
        text: Text to encode
        charset: Character encoding to use

    Returns:
        RFC 2047 encoded string
    """
    if all(ord(c) < 128 for c in text):
        return text

    encoded = base64.b64encode(text.encode(charset)).decode()
    return f"=?{charset}?B?{encoded}?="


def decode_rfc2047(encoded_text: str) -> str:
    """Decode RFC 2047 encoded header text.

    Args:
        encoded_text: RFC 2047 encoded string

    Returns:
        Decoded text
    """
    pattern = r"=\?([^?]+)\?([BbQq])\?([^?]+)\?="
    matches = list(re.finditer(pattern, encoded_text))

    result = encoded_text
    for match in matches:
        charset, encoding_type, encoded = match.groups()
        try:
            if encoding_type.upper() == "B":
                decoded = base64.b64decode(encoded).decode(charset)
            else:
                decoded = quopri.decodestring(encoded.encode()).decode(charset)
            result = result.replace(match.group(0), decoded)
        except (ValueError, TypeError):
            pass

    return result
