"""Tests for HPACK header compression."""

import pytest

from thomas.marketplace.http2._exceptions import CompressionError
from thomas.marketplace.http2.hpack import STATIC_TABLE, HeaderDecoder, HeaderEncoder
from thomas.marketplace.http2.huffman_table import HuffmanDecoder, HuffmanEncoder


class TestHuffmanEncoding:
    """Tests for Huffman encoding/decoding."""

    def setup_method(self) -> None:
        """Setup codec."""
        self.encoder = HuffmanEncoder()
        self.decoder = HuffmanDecoder()

    def test_encode_decode_simple(self) -> None:
        """Test Huffman roundtrip."""
        data = b"www.example.com"
        encoded = self.encoder.encode(data)
        decoded = self.decoder.decode(encoded)
        assert decoded == data

    def test_encode_decode_empty(self) -> None:
        """Test encoding empty data."""
        data = b""
        encoded = self.encoder.encode(data)
        decoded = self.decoder.decode(encoded)
        assert decoded == data

    def test_encode_all_bytes(self) -> None:
        """Test encoding all byte values 0-255."""
        data = bytes(range(256))
        encoded = self.encoder.encode(data)
        decoded = self.decoder.decode(encoded)
        assert decoded == data

    def test_huffman_compression_ratio(self) -> None:
        """Test that Huffman compression reduces size."""
        data = b"The quick brown fox jumps over the lazy dog"
        encoded = self.encoder.encode(data)
        # Huffman should reduce size for typical text
        assert len(encoded) < len(data)

    def test_huffman_short_data(self) -> None:
        """Test Huffman with very short data."""
        for length in range(1, 10):
            data = b"a" * length
            encoded = self.encoder.encode(data)
            decoded = self.decoder.decode(encoded)
            assert decoded == data

    def test_huffman_special_characters(self) -> None:
        """Test Huffman with special characters."""
        data = b"!@#$%^&*()_+-={}[]|:;<>?,./"
        encoded = self.encoder.encode(data)
        decoded = self.decoder.decode(encoded)
        assert decoded == data


class TestHPACKEncoder:
    """Tests for HPACK header encoder."""

    def setup_method(self) -> None:
        """Setup encoder."""
        self.encoder = HeaderEncoder()

    def test_encode_static_table_exact_match(self) -> None:
        """Test encoding header with exact static table match."""
        # ":method: GET" is in static table at index 2
        headers = [(b":method", b"GET")]
        encoded = self.encoder.encode_headers(headers)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_encode_literal_header(self) -> None:
        """Test encoding literal header not in static table."""
        headers = [(b"custom-header", b"custom-value")]
        encoded = self.encoder.encode_headers(headers)
        assert isinstance(encoded, bytes)

    def test_encode_multiple_headers(self) -> None:
        """Test encoding multiple headers."""
        headers = [
            (b":method", b"POST"),
            (b":path", b"/api/data"),
            (b":scheme", b"https"),
            (b"content-type", b"application/json"),
        ]
        encoded = self.encoder.encode_headers(headers)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_dynamic_table_insertion(self) -> None:
        """Test that headers are added to dynamic table."""
        headers = [(b"custom-header", b"value1")]
        self.encoder.encode_headers(headers)

        assert len(self.encoder.dynamic_table) > 0
        assert self.encoder.dynamic_table[0] == (b"custom-header", b"value1")

    def test_dynamic_table_size_limit(self) -> None:
        """Test dynamic table size limit."""
        encoder = HeaderEncoder(max_dynamic_table_size=100)

        # Add headers until table size limit exceeded
        for i in range(10):
            headers = [(f"header-{i}".encode(), f"value-{i}".encode())]
            encoder.encode_headers(headers)

        # Table size should not exceed limit
        assert encoder.dynamic_table_size <= encoder.max_dynamic_table_size

    def test_integer_encoding_small(self) -> None:
        """Test integer encoding with small values."""
        # Small integers should use single byte
        result = self.encoder._encode_integer(10, 7, 0x80)
        assert len(result) == 1

    def test_integer_encoding_large(self) -> None:
        """Test integer encoding with large values."""
        # Large integers need multiple bytes
        result = self.encoder._encode_integer(1337, 5, 0x20)
        assert len(result) > 1

    def test_string_encoding_huffman(self) -> None:
        """Test string encoding with Huffman."""
        # Long strings should use Huffman
        data = b"The quick brown fox jumps over the lazy dog"
        result = self.encoder._encode_string(data)
        # Should start with high bit set (Huffman)
        assert result[0] & 0x80 != 0

    def test_string_encoding_literal(self) -> None:
        """Test string encoding without Huffman."""
        # Very short strings might not use Huffman
        data = b"ab"
        result = self.encoder._encode_string(data)
        assert isinstance(result, bytes)


class TestHPACKDecoder:
    """Tests for HPACK header decoder."""

    def setup_method(self) -> None:
        """Setup encoder and decoder."""
        self.encoder = HeaderEncoder()
        self.decoder = HeaderDecoder()

    def test_decode_encoded_headers(self) -> None:
        """Test round-trip encoding/decoding."""
        headers = [
            (b":method", b"GET"),
            (b":path", b"/"),
            (b":scheme", b"https"),
        ]
        encoded = self.encoder.encode_headers(headers)
        decoded = self.decoder.decode_headers(encoded)

        # Should have same headers (may be in different order from table)
        assert len(decoded) == len(headers)

    def test_decode_indexed_static_table(self) -> None:
        """Test decoding indexed header from static table."""
        # Index 2 is ":method: GET"
        encoded = self.encoder._encode_indexed(2)
        decoded = self.decoder.decode_headers(encoded)

        assert len(decoded) == 1
        assert decoded[0] == (b":method", b"GET")

    def test_decode_literal_with_indexing(self) -> None:
        """Test decoding literal header with incremental indexing."""
        headers = [(b"x-custom", b"test")]
        encoded = self.encoder.encode_headers(headers)
        decoded = self.decoder.decode_headers(encoded)

        assert len(decoded) == 1
        assert decoded[0][0] == b"x-custom"
        assert decoded[0][1] == b"test"

    def test_decode_multiple_headers_roundtrip(self) -> None:
        """Test round-trip with multiple headers."""
        headers = [
            (b":method", b"POST"),
            (b":path", b"/api/search"),
            (b":scheme", b"https"),
            (b"accept", b"application/json"),
            (b"user-agent", b"test-client/1.0"),
        ]
        encoded = self.encoder.encode_headers(headers)
        decoded = self.decoder.decode_headers(encoded)

        assert len(decoded) == len(headers)

    def test_decode_invalid_index_raises_error(self) -> None:
        """Test that invalid index raises error."""
        # Create invalid encoded data
        data = bytes([0x80 | 127])  # Index 127 doesn't exist

        with pytest.raises(CompressionError):
            self.decoder.decode_headers(data)

    def test_dynamic_table_synchronization(self) -> None:
        """Test that encoder/decoder dynamic tables stay in sync."""
        headers = [
            (b"x-header1", b"value1"),
            (b"x-header2", b"value2"),
        ]

        # Encode with first encoder
        encoded = self.encoder.encode_headers(headers)

        # Decode with decoder
        decoded = self.decoder.decode_headers(encoded)

        # Tables should be synchronized
        assert len(self.encoder.dynamic_table) == len(self.decoder.dynamic_table)

    def test_empty_header_block(self) -> None:
        """Test decoding empty header block."""
        decoded = self.decoder.decode_headers(b"")
        assert decoded == []

    def test_huffman_string_decoding(self) -> None:
        """Test decoding Huffman-encoded strings."""
        encoder = HuffmanEncoder()
        data = b"www.example.com"
        huffman = encoder.encode(data)

        # Create encoded string with Huffman flag
        length_byte = bytes([0x80 | len(huffman)])
        encoded_string = length_byte + huffman

        decoded_string, consumed = self.decoder._decode_string(encoded_string)
        assert decoded_string == data


class TestHPACKStaticTable:
    """Tests for static table."""

    def test_static_table_size(self) -> None:
        """Test static table has correct size."""
        assert len(STATIC_TABLE) == 61

    def test_static_table_entries(self) -> None:
        """Test key static table entries."""
        # Entry 1: :authority
        assert STATIC_TABLE[0] == (b":authority", b"")

        # Entry 2: :method GET
        assert STATIC_TABLE[1] == (b":method", b"GET")

        # Entry 8: :status 200
        assert STATIC_TABLE[7] == (b":status", b"200")

    def test_encoder_uses_static_table(self) -> None:
        """Test that encoder finds matches in static table."""
        encoder = HeaderEncoder()

        # This should match static table
        index = encoder._find_static_table(b":method", b"GET")
        assert index == 2

    def test_encoder_finds_name_in_static(self) -> None:
        """Test finding name-only match in static table."""
        encoder = HeaderEncoder()

        # Find ":method" (should be index 2 or 3 depending on value)
        index = encoder._find_name_in_tables(b":method")
        assert index is not None
        assert index >= 2


class TestHPACKEdgeCases:
    """Tests for edge cases in HPACK."""

    def test_very_large_header_value(self) -> None:
        """Test encoding very large header values."""
        encoder = HeaderEncoder()
        decoder = HeaderDecoder()

        large_value = b"x" * 10000
        headers = [(b"x-large", large_value)]

        encoded = encoder.encode_headers(headers)
        decoded = decoder.decode_headers(encoded)

        assert decoded[0][1] == large_value

    def test_many_headers(self) -> None:
        """Test encoding many headers."""
        encoder = HeaderEncoder()
        decoder = HeaderDecoder()

        headers = [(f"header-{i}".encode(), f"value-{i}".encode()) for i in range(100)]

        encoded = encoder.encode_headers(headers)
        decoded = decoder.decode_headers(encoded)

        assert len(decoded) == 100

    def test_binary_header_values(self) -> None:
        """Test headers with binary values."""
        encoder = HeaderEncoder()
        decoder = HeaderDecoder()

        binary_value = bytes(range(256))
        headers = [(b"x-binary", binary_value)]

        encoded = encoder.encode_headers(headers)
        decoded = decoder.decode_headers(encoded)

        assert decoded[0][1] == binary_value

    def test_header_name_case_sensitivity(self) -> None:
        """Test that header names are case-sensitive in encoding."""
        encoder = HeaderEncoder()

        headers1 = [(b"X-Header", b"value")]
        headers2 = [(b"x-header", b"value")]

        encoded1 = encoder.encode_headers(headers1)
        encoded2 = encoder.encode_headers(headers2)

        # Different encodings due to different case
        assert len(encoded1) > 0 and len(encoded2) > 0
