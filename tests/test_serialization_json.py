"""
Tests for JSON codec with custom type support.

Tests roundtrip serialization, custom types (datetime, UUID, Decimal, bytes,
Enum, dataclass, NamedTuple), streaming, and edge cases.
"""

import dataclasses
import json
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import NamedTuple

import pytest

from thomas.serialization import (
    CodecConfig,
    DeserializationError,
    JSONCodec,
    SerializationError,
    SerializationFormat,
)


class Color(Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


@dataclasses.dataclass
class Person:
    name: str
    age: int
    email: str


class Point(NamedTuple):
    x: float
    y: float


class TestJSONCodec:
    """JSON codec tests."""

    def setup_method(self):
        self.codec = JSONCodec()
        self.config = CodecConfig(format=SerializationFormat.JSON)

    def test_encode_decode_basic_types(self):
        """Test encoding/decoding basic types."""
        test_cases = [
            None,
            True,
            False,
            42,
            -42,
            3.14,
            "hello",
            "unicode: 你好",
            [],
            [1, 2, 3],
            {},
            {"a": 1, "b": 2},
        ]

        for obj in test_cases:
            encoded = self.codec.encode(obj, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == obj

    def test_encode_decode_datetime(self):
        """Test datetime serialization."""
        dt = datetime(2024, 1, 15, 12, 30, 45)
        encoded = self.codec.encode(dt, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == dt

    def test_encode_decode_date(self):
        """Test date serialization."""
        d = date(2024, 1, 15)
        encoded = self.codec.encode(d, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == d

    def test_encode_decode_time(self):
        """Test time serialization."""
        t = time(12, 30, 45, 123456)
        encoded = self.codec.encode(t, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == t

    def test_encode_decode_uuid(self):
        """Test UUID serialization."""
        u = uuid.uuid4()
        encoded = self.codec.encode(u, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == u

    def test_encode_decode_decimal(self):
        """Test Decimal serialization."""
        values = [Decimal("3.14"), Decimal("0"), Decimal("-123.456")]
        for value in values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value

    def test_encode_decode_bytes(self):
        """Test bytes serialization (base64)."""
        data = b"hello world"
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == data

    def test_encode_decode_enum(self):
        """Test Enum serialization."""
        encoded = self.codec.encode(Color.RED, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Decoded as dict with type info, not Enum
        assert decoded["_enum_type"] == "Color"
        assert decoded["_enum_value"] == "red"

    def test_encode_decode_dataclass(self):
        """Test dataclass serialization."""
        person = Person("Alice", 30, "alice@example.com")
        encoded = self.codec.encode(person, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Decoded as dict with type info
        assert decoded["_dataclass_type"] == "Person"
        assert decoded["_dataclass_data"]["name"] == "Alice"

    def test_encode_decode_namedtuple(self):
        """Test NamedTuple serialization."""
        point = Point(1.5, 2.5)
        encoded = self.codec.encode(point, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Decoded as dict with type info
        assert decoded["_namedtuple_type"] == "Point"
        assert decoded["_namedtuple_data"]["x"] == 1.5

    def test_nested_complex_types(self):
        """Test nested complex types."""
        data = {
            "timestamp": datetime.now(),
            "id": uuid.uuid4(),
            "items": [
                {"price": Decimal("10.99"), "data": b"item1"},
                {"price": Decimal("20.50"), "data": b"item2"},
            ],
        }

        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert isinstance(decoded["timestamp"], datetime)
        assert isinstance(decoded["id"], uuid.UUID)
        assert len(decoded["items"]) == 2

    def test_pretty_print(self):
        """Test pretty print formatting."""
        config = CodecConfig(format=SerializationFormat.JSON, pretty_print=True)
        data = {"name": "Alice", "age": 30}

        encoded = self.codec.encode(data, config)
        # Pretty print should have indentation
        decoded_str = encoded.decode("utf-8")
        assert "\n" in decoded_str or "  " in decoded_str

    def test_allow_nan_disabled(self):
        """Test NaN/Infinity rejection when allow_nan=False."""
        config = CodecConfig(format=SerializationFormat.JSON, allow_nan=False)

        with pytest.raises(SerializationError):
            self.codec.encode(float("nan"), config)

        with pytest.raises(SerializationError):
            self.codec.encode(float("inf"), config)

    def test_allow_nan_enabled(self):
        """Test NaN/Infinity allowed when allow_nan=True."""
        config = CodecConfig(format=SerializationFormat.JSON, allow_nan=True)

        # This should not raise
        encoded_nan = self.codec.encode(float("nan"), config)
        assert encoded_nan is not None

    def test_stream_encode(self):
        """Test streaming JSON encoding."""
        objects = [{"id": 1}, {"id": 2}, {"id": 3}]
        encoded_lines = list(self.codec.stream_encode(iter(objects), self.config))

        assert len(encoded_lines) == 3
        for i, line in enumerate(encoded_lines):
            decoded = json.loads(line.decode("utf-8"))
            assert decoded["id"] == i + 1

    def test_stream_decode(self):
        """Test streaming JSON (JSON Lines) decoding."""
        # Create JSON Lines format
        lines = ['{"id": 1}', '{"id": 2}', '{"id": 3}']
        data = "\n".join(lines).encode("utf-8")

        decoded_objects = list(self.codec.stream_decode(data, self.config))

        assert len(decoded_objects) == 3
        assert [obj["id"] for obj in decoded_objects] == [1, 2, 3]

    def test_streaming_parser_array(self):
        """Test streaming parser with JSON array."""
        data = json.dumps([1, 2, 3, 4, 5]).encode("utf-8")
        items = list(self.codec.encode_streaming_parser(data, self.config))
        assert items == [1, 2, 3, 4, 5]

    def test_streaming_parser_single_object(self):
        """Test streaming parser with single JSON object."""
        data = json.dumps({"key": "value"}).encode("utf-8")
        items = list(self.codec.encode_streaming_parser(data, self.config))
        assert items == [{"key": "value"}]

    def test_invalid_json(self):
        """Test decoding invalid JSON."""
        with pytest.raises(DeserializationError):
            self.codec.decode(b"{invalid json}", self.config)

    def test_invalid_utf8(self):
        """Test decoding invalid UTF-8."""
        with pytest.raises(DeserializationError):
            self.codec.decode(b"\xff\xfe invalid", self.config)

    def test_large_payload(self):
        """Test encoding/decoding large payloads."""
        large_data = {"items": [{"id": i, "value": f"item-{i}" * 10} for i in range(1000)]}

        encoded = self.codec.encode(large_data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert len(decoded["items"]) == 1000
        assert decoded["items"][0]["id"] == 0

    def test_special_characters(self):
        """Test encoding/decoding special characters."""
        test_strings = [
            'quotes: "test"',
            "newlines:\n\t",
            "unicode: 你好世界",
            "symbols: !@#$%^&*()",
            "emoji: 😀🎉",
        ]

        for s in test_strings:
            encoded = self.codec.encode(s, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == s

    def test_circular_reference_handling(self):
        """Test handling of circular references."""
        data = {"a": 1}
        data["self"] = data

        # This should raise an error
        with pytest.raises((SerializationError, ValueError)):
            self.codec.encode(data, self.config)

    def test_empty_containers(self):
        """Test encoding/decoding empty containers."""
        test_cases = [[], {}, "", b""]

        for obj in test_cases:
            encoded = self.codec.encode(obj, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == obj
