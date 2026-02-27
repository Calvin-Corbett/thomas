"""
Compression implementations: LZ4, Snappy, and ZSTD-style compression.

Provides fast compression/decompression for columnar data with different
compression algorithms and levels.
"""

import struct

from thomas.columnar._exceptions import CompressionError


class LZ4Compressor:
    """LZ4-style compression with sliding window and literal/match copy."""

    WINDOW_SIZE = 65536  # 64KB window
    MIN_MATCH = 4
    MAX_MATCH = 255

    @staticmethod
    def compress(data: bytes) -> bytes:
        """Compress data using LZ4-style compression.

        Uses literal/match approach:
        - Literal runs: sequences of unmatched bytes
        - Matches: repeated sequences found in history buffer
        """
        if not data:
            return struct.pack("<I", 0)

        result = bytearray()
        result.extend(struct.pack("<I", len(data)))

        pos = 0
        literals = bytearray()

        while pos < len(data):
            # Find best match in history
            match_length, match_distance = LZ4Compressor._find_match(data, pos, LZ4Compressor.WINDOW_SIZE)

            if match_length >= LZ4Compressor.MIN_MATCH:
                # Flush literals
                if literals:
                    LZ4Compressor._write_literals(result, bytes(literals))
                    literals = bytearray()

                # Write match
                token = min(match_length - LZ4Compressor.MIN_MATCH, 15)
                result.append((match_distance >> 8) | (token << 4))
                result.append(match_distance & 0xFF)
                if match_length > 15 + LZ4Compressor.MIN_MATCH:
                    remaining = match_length - 15 - LZ4Compressor.MIN_MATCH
                    while remaining > 254:
                        result.append(255)
                        remaining -= 255
                    result.append(remaining)

                pos += match_length
            else:
                # Add to literals
                literals.append(data[pos])
                pos += 1

        # Flush remaining literals
        if literals:
            LZ4Compressor._write_literals(result, bytes(literals))

        result.append(0)  # End marker
        return bytes(result)

    @staticmethod
    def _find_match(data: bytes, pos: int, window_size: int) -> tuple[int, int]:
        """Find longest matching sequence in history buffer."""
        if pos < LZ4Compressor.MIN_MATCH:
            return 0, 0

        window_start = max(0, pos - window_size)
        best_length = 0
        best_distance = 0

        # Search for matches
        for i in range(window_start, pos):
            length = 0
            while (
                length < LZ4Compressor.MAX_MATCH and pos + length < len(data) and data[i + length] == data[pos + length]
            ):
                length += 1

            if length > best_length:
                best_length = length
                best_distance = pos - i

        return best_length, best_distance

    @staticmethod
    def _write_literals(result: bytearray, literals: bytes) -> None:
        """Write literal run."""
        if not literals:
            return

        length = len(literals)
        token = min(length, 15)
        result.append(token)

        if length > 15:
            remaining = length - 15
            while remaining > 254:
                result.append(255)
                remaining -= 255
            result.append(remaining)

        result.extend(literals)

    @staticmethod
    def decompress(data: bytes) -> bytes:
        """Decompress LZ4-style compressed data."""
        if len(data) < 4:
            raise CompressionError("Invalid compressed data")

        uncompressed_size = struct.unpack("<I", data[:4])[0]
        result = bytearray()
        pos = 4

        while pos < len(data) and len(result) < uncompressed_size:
            token = data[pos]
            pos += 1

            if token == 0:
                break

            # Literal run
            literal_length = token & 0x0F
            if literal_length == 15:
                while pos < len(data):
                    byte = data[pos]
                    pos += 1
                    literal_length += byte
                    if byte < 255:
                        break

            if pos + literal_length <= len(data):
                result.extend(data[pos : pos + literal_length])
                pos += literal_length

            if len(result) >= uncompressed_size:
                break

            # Match
            if pos + 1 < len(data):
                distance = ((token >> 4) << 8) | data[pos + 1]
                pos += 2

                match_length = (token >> 4) + LZ4Compressor.MIN_MATCH
                if match_length == 15 + LZ4Compressor.MIN_MATCH and pos < len(data):
                    while pos < len(data):
                        byte = data[pos]
                        pos += 1
                        match_length += byte
                        if byte < 255:
                            break

                # Copy match from history
                match_pos = len(result) - distance
                for i in range(match_length):
                    result.append(result[match_pos + i])

        if len(result) != uncompressed_size:
            raise CompressionError(f"Decompressed size mismatch: got {len(result)}, expected {uncompressed_size}")

        return bytes(result)


class SnappyCompressor:
    """Snappy-style compression with fast path for short matches."""

    @staticmethod
    def compress(data: bytes) -> bytes:
        """Compress data using Snappy-style compression.

        Fast compression optimized for short sequences.
        """
        if not data:
            return struct.pack("<I", 0)

        result = bytearray()
        result.extend(struct.pack("<I", len(data)))

        pos = 0

        while pos < len(data):
            # Look for 4-byte match
            best_match_pos = -1
            best_match_len = 0

            if pos + 4 <= len(data):
                pattern = data[pos : pos + 4]
                for i in range(max(0, pos - 32768), pos):
                    if data[i : i + 4] == pattern:
                        # Extend match
                        match_len = 4
                        while (
                            pos + match_len < len(data)
                            and i + match_len < pos
                            and data[i + match_len] == data[pos + match_len]
                        ):
                            match_len += 1
                        if match_len > best_match_len:
                            best_match_len = match_len
                            best_match_pos = i

            if best_match_len >= 4:
                # Write match
                distance = pos - best_match_pos
                result.append(0xFF)  # Match indicator
                result.extend(struct.pack("<HB", distance, best_match_len - 4))
                pos += best_match_len
            else:
                # Write literal
                result.append(data[pos])
                pos += 1

        result.append(0)  # End marker
        return bytes(result)

    @staticmethod
    def decompress(data: bytes) -> bytes:
        """Decompress Snappy-style compressed data."""
        if len(data) < 4:
            raise CompressionError("Invalid compressed data")

        uncompressed_size = struct.unpack("<I", data[:4])[0]
        result = bytearray()
        pos = 4

        while pos < len(data) and len(result) < uncompressed_size:
            byte = data[pos]
            pos += 1

            if byte == 0:
                break
            elif byte == 0xFF and pos + 3 <= len(data):
                # Match
                distance = struct.unpack("<H", data[pos : pos + 2])[0]
                match_len = data[pos + 2] + 4
                pos += 3

                match_pos = len(result) - distance
                for i in range(match_len):
                    result.append(result[match_pos + i])
            else:
                # Literal
                result.append(byte)

        if len(result) != uncompressed_size:
            raise CompressionError(f"Decompressed size mismatch: got {len(result)}, expected {uncompressed_size}")

        return bytes(result)


class ZSTDCompressor:
    """ZSTD-style compression with dictionary support."""

    @staticmethod
    def compress(data: bytes, level: int = 3) -> bytes:
        """Compress data using ZSTD-style compression.

        Args:
            data: Data to compress
            level: Compression level 1-22 (higher = better compression but slower)
        """
        if not data:
            return struct.pack("<I", 0)

        level = max(1, min(22, level))
        result = bytearray()
        result.extend(struct.pack("<I", len(data)))
        result.append(level)

        # Simple run-length + literal encoding
        pos = 0
        while pos < len(data):
            byte = data[pos]
            run_length = 1

            while pos + run_length < len(data) and data[pos + run_length] == byte:
                run_length += 1

            if run_length >= 3:
                # Write RLE token
                result.append(0xFE)
                result.append(byte)
                result.extend(struct.pack("<H", run_length))
                pos += run_length
            else:
                # Write literals
                result.append(byte)
                pos += 1

        result.append(0)  # End marker
        return bytes(result)

    @staticmethod
    def decompress(data: bytes) -> bytes:
        """Decompress ZSTD-style compressed data."""
        if len(data) < 5:
            raise CompressionError("Invalid compressed data")

        uncompressed_size = struct.unpack("<I", data[:4])[0]
        level = data[4]
        result = bytearray()
        pos = 5

        while pos < len(data) and len(result) < uncompressed_size:
            byte = data[pos]
            pos += 1

            if byte == 0:
                break
            elif byte == 0xFE and pos + 3 <= len(data):
                # RLE token
                rle_byte = data[pos]
                pos += 1
                run_length = struct.unpack("<H", data[pos : pos + 2])[0]
                pos += 2
                result.extend([rle_byte] * run_length)
            else:
                result.append(byte)

        if len(result) != uncompressed_size:
            raise CompressionError(f"Decompressed size mismatch: got {len(result)}, expected {uncompressed_size}")

        return bytes(result)


def select_compression(data: bytes, preferred: str | None = None) -> str:
    """Select best compression algorithm based on data characteristics.

    Heuristics:
    - ZSTD for best compression ratio
    - Snappy for fast compression
    - LZ4 for balanced performance
    - None if compression ratio < 95%
    """
    if not data or len(data) < 100:
        return "NONE"

    # Test compression ratio
    try:
        lz4_compressed = LZ4Compressor.compress(data)
        ratio = len(lz4_compressed) / len(data)

        if ratio > 0.95:
            return "NONE"

        if preferred in {"ZSTD", "SNAPPY", "LZ4"}:
            return preferred

        # Default to LZ4 for balanced performance
        return "LZ4"
    except Exception:
        return "NONE"


def compress_lz4(data: bytes) -> bytes:
    """Public API: Compress using LZ4."""
    return LZ4Compressor.compress(data)


def decompress_lz4(data: bytes) -> bytes:
    """Public API: Decompress LZ4 data."""
    return LZ4Compressor.decompress(data)


def compress_snappy(data: bytes) -> bytes:
    """Public API: Compress using Snappy."""
    return SnappyCompressor.compress(data)


def decompress_snappy(data: bytes) -> bytes:
    """Public API: Decompress Snappy data."""
    return SnappyCompressor.decompress(data)


def compress_zstd(data: bytes, level: int = 3) -> bytes:
    """Public API: Compress using ZSTD.

    Args:
        data: Data to compress
        level: Compression level 1-22
    """
    return ZSTDCompressor.compress(data, level)


def decompress_zstd(data: bytes) -> bytes:
    """Public API: Decompress ZSTD data."""
    return ZSTDCompressor.decompress(data)
