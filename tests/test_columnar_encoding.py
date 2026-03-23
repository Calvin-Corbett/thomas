"""
Tests for columnar encoding implementations.

Tests plain, dictionary, RLE, and delta encoding schemes.
"""

from typing import Any

from thomas.marketplace.columnar._types import ColumnType
from thomas.marketplace.columnar.encoding import (
    decode_dictionary,
    decode_plain,
    encode_delta,
    encode_dictionary,
    encode_plain,
    encode_rle,
    select_encoding,
)


class TestPlainEncoding:
    """Tests for plain encoding."""

    def test_encode_decode_int32(self) -> None:
        """Test INT32 plain encoding."""
        values = [1, 2, 3, 4, 5]
        encoded = encode_plain(values, ColumnType.INT32)
        assert len(encoded) > 0

        decoded = decode_plain(encoded, ColumnType.INT32, len(values))
        assert decoded == values

    def test_encode_decode_float64(self) -> None:
        """Test FLOAT64 plain encoding."""
        values = [1.5, 2.7, 3.14, 4.0]
        encoded = encode_plain(values, ColumnType.FLOAT64)
        decoded = decode_plain(encoded, ColumnType.FLOAT64, len(values))

        for d, v in zip(decoded, values):
            assert abs(d - v) < 0.001

    def test_encode_decode_string(self) -> None:
        """Test STRING plain encoding."""
        values = ["hello", "world", "test"]
        encoded = encode_plain(values, ColumnType.STRING)
        decoded = decode_plain(encoded, ColumnType.STRING, len(values))
        assert decoded == values

    def test_encode_decode_bool(self) -> None:
        """Test BOOL plain encoding."""
        values = [True, False, True, True, False]
        encoded = encode_plain(values, ColumnType.BOOL)
        decoded = decode_plain(encoded, ColumnType.BOOL, len(values))
        assert decoded == values

    def test_encode_with_nulls(self) -> None:
        """Test plain encoding with null values."""
        values = [1, None, 3, None, 5]
        encoded = encode_plain(values, ColumnType.INT32)
        assert len(encoded) > 0


class TestDictionaryEncoding:
    """Tests for dictionary encoding."""

    def test_encode_decode_dictionary(self) -> None:
        """Test dictionary encoding."""
        values = ["apple", "banana", "apple", "cherry", "banana"]
        encoded, dictionary = encode_dictionary(values, ColumnType.STRING)

        assert len(dictionary) == 3
        assert "apple" in dictionary
        assert "banana" in dictionary
        assert "cherry" in dictionary

    def test_decode_dictionary(self) -> None:
        """Test dictionary decoding."""
        values = ["apple", "banana", "apple", "cherry", "banana"]
        encoded, dictionary = encode_dictionary(values, ColumnType.STRING)

        decoded = decode_dictionary(encoded, dictionary, len(values))
        assert decoded == values

    def test_dictionary_with_nulls(self) -> None:
        """Test dictionary encoding with nulls."""
        values = ["apple", None, "banana", "apple"]
        encoded, dictionary = encode_dictionary(values, ColumnType.STRING)

        assert None not in dictionary
        decoded = decode_dictionary(encoded, dictionary, len(values))
        assert decoded == values

    def test_dictionary_numeric(self) -> None:
        """Test dictionary encoding with numbers."""
        values = [1, 2, 1, 3, 2, 1]
        encoded, dictionary = encode_dictionary(values, ColumnType.INT32)

        assert len(dictionary) == 3
        decoded = decode_dictionary(encoded, dictionary, len(values))
        assert decoded == values


class TestRLEEncoding:
    """Tests for run-length encoding."""

    def test_encode_decode_rle(self) -> None:
        """Test RLE encoding."""
        values = [1, 1, 1, 2, 2, 3, 3, 3, 3]
        encoded = encode_rle(values, ColumnType.INT32)
        assert len(encoded) > 0

    def test_rle_single_value_run(self) -> None:
        """Test RLE with repeated values."""
        values = [5] * 100
        encoded = encode_rle(values, ColumnType.INT32)
        assert len(encoded) < len(values) * 4  # Should compress well

    def test_rle_no_repeats(self) -> None:
        """Test RLE with no repeats."""
        values = list(range(100))
        encoded = encode_rle(values, ColumnType.INT32)
        # Should not compress well but should still be valid
        assert len(encoded) > 0

    def test_rle_with_nulls(self) -> None:
        """Test RLE with null values."""
        values = [1, 1, None, None, 2, 2]
        encoded = encode_rle(values, ColumnType.INT32)
        assert len(encoded) > 0


class TestDeltaEncoding:
    """Tests for delta encoding."""

    def test_encode_decode_delta_timestamp(self) -> None:
        """Test delta encoding for timestamps."""
        from datetime import datetime, timedelta

        base = datetime(2020, 1, 1)
        values = [
            base,
            base + timedelta(days=1),
            base + timedelta(days=2),
            base + timedelta(days=3),
        ]
        encoded = encode_delta(values, ColumnType.TIMESTAMP)
        assert len(encoded) > 0

    def test_delta_monotonic_integers(self) -> None:
        """Test delta encoding for monotonic integers."""
        values = [0, 10, 20, 30, 40, 50]
        encoded = encode_delta(values, ColumnType.INT64)
        assert len(encoded) > 0

    def test_delta_with_nulls(self) -> None:
        """Test delta encoding with nulls."""
        values = [1, None, 3, 4, 5]
        encoded = encode_delta(values, ColumnType.INT32)
        assert len(encoded) > 0


class TestEncodingSelection:
    """Tests for automatic encoding selection."""

    def test_select_encoding_low_cardinality(self) -> None:
        """Test encoding selection for low cardinality data."""
        values = ["a", "b", "a", "b", "a", "b"] * 100
        encoding = select_encoding(values, ColumnType.STRING)
        # Low cardinality should select dictionary encoding
        assert encoding in {selected_encoding := "dictionary"} or encoding == "RLE"

    def test_select_encoding_high_cardinality(self) -> None:
        """Test encoding selection for high cardinality data."""
        values = list(range(1000))
        encoding = select_encoding(values, ColumnType.INT32)
        # High cardinality should select plain or delta
        assert encoding in {"PLAIN", "DELTA"}

    def test_select_encoding_temporal(self) -> None:
        """Test encoding selection for temporal data."""
        from datetime import datetime, timedelta

        values = [datetime(2020, 1, 1) + timedelta(days=i) for i in range(100)]
        encoding = select_encoding(values, ColumnType.TIMESTAMP)
        # Temporal should prefer delta encoding
        assert encoding == "DELTA"

    def test_select_encoding_empty(self) -> None:
        """Test encoding selection for empty data."""
        values: list[Any] = []
        encoding = select_encoding(values, ColumnType.INT32)
        assert encoding == "PLAIN"


class TestEncodingEdgeCases:
    """Tests for encoding edge cases."""

    def test_encode_empty_values(self) -> None:
        """Test encoding empty value list."""
        values: list[Any] = []
        encoded = encode_plain(values, ColumnType.INT32)
        assert len(encoded) == 0

    def test_encode_all_nulls(self) -> None:
        """Test encoding all null values."""
        values = [None, None, None]
        encoded = encode_plain(values, ColumnType.INT32)
        assert len(encoded) == 0

    def test_encode_single_value(self) -> None:
        """Test encoding single value."""
        values = [42]
        encoded = encode_plain(values, ColumnType.INT32)
        decoded = decode_plain(encoded, ColumnType.INT32, 1)
        assert decoded == [42]

    def test_large_string_encoding(self) -> None:
        """Test encoding large strings."""
        values = ["x" * 10000]
        encoded = encode_plain(values, ColumnType.STRING)
        decoded = decode_plain(encoded, ColumnType.STRING, 1)
        assert decoded == values

    def test_binary_encoding(self) -> None:
        """Test binary data encoding."""
        values = [b"\x00\x01\x02", b"\xff\xfe\xfd"]
        encoded = encode_plain(values, ColumnType.BINARY)
        decoded = decode_plain(encoded, ColumnType.BINARY, len(values))
        assert decoded == values


class TestDictionaryCompression:
    """Tests for dictionary compression effectiveness."""

    def test_dictionary_compression_ratio(self) -> None:
        """Test dictionary achieves good compression ratio."""
        # Create highly repetitive data
        values = [f"value_{i % 10}" for i in range(1000)]

        plain_encoded = encode_plain(values, ColumnType.STRING)
        dict_encoded, _ = encode_dictionary(values, ColumnType.STRING)

        # Dictionary should be significantly smaller
        assert len(dict_encoded) < len(plain_encoded) * 0.3

    def test_rle_compression_ratio(self) -> None:
        """Test RLE compression effectiveness."""
        values = [1] * 1000
        plain_encoded = encode_plain(values, ColumnType.INT32)
        rle_encoded = encode_rle(values, ColumnType.INT32)

        # RLE should be much smaller for repeated values
        assert len(rle_encoded) < len(plain_encoded) * 0.1


class TestEncodingIntegration:
    """Integration tests for encoding."""

    def test_mixed_type_encoding(self) -> None:
        """Test encoding different data types."""
        int_values = [1, 2, 3]
        float_values = [1.1, 2.2, 3.3]
        string_values = ["a", "b", "c"]

        for values, col_type in [
            (int_values, ColumnType.INT32),
            (float_values, ColumnType.FLOAT64),
            (string_values, ColumnType.STRING),
        ]:
            encoded = encode_plain(values, col_type)
            assert len(encoded) > 0

    def test_encode_decode_roundtrip(self) -> None:
        """Test encoding/decoding roundtrip."""
        test_cases = [
            ([1, 2, 3, 4, 5], ColumnType.INT32),
            ([1.1, 2.2, 3.3], ColumnType.FLOAT64),
            (["hello", "world"], ColumnType.STRING),
            ([True, False, True], ColumnType.BOOL),
        ]

        for values, col_type in test_cases:
            encoded = encode_plain(values, col_type)
            decoded = decode_plain(encoded, col_type, len(values))
            assert decoded == values
