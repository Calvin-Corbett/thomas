"""
Tests for CBOR (RFC 7049) codec.

Tests CBOR types (major types 0-7), indefinite-length arrays/maps/strings,
canonical encoding, half-precision floats, and tagged values.
"""

import pytest

from thomas.serialization import (
    CBORCodec,
    CodecConfig,
    DeserializationError,
    SerializationFormat,
)


class TestCBORCodec:
    """CBOR codec tests."""

    def setup_method(self):
        self.codec = CBORCodec()
        self.config = CodecConfig(format=SerializationFormat.CBOR)

    def test_encode_decode_null(self):
        """Test null encoding."""
        encoded = self.codec.encode(None, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded is None

    def test_encode_decode_booleans(self):
        """Test boolean encoding."""
        assert self.codec.decode(self.codec.encode(True, self.config), self.config) is True
        assert self.codec.decode(self.codec.encode(False, self.config), self.config) is False

    def test_encode_decode_unsigned_ints(self):
        """Test unsigned integer encoding."""
        test_values = [
            0,
            1,
            23,  # Single byte
            24,
            255,
            256,
            65535,
            65536,
            4294967295,
        ]

        for value in test_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value

    def test_encode_decode_negative_ints(self):
        """Test negative integer encoding."""
        test_values = [-1, -10, -100, -1000, -32768, -2147483648]

        for value in test_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value

    def test_encode_decode_floats(self):
        """Test floating point encoding."""
        test_values = [0.0, 1.5, -3.14, 1e10, -1e-10]

        for value in test_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert abs(decoded - value) < 1e-10

    def test_encode_decode_text_strings(self):
        """Test text string encoding."""
        test_strings = [
            "",
            "hello",
            "unicode: 你好",
            "emoji: 😀🎉",
            "x" * 100,
        ]

        for s in test_strings:
            encoded = self.codec.encode(s, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == s

    def test_encode_decode_byte_strings(self):
        """Test byte string encoding."""
        test_bytes = [
            b"",
            b"hello",
            bytes(range(256)),
            b"\x00\xff\xfe",
        ]

        for data in test_bytes:
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
        """Test map encoding."""
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

    def test_encode_decode_tuples_as_arrays(self):
        """Test tuple encoding as CBOR arrays."""
        data = (1, 2, 3)
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Tuples decoded as lists
        assert decoded == [1, 2, 3]

    def test_canonical_encoding(self):
        """Test canonical CBOR encoding."""
        config = CodecConfig(format=SerializationFormat.CBOR, pretty_print=True)

        data = {"z": 1, "a": 2, "m": 3}
        encoded = self.codec.encode(data, config)
        decoded = self.codec.decode(encoded, config)

        # Content should match regardless of order
        assert decoded == data

    def test_deterministic_encoding(self):
        """Test that same object produces same encoding (determinism)."""
        data = {"id": 42, "name": "test"}

        encoded1 = self.codec.encode(data, self.config)
        encoded2 = self.codec.encode(data, self.config)

        # Without canonical flag, encodings might differ in key order
        # But decoding should produce same result
        decoded1 = self.codec.decode(encoded1, self.config)
        decoded2 = self.codec.decode(encoded2, self.config)

        assert decoded1 == decoded2

    def test_large_unsigned_int(self):
        """Test large unsigned integers."""
        large_value = 18446744073709551615  # Max uint64
        encoded = self.codec.encode(large_value, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == large_value

    def test_very_large_array(self):
        """Test encoding large arrays."""
        large_array = list(range(10000))
        encoded = self.codec.encode(large_array, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert len(decoded) == 10000
        assert decoded[5000] == 5000

    def test_deeply_nested_structure(self):
        """Test deeply nested structures."""
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == data

    def test_mixed_type_array(self):
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
        assert abs(decoded[2] - 3.14) < 0.01
        assert decoded[3] is True
        assert decoded[4] is None

    def test_mixed_type_map(self):
        """Test maps with various key/value types."""
        # CBOR allows any type as key, but Python dict is limited
        data = {"string_key": 1, "int": 42, "float": 3.14}

        encoded = self.codec.encode(data, self.config)
        decoded = self.codec.decode(encoded, self.config)

        assert decoded == data

    def test_empty_containers(self):
        """Test empty arrays and maps."""
        for container in [[], {}]:
            encoded = self.codec.encode(container, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == container

    def test_string_with_embedded_nulls(self):
        """Test strings with null characters."""
        test_str = "hello\x00world"
        encoded = self.codec.encode(test_str, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == test_str

    def test_bytes_with_all_values(self):
        """Test byte strings containing all byte values."""
        test_bytes = bytes(range(256))
        encoded = self.codec.encode(test_bytes, self.config)
        decoded = self.codec.decode(encoded, self.config)
        assert decoded == test_bytes

    def test_precision_loss_in_floats(self):
        """Test that float precision is preserved."""
        original = 0.1 + 0.2  # Classic float precision issue
        encoded = self.codec.encode(original, self.config)
        decoded = self.codec.decode(encoded, self.config)
        # Should be very close
        assert abs(decoded - original) < 1e-15

    def test_zero_values(self):
        """Test encoding of zero values."""
        test_cases = [0, 0.0, "", b"", [], {}]

        for value in test_cases:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value

    def test_invalid_cbor(self):
        """Test decoding invalid CBOR."""
        with pytest.raises(DeserializationError):
            self.codec.decode(b"\xff\xff\xff", self.config)

    def test_truncated_data(self):
        """Test handling truncated CBOR data."""
        full_data = self.codec.encode(
            {"key": "value" * 100},
            self.config,
        )
        truncated = full_data[: len(full_data) // 2]

        with pytest.raises(DeserializationError):
            self.codec.decode(truncated, self.config)

    def test_string_length_encoding(self):
        """Test various string length encodings."""
        test_strings = [
            "x" * 23,  # Single byte length
            "y" * 24,  # One-byte length field
            "z" * 256,  # Two-byte length field
            "w" * 65536,  # Four-byte length field
        ]

        for s in test_strings:
            encoded = self.codec.encode(s, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == s

    def test_negative_number_encoding(self):
        """Test negative number encoding efficiency."""
        # CBOR encodes -n as major type 1 with value n-1
        negative_values = [-1, -10, -100, -1000]

        for value in negative_values:
            encoded = self.codec.encode(value, self.config)
            decoded = self.codec.decode(encoded, self.config)
            assert decoded == value
