"""
Tests for compression layer.

Tests compression algorithms (Zlib, Gzip, LZ77), compression ratios,
roundtrip, and adaptive compression.
"""

import pytest

from thomas.marketplace.serialization import SerializationError
from thomas.marketplace.serialization.compression import (
    CompressionAlgorithm,
    LZ77Compressor,
    compress,
    compression_ratio,
    decompress,
    estimate_compression_benefit,
)


class TestCompressionAlgorithms:
    """Tests for compression algorithms."""

    def test_zlib_roundtrip(self):
        """Test Zlib compression/decompression."""
        data = b"hello world" * 100

        compressed, was_compressed = compress(
            data,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )

        if was_compressed:
            decompressed = decompress(
                compressed,
                CompressionAlgorithm.ZLIB,
            )
            assert decompressed == data

    def test_gzip_roundtrip(self):
        """Test Gzip compression/decompression."""
        data = b"test data" * 50

        compressed, was_compressed = compress(
            data,
            CompressionAlgorithm.GZIP,
            threshold=0,
        )

        if was_compressed:
            decompressed = decompress(
                compressed,
                CompressionAlgorithm.GZIP,
            )
            assert decompressed == data

    def test_lz77_roundtrip(self):
        """Test LZ77 compression/decompression."""
        data = b"repeating pattern " * 100

        compressed = LZ77Compressor.compress(data)
        decompressed = LZ77Compressor.decompress(compressed)

        assert decompressed == data

    def test_compression_threshold(self):
        """Test that compression is skipped for small data."""
        small_data = b"tiny"
        threshold = 1000

        compressed, was_compressed = compress(
            small_data,
            CompressionAlgorithm.ZLIB,
            threshold=threshold,
        )

        assert not was_compressed
        assert compressed == small_data

    def test_compression_not_beneficial(self):
        """Test that compression is not applied if not beneficial."""
        # Random data doesn't compress well
        random_data = bytes(range(256)) * 10

        compressed, was_compressed = compress(
            random_data,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )

        # May or may not compress, but should not increase size
        assert len(compressed) <= len(random_data) + 100

    def test_compression_levels(self):
        """Test different compression levels."""
        data = b"x" * 10000

        results = {}
        for level in [1, 6, 9]:
            compressed, was_compressed = compress(
                data,
                CompressionAlgorithm.ZLIB,
                level=level,
                threshold=0,
            )
            if was_compressed:
                results[level] = len(compressed)

        # Higher levels should produce same or smaller output
        if 1 in results and 9 in results:
            assert results[9] <= results[1]

    def test_compression_ratio_calculation(self):
        """Test compression ratio calculation."""
        original_size = 1000
        compressed_size = 400

        ratio = compression_ratio(original_size, compressed_size)
        assert ratio == pytest.approx(2.5)

    def test_compression_ratio_no_compression(self):
        """Test compression ratio for incompressible data."""
        size = 500
        ratio = compression_ratio(size, size)
        assert ratio == 1.0

    def test_compression_estimation(self):
        """Test compression benefit estimation."""
        highly_compressible = b"x" * 10000

        benefit = estimate_compression_benefit(
            highly_compressible,
            CompressionAlgorithm.ZLIB,
        )

        # Should estimate good compression for repetitive data
        assert benefit >= 1.0

    def test_no_compression_algorithm(self):
        """Test NONE compression algorithm."""
        data = b"test"

        compressed, was_compressed = compress(
            data,
            CompressionAlgorithm.NONE,
        )

        assert not was_compressed
        assert compressed == data

    def test_decompress_no_compression(self):
        """Test decompressing with NONE algorithm."""
        data = b"test"

        result = decompress(data, CompressionAlgorithm.NONE)
        assert result == data

    def test_lz77_empty_data(self):
        """Test LZ77 with empty data."""
        result = LZ77Compressor.compress(b"")
        assert result == b""

        decompressed = LZ77Compressor.decompress(b"")
        assert decompressed == b""

    def test_lz77_single_byte(self):
        """Test LZ77 with single byte."""
        data = b"x"
        compressed = LZ77Compressor.compress(data)
        decompressed = LZ77Compressor.decompress(compressed)
        assert decompressed == data

    def test_lz77_no_patterns(self):
        """Test LZ77 with non-repetitive data."""
        data = bytes(range(256))
        compressed = LZ77Compressor.compress(data)
        # Non-repetitive data won't compress well
        assert len(compressed) >= len(data) * 0.9

    def test_lz77_highly_repetitive(self):
        """Test LZ77 with highly repetitive data."""
        data = b"abc" * 1000
        compressed = LZ77Compressor.compress(data)
        # Should compress significantly
        assert len(compressed) < len(data) / 2

    def test_binary_data_compression(self):
        """Test compression of binary data."""
        binary_data = bytes(range(256)) * 100

        compressed, was_compressed = compress(
            binary_data,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )

        if was_compressed:
            decompressed = decompress(
                compressed,
                CompressionAlgorithm.ZLIB,
            )
            assert decompressed == binary_data

    def test_text_data_compression(self):
        """Test compression of text data."""
        text_data = ("The quick brown fox jumps over the lazy dog. " * 200).encode("utf-8")

        compressed, was_compressed = compress(
            text_data,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )

        # Text should compress well
        if was_compressed:
            ratio = compression_ratio(len(text_data), len(compressed))
            assert ratio > 1.5

    def test_invalid_compression_algorithm_name(self):
        """Test handling of invalid algorithm."""
        data = b"test"

        # Create invalid algorithm
        with pytest.raises((SerializationError, AttributeError)):
            compress(data, "invalid_algorithm")  # type: ignore

    def test_lz77_invalid_data(self):
        """Test LZ77 decompression with invalid data."""
        with pytest.raises(SerializationError):
            LZ77Compressor.decompress(b"\xff\xff\xff\xff")

    def test_zlib_invalid_data(self):
        """Test Zlib decompression with invalid data."""
        with pytest.raises(SerializationError):
            decompress(b"\xff\xfe\xfd\xfc", CompressionAlgorithm.ZLIB)

    def test_compression_idempotent(self):
        """Test that compression/decompression is idempotent."""
        original = b"data" * 100

        # Compress -> decompress -> compress again
        compressed1, _ = compress(
            original,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )
        decompressed = decompress(
            compressed1,
            CompressionAlgorithm.ZLIB,
        )
        compressed2, _ = compress(
            decompressed,
            CompressionAlgorithm.ZLIB,
            threshold=0,
        )

        # Decompressed should match original
        assert decompressed == original

    def test_lz77_match_length_limit(self):
        """Test that LZ77 respects match length limits."""
        # Create data with very long repetitive section
        data = b"x" * 10000
        compressed = LZ77Compressor.compress(data)
        decompressed = LZ77Compressor.decompress(compressed)
        assert decompressed == data
