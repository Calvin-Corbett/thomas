"""
Wire format wrapper for serialized messages.

Provides header format (magic bytes, version, format, flags) with payload,
CRC32 integrity checking, and framing for streaming protocols.
"""

import struct
import zlib
from collections.abc import Iterator
from io import BytesIO

from .exceptions import DeserializationError
from .types import CompressionType, SerializationFormat, WireMessage


class WireFormatter:
    """Formats and parses wire protocol messages."""

    # Magic bytes identifying Thomas serialization
    MAGIC_BYTES = b"THOM"
    VERSION = 1

    # Flag bits
    FLAG_COMPRESSED = 0x01
    FLAG_CHECKSUM = 0x02
    FLAG_STREAMING = 0x04

    def __init__(self) -> None:
        self.stream = BytesIO()

    def pack(
        self,
        payload: bytes,
        format: SerializationFormat,
        version: int = 1,
        compressed: CompressionType = CompressionType.NONE,
        checksum: bool = True,
    ) -> bytes:
        """Pack payload into wire format.

        Format:
        - Magic bytes (4): "THOM"
        - Version (1): Protocol version
        - Format (1): Serialization format enum value
        - Flags (1): Compression, checksum, streaming flags
        - Compressed type (1): Compression algorithm enum value
        - Schema version (2): Schema version number
        - Payload length (4): Length of payload
        - Payload (n): Serialized data
        - Checksum (4, optional): CRC32 of header + payload

        Args:
            payload: Serialized payload bytes.
            format: Serialization format used.
            version: Schema version.
            compressed: Compression type applied.
            checksum: Include CRC32 checksum.

        Returns:
            Wire format bytes.
        """
        stream = BytesIO()

        # Header
        stream.write(self.MAGIC_BYTES)
        stream.write(struct.pack("B", self.VERSION))
        # Encode format as index in enum
        format_index = list(SerializationFormat).index(format)
        stream.write(struct.pack("B", format_index))

        flags = 0
        if compressed != CompressionType.NONE:
            flags |= self.FLAG_COMPRESSED
        if checksum:
            flags |= self.FLAG_CHECKSUM

        stream.write(struct.pack("B", flags))
        # Encode compression type as index
        compression_index = list(CompressionType).index(compressed)
        stream.write(struct.pack("B", compression_index))
        stream.write(struct.pack(">H", version))
        stream.write(struct.pack(">I", len(payload)))

        # Payload
        stream.write(payload)

        data = stream.getvalue()

        # Checksum
        if checksum:
            crc = zlib.crc32(data) & 0xFFFFFFFF
            data += struct.pack(">I", crc)

        return data

    def unpack(self, data: bytes) -> WireMessage:
        """Unpack wire format message.

        Args:
            data: Wire format bytes.

        Returns:
            WireMessage with parsed components.

        Raises:
            DeserializationError: If format is invalid.
        """
        stream = BytesIO(data)

        # Read and validate magic bytes
        magic = stream.read(4)
        if magic != self.MAGIC_BYTES:
            raise DeserializationError(f"Invalid magic bytes: {magic!r}", data=data)

        # Read version
        version_byte = stream.read(1)
        if not version_byte:
            raise DeserializationError("Truncated wire format", data=data)
        proto_version = version_byte[0]

        if proto_version != self.VERSION:
            raise DeserializationError(
                f"Unsupported protocol version: {proto_version}",
                data=data,
            )

        # Read format
        format_byte = stream.read(1)
        if not format_byte:
            raise DeserializationError("Truncated wire format", data=data)

        try:
            format_index = format_byte[0]
            format_enum = list(SerializationFormat)[format_index]
        except (ValueError, IndexError):
            raise DeserializationError(
                f"Unknown serialization format: {format_byte[0]}",
                data=data,
            )

        # Read flags
        flags_byte = stream.read(1)
        if not flags_byte:
            raise DeserializationError("Truncated wire format", data=data)
        flags = flags_byte[0]

        has_checksum = bool(flags & self.FLAG_CHECKSUM)
        is_compressed = bool(flags & self.FLAG_COMPRESSED)

        # Read compression type
        compressed_byte = stream.read(1)
        if not compressed_byte:
            raise DeserializationError("Truncated wire format", data=data)

        try:
            compression_index = compressed_byte[0]
            compressed_type = list(CompressionType)[compression_index]
        except (ValueError, IndexError):
            raise DeserializationError(
                f"Unknown compression type: {compressed_byte[0]}",
                data=data,
            )

        # Read schema version
        version_bytes = stream.read(2)
        if len(version_bytes) < 2:
            raise DeserializationError("Truncated wire format", data=data)
        schema_version = struct.unpack(">H", version_bytes)[0]

        # Read payload length
        length_bytes = stream.read(4)
        if len(length_bytes) < 4:
            raise DeserializationError("Truncated wire format", data=data)
        payload_length = struct.unpack(">I", length_bytes)[0]

        # Read payload
        payload = stream.read(payload_length)
        if len(payload) < payload_length:
            raise DeserializationError("Truncated payload", data=data)

        # Verify checksum if present
        if has_checksum:
            checksum_bytes = stream.read(4)
            if len(checksum_bytes) < 4:
                raise DeserializationError("Missing checksum", data=data)

            expected_checksum = struct.unpack(">I", checksum_bytes)[0]
            header_and_payload = data[:-4]
            actual_checksum = zlib.crc32(header_and_payload) & 0xFFFFFFFF

            if expected_checksum != actual_checksum:
                raise DeserializationError(
                    "Checksum mismatch - data corruption detected",
                    data=data,
                )

        return WireMessage(
            format=format_enum,
            version=schema_version,
            compressed=compressed_type,
            payload=payload,
            metadata={"checksum_verified": has_checksum},
        )


class FramedStreamWriter:
    """Writes framed messages to a stream."""

    def __init__(self, stream: BytesIO) -> None:
        """Initialize writer.

        Args:
            stream: BytesIO stream to write to.
        """
        self.stream = stream
        self.formatter = WireFormatter()

    def write_message(
        self,
        payload: bytes,
        format: SerializationFormat,
        version: int = 1,
        compressed: CompressionType = CompressionType.NONE,
    ) -> None:
        """Write a single framed message.

        Args:
            payload: Message payload.
            format: Serialization format.
            version: Schema version.
            compressed: Compression type.
        """
        packed = self.formatter.pack(
            payload,
            format,
            version,
            compressed,
            checksum=True,
        )
        self.stream.write(packed)

    def write_messages(
        self,
        payloads: Iterator[bytes],
        format: SerializationFormat,
        version: int = 1,
        compressed: CompressionType = CompressionType.NONE,
    ) -> None:
        """Write multiple framed messages.

        Args:
            payloads: Iterator of message payloads.
            format: Serialization format.
            version: Schema version.
            compressed: Compression type.
        """
        for payload in payloads:
            self.write_message(payload, format, version, compressed)


class FramedStreamReader:
    """Reads framed messages from a stream."""

    def __init__(self, stream: BytesIO) -> None:
        """Initialize reader.

        Args:
            stream: BytesIO stream to read from.
        """
        self.stream = stream
        self.formatter = WireFormatter()

    def read_message(self) -> WireMessage | None:
        """Read next framed message.

        Returns:
            WireMessage or None if stream is exhausted.

        Raises:
            DeserializationError: If message is invalid.
        """
        # Try to read magic bytes
        magic = self.stream.read(4)
        if not magic:
            return None

        if magic != WireFormatter.MAGIC_BYTES:
            raise DeserializationError(
                f"Invalid magic bytes at stream position {self.stream.tell()}",
                data=magic,
            )

        # Read rest of header (version + format + flags + compressed + version + length = 8 bytes)
        header = self.stream.read(8)
        if len(header) < 8:
            raise DeserializationError("Truncated message header")

        # Extract payload length
        payload_length = struct.unpack(">I", header[4:8])[0]

        # Read payload
        payload = self.stream.read(payload_length)
        if len(payload) < payload_length:
            raise DeserializationError("Truncated message payload")

        # Read checksum (4 bytes)
        checksum = self.stream.read(4)
        if len(checksum) < 4:
            raise DeserializationError("Missing message checksum")

        # Reconstruct full message for unpacking
        full_data = magic + header + payload + checksum

        return self.formatter.unpack(full_data)

    def read_messages(self) -> Iterator[WireMessage]:
        """Read all framed messages from stream.

        Yields:
            WireMessage for each message in stream.

        Raises:
            DeserializationError: If any message is invalid.
        """
        while True:
            message = self.read_message()
            if message is None:
                break
            yield message


def pack_message(
    payload: bytes,
    format: SerializationFormat,
    version: int = 1,
    compressed: CompressionType = CompressionType.NONE,
) -> bytes:
    """Pack a message into wire format.

    Args:
        payload: Serialized payload.
        format: Serialization format.
        version: Schema version.
        compressed: Compression type.

    Returns:
        Wire format bytes.
    """
    formatter = WireFormatter()
    return formatter.pack(payload, format, version, compressed)


def unpack_message(data: bytes) -> WireMessage:
    """Unpack a message from wire format.

    Args:
        data: Wire format bytes.

    Returns:
        WireMessage with parsed components.

    Raises:
        DeserializationError: If format is invalid.
    """
    formatter = WireFormatter()
    return formatter.unpack(data)
