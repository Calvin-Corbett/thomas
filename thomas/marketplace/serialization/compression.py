"""
Compression layer for serialized data.

Provides compression/decompression using Zlib, Gzip, and a custom LZ77-style
compressor. Includes compression ratio tracking and adaptive compression
that skips compression if it provides little benefit.
"""

import gzip
import zlib
from enum import Enum

from .exceptions import SerializationError


class CompressionAlgorithm(str, Enum):
    """Supported compression algorithms."""

    NONE = "none"
    ZLIB = "zlib"
    GZIP = "gzip"
    LZ77 = "lz77"


class LZ77Compressor:
    """Simple LZ77-style compression implementation."""

    WINDOW_SIZE = 32768  # 32KB window
    MIN_MATCH = 3
    MAX_MATCH = 258

    @staticmethod
    def compress(data: bytes) -> bytes:
        """Compress data using LZ77 algorithm.

        Args:
            data: Bytes to compress.

        Returns:
            Compressed bytes.
        """
        if not data:
            return b""

        result = bytearray()
        i = 0

        while i < len(data):
            # Find best match in window
            best_match_len = 0
            best_match_dist = 0

            window_start = max(0, i - LZ77Compressor.WINDOW_SIZE)
            for j in range(window_start, i):
                match_len = 0
                while (
                    match_len < LZ77Compressor.MAX_MATCH
                    and i + match_len < len(data)
                    and data[j + match_len] == data[i + match_len]
                ):
                    match_len += 1

                if match_len >= LZ77Compressor.MIN_MATCH and match_len > best_match_len:
                    best_match_len = match_len
                    best_match_dist = i - j

            if best_match_len >= LZ77Compressor.MIN_MATCH:
                # Encode match: 0xFF + distance (2 bytes) + length (1 byte)
                result.append(0xFF)
                result.extend(best_match_dist.to_bytes(2, byteorder="big"))
                result.append(best_match_len)
                i += best_match_len
            else:
                # Literal byte
                byte = data[i]
                if byte == 0xFF:
                    result.append(0xFF)
                    result.append(0x00)
                else:
                    result.append(byte)
                i += 1

        return bytes(result)

    @staticmethod
    def decompress(data: bytes) -> bytes:
        """Decompress LZ77-compressed data.

        Args:
            data: Compressed bytes.

        Returns:
            Decompressed bytes.

        Raises:
            SerializationError: If decompression fails.
        """
        try:
            result = bytearray()
            i = 0

            while i < len(data):
                byte = data[i]

                if byte == 0xFF:
                    if i + 1 >= len(data):
                        break

                    next_byte = data[i + 1]
                    if next_byte == 0x00:
                        # Escaped 0xFF
                        result.append(0xFF)
                        i += 2
                    else:
                        # Match: distance (2) + length (1)
                        if i + 3 >= len(data):
                            break

                        distance = int.from_bytes(data[i + 1 : i + 3], byteorder="big")
                        length = data[i + 3]

                        # Copy from history
                        start_pos = len(result) - distance
                        for _ in range(length):
                            if start_pos < len(result):
                                result.append(result[start_pos])
                                start_pos += 1

                        i += 4
                else:
                    result.append(byte)
                    i += 1

            return bytes(result)
        except Exception as e:
            raise SerializationError(f"LZ77 decompression failed: {e}") from e


def compress(
    data: bytes,
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZLIB,
    level: int = 6,
    threshold: int = 256,
) -> tuple[bytes, bool]:
    """Compress data if it provides benefit.

    Args:
        data: Bytes to compress.
        algorithm: Compression algorithm to use.
        level: Compression level (1-9 for ZLIB/GZIP, ignored for LZ77).
        threshold: Skip compression if payload < threshold bytes.

    Returns:
        Tuple of (compressed_data, was_compressed).
        If compression didn't help, returns (original_data, False).

    Raises:
        SerializationError: If compression fails.
    """
    if len(data) < threshold:
        return data, False

    try:
        if algorithm == CompressionAlgorithm.ZLIB:
            compressed = zlib.compress(data, level)
        elif algorithm == CompressionAlgorithm.GZIP:
            compressed = gzip.compress(data, compresslevel=level)
        elif algorithm == CompressionAlgorithm.LZ77:
            compressed = LZ77Compressor.compress(data)
        elif algorithm == CompressionAlgorithm.NONE:
            return data, False
        else:
            raise SerializationError(f"Unknown compression algorithm: {algorithm}")

        # Only use compression if it actually reduces size
        if len(compressed) < len(data):
            return compressed, True
        else:
            return data, False

    except SerializationError:
        raise
    except Exception as e:
        raise SerializationError(f"Compression failed: {e}") from e


def decompress(
    data: bytes,
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZLIB,
) -> bytes:
    """Decompress data.

    Args:
        data: Compressed bytes.
        algorithm: Decompression algorithm to use.

    Returns:
        Decompressed bytes.

    Raises:
        SerializationError: If decompression fails.
    """
    try:
        if algorithm == CompressionAlgorithm.ZLIB:
            return zlib.decompress(data)
        elif algorithm == CompressionAlgorithm.GZIP:
            return gzip.decompress(data)
        elif algorithm == CompressionAlgorithm.LZ77:
            return LZ77Compressor.decompress(data)
        elif algorithm == CompressionAlgorithm.NONE:
            return data
        else:
            raise SerializationError(f"Unknown compression algorithm: {algorithm}")

    except SerializationError:
        raise
    except Exception as e:
        raise SerializationError(f"Decompression failed: {e}") from e


def compression_ratio(original_size: int, compressed_size: int) -> float:
    """Calculate compression ratio.

    Args:
        original_size: Size before compression.
        compressed_size: Size after compression.

    Returns:
        Ratio of original/compressed (> 1.0 means good compression).
    """
    if compressed_size == 0:
        return 0.0
    return original_size / compressed_size


def estimate_compression_benefit(
    data: bytes,
    algorithm: CompressionAlgorithm = CompressionAlgorithm.ZLIB,
    level: int = 1,  # Use low level for estimation
) -> float:
    """Estimate compression benefit without actually compressing.

    Args:
        data: Bytes to estimate compression for.
        algorithm: Compression algorithm.
        level: Compression level for estimation.

    Returns:
        Estimated compression ratio.
    """
    if len(data) < 100:
        return 1.0  # No benefit for small data

    # Use a sample to estimate
    sample_size = min(len(data), 4096)
    sample = data[:sample_size]

    try:
        _, was_compressed = compress(sample, algorithm, level, threshold=0)
        if not was_compressed:
            return 1.0

        if algorithm == CompressionAlgorithm.ZLIB:
            compressed = zlib.compress(sample, level)
        elif algorithm == CompressionAlgorithm.GZIP:
            compressed = gzip.compress(sample, compresslevel=level)
        elif algorithm == CompressionAlgorithm.LZ77:
            compressed = LZ77Compressor.compress(sample)
        else:
            return 1.0

        ratio = compression_ratio(len(sample), len(compressed))
        return ratio
    except Exception:
        return 1.0
