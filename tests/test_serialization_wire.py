"""
Tests for wire format and message framing.

Tests wire format wrapping, CRC32 integrity checking, message framing,
corruption detection, and streaming.
"""

from io import BytesIO

import pytest

from thomas.serialization import (
    CompressionType,
    DeserializationError,
    SerializationFormat,
)
from thomas.serialization.wire_format import (
    FramedStreamReader,
    FramedStreamWriter,
    WireFormatter,
    pack_message,
    unpack_message,
)


class TestWireFormatter:
    """Tests for wire message formatting."""

    def setup_method(self):
        self.formatter = WireFormatter()

    def test_pack_simple_message(self):
        """Test packing a simple message."""
        payload = b"hello world"
        packed = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            version=1,
            compressed=CompressionType.NONE,
            checksum=True,
        )

        assert isinstance(packed, bytes)
        assert packed.startswith(b"THOM")  # Magic bytes

    def test_unpack_valid_message(self):
        """Test unpacking a valid message."""
        original_payload = b"test data"
        packed = self.formatter.pack(
            original_payload,
            SerializationFormat.JSON,
            version=1,
            compressed=CompressionType.NONE,
            checksum=True,
        )

        unpacked = self.formatter.unpack(packed)

        assert unpacked.payload == original_payload
        assert unpacked.format == SerializationFormat.JSON
        assert unpacked.version == 1
        assert unpacked.compressed == CompressionType.NONE
        assert unpacked.metadata["checksum_verified"] is True

    def test_invalid_magic_bytes(self):
        """Test error on invalid magic bytes."""
        bad_data = b"XXXX" + b"\x00" * 20

        with pytest.raises(DeserializationError) as exc_info:
            self.formatter.unpack(bad_data)

        assert "magic" in str(exc_info.value).lower()

    def test_checksum_verification(self):
        """Test checksum verification."""
        payload = b"important data"
        packed = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            version=1,
            checksum=True,
        )

        # Corrupt the payload
        corrupted = bytearray(packed)
        # Change a byte in the middle of payload
        payload_start = 16
        corrupted[payload_start] ^= 0xFF  # Flip bits

        with pytest.raises(DeserializationError) as exc_info:
            self.formatter.unpack(bytes(corrupted))

        assert "checksum" in str(exc_info.value).lower()

    def test_checksum_optional(self):
        """Test that checksum can be disabled."""
        payload = b"data"
        packed_with_checksum = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            checksum=True,
        )
        packed_without_checksum = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            checksum=False,
        )

        # Without checksum should be smaller
        assert len(packed_without_checksum) < len(packed_with_checksum)

    def test_compression_flag(self):
        """Test compression flag in packed message."""
        payload = b"x" * 1000

        packed = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            compressed=CompressionType.ZLIB,
            checksum=False,
        )

        unpacked = self.formatter.unpack(packed)
        assert unpacked.compressed == CompressionType.ZLIB

    def test_all_formats(self):
        """Test packing/unpacking all supported formats."""
        payload = b"test"

        for format in SerializationFormat:
            packed = self.formatter.pack(
                payload,
                format,
                checksum=True,
            )
            unpacked = self.formatter.unpack(packed)

            assert unpacked.format == format
            assert unpacked.payload == payload

    def test_truncated_header(self):
        """Test error on truncated header."""
        data = b"THOM\x01"  # Magic + version only

        with pytest.raises(DeserializationError):
            self.formatter.unpack(data)

    def test_truncated_payload(self):
        """Test error on truncated payload."""
        payload = b"data" * 100
        packed = self.formatter.pack(
            payload,
            SerializationFormat.JSON,
            checksum=False,
        )

        # Remove part of payload
        truncated = packed[:-50]

        with pytest.raises(DeserializationError):
            self.formatter.unpack(truncated)

    def test_large_payload(self):
        """Test packing large payloads."""
        large_payload = b"x" * 1000000  # 1MB

        packed = self.formatter.pack(
            large_payload,
            SerializationFormat.JSON,
            checksum=True,
        )
        unpacked = self.formatter.unpack(packed)

        assert unpacked.payload == large_payload
        assert len(unpacked.payload) == 1000000

    def test_roundtrip_preserves_metadata(self):
        """Test that roundtrip preserves all metadata."""
        payload = b"metadata test"

        packed = self.formatter.pack(
            payload,
            SerializationFormat.MSGPACK,
            version=3,
            compressed=CompressionType.GZIP,
            checksum=True,
        )

        unpacked = self.formatter.unpack(packed)

        assert unpacked.format == SerializationFormat.MSGPACK
        assert unpacked.version == 3
        assert unpacked.compressed == CompressionType.GZIP
        assert unpacked.payload == payload


class TestFramedStreamIO:
    """Tests for framed message streaming."""

    def test_write_and_read_single_message(self):
        """Test writing and reading a single message."""
        stream = BytesIO()
        writer = FramedStreamWriter(stream)

        payload = b"message data"
        writer.write_message(
            payload,
            SerializationFormat.JSON,
            version=1,
        )

        # Read it back
        stream.seek(0)
        reader = FramedStreamReader(stream)
        message = reader.read_message()

        assert message is not None
        assert message.payload == payload
        assert message.format == SerializationFormat.JSON

    def test_write_and_read_multiple_messages(self):
        """Test writing and reading multiple messages."""
        stream = BytesIO()
        writer = FramedStreamWriter(stream)

        payloads = [b"msg1", b"msg2", b"msg3"]
        for payload in payloads:
            writer.write_message(
                payload,
                SerializationFormat.JSON,
            )

        # Read them back
        stream.seek(0)
        reader = FramedStreamReader(stream)
        messages = list(reader.read_messages())

        assert len(messages) == 3
        for i, message in enumerate(messages):
            assert message.payload == payloads[i]

    def test_read_exhausted_stream(self):
        """Test that read_message returns None for exhausted stream."""
        stream = BytesIO(b"")
        reader = FramedStreamReader(stream)

        message = reader.read_message()
        assert message is None

    def test_corrupted_message_in_stream(self):
        """Test error handling for corrupted message in stream."""
        stream = BytesIO()
        writer = FramedStreamWriter(stream)

        # Write one valid message
        writer.write_message(b"valid", SerializationFormat.JSON)
        writer.write_message(b"more", SerializationFormat.JSON)

        # Corrupt the stream
        data = stream.getvalue()
        corrupted = bytearray(data)
        corrupted[50:60] = b"\xff" * 10

        # Try to read corrupted stream
        stream2 = BytesIO(bytes(corrupted))
        reader = FramedStreamReader(stream2)

        # First message should be fine
        msg1 = reader.read_message()
        assert msg1 is not None

        # Second message should fail
        with pytest.raises(DeserializationError):
            reader.read_message()


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_pack_message_helper(self):
        """Test pack_message helper function."""
        payload = b"test"
        packed = pack_message(
            payload,
            SerializationFormat.JSON,
            version=1,
        )

        assert isinstance(packed, bytes)
        assert packed.startswith(b"THOM")

    def test_unpack_message_helper(self):
        """Test unpack_message helper function."""
        original = b"test data"

        formatter = WireFormatter()
        packed = formatter.pack(
            original,
            SerializationFormat.JSON,
            checksum=True,
        )

        unpacked = unpack_message(packed)

        assert unpacked.payload == original

    def test_roundtrip_with_helpers(self):
        """Test roundtrip using helper functions."""
        payload = b"roundtrip test"

        packed = pack_message(
            payload,
            SerializationFormat.CBOR,
            version=2,
        )

        unpacked = unpack_message(packed)

        assert unpacked.payload == payload
        assert unpacked.format == SerializationFormat.CBOR
        assert unpacked.version == 2


class TestWireFormatRobustness:
    """Tests for wire format robustness."""

    def test_empty_payload(self):
        """Test packing empty payload."""
        formatter = WireFormatter()
        packed = formatter.pack(
            b"",
            SerializationFormat.JSON,
        )

        unpacked = formatter.unpack(packed)
        assert unpacked.payload == b""

    def test_binary_payload(self):
        """Test packing binary payload with all byte values."""
        formatter = WireFormatter()
        binary = bytes(range(256))

        packed = formatter.pack(
            binary,
            SerializationFormat.JSON,
            checksum=True,
        )

        unpacked = formatter.unpack(packed)
        assert unpacked.payload == binary

    def test_format_version_preserved(self):
        """Test that format and version are preserved."""
        formatter = WireFormatter()

        test_cases = [
            (SerializationFormat.JSON, 1),
            (SerializationFormat.MSGPACK, 2),
            (SerializationFormat.PROTOBUF, 3),
            (SerializationFormat.CBOR, 5),
        ]

        for format, version in test_cases:
            packed = formatter.pack(
                b"test",
                format,
                version=version,
            )

            unpacked = formatter.unpack(packed)
            assert unpacked.format == format
            assert unpacked.version == version

    def test_max_payload_size(self):
        """Test handling of large payload sizes."""
        formatter = WireFormatter()

        # Create a 10MB payload
        large_payload = b"x" * (10 * 1024 * 1024)

        packed = formatter.pack(
            large_payload,
            SerializationFormat.JSON,
            checksum=False,  # Skip checksum for speed
        )

        unpacked = formatter.unpack(packed)
        assert len(unpacked.payload) == len(large_payload)
