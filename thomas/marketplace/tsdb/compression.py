"""Time-series compression algorithms for the Thomas TSDB.

Implements delta-of-delta encoding for timestamps, XOR-based compression
for floating-point values (Gorilla-style), and various optimizations.
"""

import struct


class DeltaOfDeltaEncoder:
    """Encodes timestamps using delta-of-delta encoding.

    This technique first computes deltas (differences between consecutive
    timestamps), then encodes the deltas of deltas, which tend to be small
    and compress well.
    """

    @staticmethod
    def encode(timestamps: list[int]) -> bytes:
        """Encode timestamps using delta-of-delta compression.

        Args:
            timestamps: List of timestamps in milliseconds

        Returns:
            Compressed byte string

        Raises:
            ValueError: If timestamps list is empty
        """
        if not timestamps:
            raise ValueError("Cannot encode empty timestamp list")

        result = bytearray()

        # Store first timestamp as reference (8 bytes, big-endian)
        result.extend(struct.pack(">Q", timestamps[0]))

        if len(timestamps) == 1:
            return bytes(result)

        # Store second timestamp delta (4 bytes, big-endian)
        first_delta = timestamps[1] - timestamps[0]
        result.extend(struct.pack(">i", first_delta))

        if len(timestamps) == 2:
            return bytes(result)

        # Encode delta-of-deltas starting from third timestamp
        bit_buffer = BitBuffer()
        for i in range(2, len(timestamps)):
            delta = timestamps[i] - timestamps[i - 1]
            prev_delta = timestamps[i - 1] - timestamps[i - 2]
            delta_of_delta = delta - prev_delta

            # Store delta-of-delta with variable-length encoding
            DeltaOfDeltaEncoder._encode_varint(bit_buffer, delta_of_delta)

        result.extend(bit_buffer.get_bytes())
        return bytes(result)

    @staticmethod
    def decode(data: bytes) -> list[int]:
        """Decode delta-of-delta encoded timestamps.

        Args:
            data: Compressed byte string

        Returns:
            List of decoded timestamps

        Raises:
            ValueError: If data is invalid
        """
        if len(data) < 8:
            raise ValueError("Invalid compressed data: too short")

        result: list[int] = []
        offset = 0

        # Read first timestamp
        first_ts = struct.unpack(">Q", data[offset : offset + 8])[0]
        result.append(first_ts)
        offset += 8

        if len(data) == 8:
            return result

        # Read second timestamp delta
        if len(data) < offset + 4:
            raise ValueError("Invalid compressed data: missing second delta")

        first_delta = struct.unpack(">i", data[offset : offset + 4])[0]
        result.append(first_ts + first_delta)
        offset += 4

        if len(data) == offset:
            return result

        # Decode remaining delta-of-deltas
        bit_buffer = BitBuffer.from_bytes(data[offset:])
        prev_delta = first_delta

        while bit_buffer.has_data():
            delta_of_delta = DeltaOfDeltaEncoder._decode_varint(bit_buffer)
            if delta_of_delta is None:
                break
            delta = prev_delta + delta_of_delta
            result.append(result[-1] + delta)
            prev_delta = delta

        return result

    @staticmethod
    def _encode_varint(buffer: "BitBuffer", value: int) -> None:
        """Encode a signed integer using variable-length encoding."""
        # Convert to unsigned using zigzag encoding
        unsigned = (value << 1) ^ (value >> 31)

        # Encode as variable-length
        while unsigned >= 128:
            buffer.write_bits((unsigned & 0x7F) | 0x80, 8)
            unsigned >>= 7
        buffer.write_bits(unsigned & 0x7F, 8)

    @staticmethod
    def _decode_varint(buffer: "BitBuffer") -> int | None:
        """Decode a variable-length encoded signed integer."""
        result = 0
        shift = 0

        while True:
            byte = buffer.read_bits(8)
            if byte is None:
                return None
            result |= (byte & 0x7F) << shift
            if byte < 128:
                break
            shift += 7

        # Decode from zigzag encoding
        return (result >> 1) ^ -(result & 1)


class XORFloatCompressor:
    """Compresses floating-point values using XOR-based compression.

    Based on the Facebook Gorilla paper's compression technique, which
    takes advantage of the bit patterns in IEEE 754 doubles.
    """

    @staticmethod
    def encode(values: list[float]) -> bytes:
        """Encode floating-point values using XOR compression.

        Args:
            values: List of float values

        Returns:
            Compressed byte string

        Raises:
            ValueError: If values list is empty
        """
        if not values:
            raise ValueError("Cannot encode empty value list")

        result = bytearray()
        bit_buffer = BitBuffer()

        # Store first value as reference (8 bytes)
        first_bits = struct.unpack(">Q", struct.pack(">d", values[0]))[0]
        result.extend(struct.pack(">Q", first_bits))

        if len(values) == 1:
            return bytes(result)

        # Encode subsequent values using XOR
        prev_bits = first_bits
        prev_leading_zero_count = 0
        prev_trailing_zero_count = 0

        for i in range(1, len(values)):
            curr_bits = struct.unpack(">Q", struct.pack(">d", values[i]))[0]
            xor_bits = prev_bits ^ curr_bits

            if xor_bits == 0:
                # Value is identical to previous
                bit_buffer.write_bits(0, 1)
            else:
                bit_buffer.write_bits(1, 1)

                # Count leading and trailing zeros in XOR result
                leading_zeros = XORFloatCompressor._count_leading_zeros(xor_bits)
                trailing_zeros = XORFloatCompressor._count_trailing_zeros(xor_bits)

                # Check if we can reuse previous zero counts
                if leading_zeros >= prev_leading_zero_count and trailing_zeros >= prev_trailing_zero_count:
                    # Reuse previous zero counts
                    bit_buffer.write_bits(1, 1)
                    significant_bits = 64 - prev_leading_zero_count - prev_trailing_zero_count
                    bit_buffer.write_bits(xor_bits >> prev_trailing_zero_count, significant_bits)
                else:
                    # New zero count pattern
                    bit_buffer.write_bits(0, 1)
                    bit_buffer.write_bits(leading_zeros, 6)
                    significant_bits = 64 - leading_zeros - trailing_zeros
                    bit_buffer.write_bits(significant_bits - 1, 6)
                    bit_buffer.write_bits(xor_bits >> trailing_zeros, significant_bits)

                    prev_leading_zero_count = leading_zeros
                    prev_trailing_zero_count = trailing_zeros

            prev_bits = curr_bits

        result.extend(bit_buffer.get_bytes())
        return bytes(result)

    @staticmethod
    def decode(data: bytes) -> list[float]:
        """Decode XOR-compressed floating-point values.

        Args:
            data: Compressed byte string

        Returns:
            List of decoded float values

        Raises:
            ValueError: If data is invalid
        """
        if len(data) < 8:
            raise ValueError("Invalid compressed data: too short")

        result: list[float] = []

        # Read first value
        first_bits = struct.unpack(">Q", data[0:8])[0]
        first_value = struct.unpack(">d", struct.pack(">Q", first_bits))[0]
        result.append(first_value)

        if len(data) == 8:
            return result

        # Decode subsequent values
        bit_buffer = BitBuffer.from_bytes(data[8:])
        prev_bits = first_bits
        prev_leading_zero_count = 0
        prev_trailing_zero_count = 0

        while bit_buffer.has_data():
            has_xor = bit_buffer.read_bits(1)
            if has_xor is None:
                break

            if has_xor == 0:
                # Same as previous
                curr_bits = prev_bits
            else:
                # Different value
                reuse_zeros = bit_buffer.read_bits(1)
                if reuse_zeros is None:
                    break

                if reuse_zeros == 1:
                    # Reuse previous zero counts
                    significant_bits = 64 - prev_leading_zero_count - prev_trailing_zero_count
                    xor_value = bit_buffer.read_bits(significant_bits)
                    if xor_value is None:
                        break
                    xor_bits = xor_value << prev_trailing_zero_count
                else:
                    # Read new zero counts
                    leading_zeros_bits = bit_buffer.read_bits(6)
                    significant_bits_minus1 = bit_buffer.read_bits(6)
                    if leading_zeros_bits is None or significant_bits_minus1 is None:
                        break

                    significant_bits = significant_bits_minus1 + 1
                    trailing_zeros = 64 - leading_zeros_bits - significant_bits
                    xor_value = bit_buffer.read_bits(significant_bits)
                    if xor_value is None:
                        break

                    xor_bits = xor_value << trailing_zeros
                    prev_leading_zero_count = leading_zeros_bits
                    prev_trailing_zero_count = trailing_zeros

                curr_bits = prev_bits ^ xor_bits

            prev_bits = curr_bits
            curr_value = struct.unpack(">d", struct.pack(">Q", curr_bits))[0]
            result.append(curr_value)

        return result

    @staticmethod
    def _count_leading_zeros(value: int) -> int:
        """Count leading zero bits in a 64-bit integer."""
        if value == 0:
            return 64
        return 63 - value.bit_length() + 1

    @staticmethod
    def _count_trailing_zeros(value: int) -> int:
        """Count trailing zero bits in a 64-bit integer."""
        if value == 0:
            return 64
        return (value & -value).bit_length() - 1


class RunLengthEncoder:
    """Encodes repeated values using run-length encoding."""

    @staticmethod
    def encode(values: list[float]) -> bytes:
        """Encode values using run-length encoding.

        Args:
            values: List of float values

        Returns:
            Compressed byte string
        """
        if not values:
            raise ValueError("Cannot encode empty value list")

        result = bytearray()
        i = 0

        while i < len(values):
            current_value = values[i]
            run_length = 1

            # Count consecutive identical values
            while i + run_length < len(values) and values[i + run_length] == current_value:
                run_length += 1

            # Store value and run length
            value_bits = struct.pack(">d", current_value)
            result.extend(value_bits)
            result.extend(struct.pack(">H", min(run_length, 65535)))

            i += run_length

        return bytes(result)

    @staticmethod
    def decode(data: bytes) -> list[float]:
        """Decode run-length encoded values.

        Args:
            data: Compressed byte string

        Returns:
            List of decoded float values

        Raises:
            ValueError: If data is invalid
        """
        if len(data) % 10 != 0:
            raise ValueError("Invalid compressed data: incorrect size")

        result: list[float] = []
        offset = 0

        while offset < len(data):
            value = struct.unpack(">d", data[offset : offset + 8])[0]
            run_length = struct.unpack(">H", data[offset + 8 : offset + 10])[0]
            result.extend([value] * run_length)
            offset += 10

        return result


class BitBuffer:
    """Helper class for bit-level read/write operations."""

    def __init__(self) -> None:
        """Initialize an empty bit buffer."""
        self.data = bytearray()
        self.bit_position = 0

    def write_bits(self, value: int, num_bits: int) -> None:
        """Write bits to the buffer.

        Args:
            value: Integer value containing the bits
            num_bits: Number of bits to write (1-64)
        """
        for i in range(num_bits - 1, -1, -1):
            bit = (value >> i) & 1
            byte_index = self.bit_position // 8
            bit_index = 7 - (self.bit_position % 8)

            if byte_index >= len(self.data):
                self.data.append(0)

            if bit:
                self.data[byte_index] |= 1 << bit_index
            else:
                self.data[byte_index] &= ~(1 << bit_index)

            self.bit_position += 1

    def read_bits(self, num_bits: int) -> int | None:
        """Read bits from the buffer.

        Args:
            num_bits: Number of bits to read

        Returns:
            Integer value or None if not enough data
        """
        if self.bit_position + num_bits > len(self.data) * 8:
            return None

        result = 0
        for _ in range(num_bits):
            byte_index = self.bit_position // 8
            bit_index = 7 - (self.bit_position % 8)
            bit = (self.data[byte_index] >> bit_index) & 1
            result = (result << 1) | bit
            self.bit_position += 1

        return result

    def get_bytes(self) -> bytes:
        """Get the underlying byte data."""
        return bytes(self.data)

    @staticmethod
    def from_bytes(data: bytes) -> "BitBuffer":
        """Create a BitBuffer from bytes for reading.

        Args:
            data: Byte data to read from

        Returns:
            BitBuffer instance ready for reading
        """
        buffer = BitBuffer()
        buffer.data = bytearray(data)
        return buffer

    def has_data(self) -> bool:
        """Check if there's more data to read."""
        return self.bit_position < len(self.data) * 8


class CompressionStats:
    """Statistics about compression performance."""

    def __init__(
        self,
        original_size: int,
        compressed_size: int,
        algorithm: str,
    ) -> None:
        """Initialize compression statistics.

        Args:
            original_size: Original size in bytes
            compressed_size: Compressed size in bytes
            algorithm: Name of compression algorithm used
        """
        self.original_size = original_size
        self.compressed_size = compressed_size
        self.algorithm = algorithm

    @property
    def compression_ratio(self) -> float:
        """Get compression ratio (compressed/original)."""
        if self.original_size == 0:
            return 1.0
        return self.compressed_size / self.original_size

    @property
    def space_saved_percent(self) -> float:
        """Get percentage of space saved."""
        if self.original_size == 0:
            return 0.0
        return (1.0 - self.compression_ratio) * 100

    def __str__(self) -> str:
        """Return string representation."""
        return (
            f"CompressionStats(algorithm={self.algorithm}, "
            f"ratio={self.compression_ratio:.3f}, "
            f"saved={self.space_saved_percent:.1f}%)"
        )
