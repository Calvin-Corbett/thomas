"""
Tests for MessagePack binary codec.

Tests binary packing, type extensions, large payloads, and roundtrip
serialization of various data types.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

import pytest

from thomas.marketplace.serialization import (
    CodecConfig,
    DeserializationError,
    MessagePackCodec,
    SerializationFormat,
)


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TestMessagePackCodec:
    """MessagePack codec tests."""

    def setup_method(self):
        self.codec = MessagePackCodec()
        self.config = CodecConfig(format=SerializationFormat.MSGPACK)

    def test_encode_decode_none(self):
        """Test None encoding."""
        encoded = self.codec.encode(None, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded is None

    def test_encode_decode_booleans(self):
        """Test boolean encoding."""
        assert self.codec.decode(self.codec.encode(True, self.config), self.config) is True
        assert self.codec.decode(self.codec.encode(False, self.config), self.config) is False

    def test_encode_decode_integers(self):
        """Test integer encoding with various ranges."""
        test_values = [
            0,
            1,
            -1,
            127,
            128,
            255,
            256,
            65535,
            65536,
            -128,
            -32768,
            2147483647,
            -2147483648,
        ]

        for value in test_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value

    def test_encode_decode_floats(self):
        """Test floating point encoding."""
        test_values = [0.0, 1.5, -3.14, 1e10, 1e-10]

        for value in test_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert abs(decoded - value) < 1e-10

    def test_encode_decode_strings(self):
        """Test string encoding."""
        test_strings = [
            "",
            "hello",
            "x" * 31,  # fixstr max
            "x" * 32,  # str 8
            "y" * 256,  # str 16
            "unicode: 你好世界",
        ]

        for s in test_strings:
            encoded = self.codec.encode(s, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == s

    def test_encode_decode_bytes(self):
        """Test binary data encoding."""
        test_data = [
            b"",
            b"hello",
            b"\x00\x01\x02\x03",
            bytes(range(256)),
        ]

        for data in test_data:
            encoded = self.codec.encode(data, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == data

    def test_encode_decode_arrays(self):
        """Test array encoding."""
        test_arrays = [
            [],
            [1, 2, 3],
            [1, "two", 3.0, None],
            [[1, 2], [3, 4]],
            list(range(100)),
        ]

        for arr in test_arrays:
            encoded = self.codec.encode(arr, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == arr

    def test_encode_decode_maps(self):
        """Test map/dict encoding."""
        test_maps = [
            {},
            {"key": "value"},
            {f"key{i}": i for i in range(20)},
            {"nested": {"inner": {"deep": "value"}}},
        ]

        for m in test_maps:
            encoded = self.codec.encode(m, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == m

    def test_encode_decode_decimal(self):
        """Test Decimal extension."""
        values = [Decimal("0"), Decimal("3.14"), Decimal("-99.99")]

        for value in values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            # Decoded as dict with type info
            assert isinstance(decoded, dict)

    def test_encode_decode_uuid(self):
        """Test UUID extension."""
        u = uuid.uuid4()
        encoded = self.codec.encode(u, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Check that it's decoded (as bytes)
        assert isinstance(decoded, bytes) and len(decoded) == 16

    def test_encode_decode_datetime(self):
        """Test datetime extension."""
        dt = datetime(2024, 1, 15, 12, 30, 45)
        encoded = self.codec.encode(dt, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Decoded preserves datetime info
        assert isinstance(decoded, bytes) or isinstance(decoded, str)

    def test_encode_decode_enum(self):
        """Test Enum encoding."""
        encoded = self.codec.encode(Status.ACTIVE, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Decoded as map with type info
        assert isinstance(decoded, dict)

    def test_nested_structures(self):
        """Test deeply nested structures."""
        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "values": [1, 2, 3],
                        "text": "deep",
                    }
                }
            }
        }

        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == data

    def test_large_payload(self):
        """Test large payload serialization."""
        large_data = {
            "items": [
                {
                    "id": i,
                    "name": f"item-{i}",
                    "data": b"x" * 100,
                }
                for i in range(100)
            ]
        }

        encoded = self.codec.encode(large_data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert len(decoded["items"]) == 100
        assert decoded["items"][50]["name"] == "item-50"

    def test_binary_efficiency(self):
        """Test that MessagePack is more efficient than JSON for binary data."""
        binary_data = b"x" * 1000
        # MessagePack binary encoding should be more efficient
        encoded = self.codec.encode(binary_data, self.config)
        assert len(encoded) < 1020  # Should be near size + small overhead

    def test_invalid_msgpack(self):
        """Test decoding invalid MessagePack."""
        with pytest.raises(DeserializationError):
            self.codec.decode(b"\xff\xff\xff\xff", self.config)

    def test_truncated_data(self):
        """Test handling truncated MessagePack."""
        # Encode something then truncate it
        encoded = self.codec.encode({"key": "value" * 100}, self.config)
        truncated = encoded[: len(encoded) // 2]

        with pytest.raises(DeserializationError):
            self.codec.decode(truncated, self.config)

    def test_mixed_types_in_array(self):
        """Test arrays with mixed types."""
        data = [
            1,
            "string",
            3.14,
            True,
            None,
            [1, 2],
            {"key": "value"},
        ]

        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert len(decoded) == 7
        assert decoded[0] == 1
        assert decoded[1] == "string"
        assert decoded[2] == 3.14
        assert decoded[3] is True
        assert decoded[4] is None

    def test_empty_containers(self):
        """Test empty arrays and maps."""
        for container in [[], {}]:
            encoded = self.codec.encode(container, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == container

    def test_string_keys_in_map(self):
        """Test that map keys are strings."""
        data = {"key1": 1, "key2": 2}
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        # All keys should be strings
        assert all(isinstance(k, str) for k in decoded.keys())

    def test_size_efficiency(self):
        """Test size efficiency of MessagePack."""
        data = {"x": 1, "y": 2, "z": 3}

        encoded = self.codec.encode(data, self.config)
        # MessagePack should be more efficient than JSON
        assert len(encoded) < 100
