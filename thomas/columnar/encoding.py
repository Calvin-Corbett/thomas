"""
Column encoding implementations: plain, dictionary, RLE, delta, and bit-packing.

Implements multiple encoding schemes used in columnar storage with automatic
selection based on data characteristics.
"""

import struct
from typing import Any

from thomas.columnar._types import (
    ColumnType,
)


class PlainEncoder:
    """Plain (unencoded) encoding for all column types."""

    @staticmethod
    def encode(values: list[Any], col_type: ColumnType) -> bytes:
        """Encode values using plain encoding (no compression)."""
        result = bytearray()

        for value in values:
            if value is None:
                continue

            if col_type == ColumnType.INT8:
                result.extend(struct.pack("b", value))
            elif col_type == ColumnType.INT16:
                result.extend(struct.pack("<h", value))
            elif col_type == ColumnType.INT32:
                result.extend(struct.pack("<i", value))
            elif col_type == ColumnType.INT64:
                result.extend(struct.pack("<q", value))
            elif col_type == ColumnType.UINT8:
                result.extend(struct.pack("B", value))
            elif col_type == ColumnType.UINT16:
                result.extend(struct.pack("<H", value))
            elif col_type == ColumnType.UINT32:
                result.extend(struct.pack("<I", value))
            elif col_type == ColumnType.UINT64:
                result.extend(struct.pack("<Q", value))
            elif col_type == ColumnType.FLOAT32:
                result.extend(struct.pack("<f", value))
            elif col_type == ColumnType.FLOAT64:
                result.extend(struct.pack("<d", value))
            elif col_type == ColumnType.BOOL:
                result.extend(b"\x01" if value else b"\x00")
            elif col_type == ColumnType.STRING:
                encoded = value.encode("utf-8")
                result.extend(struct.pack("<I", len(encoded)))
                result.extend(encoded)
            elif col_type == ColumnType.BINARY:
                result.extend(struct.pack("<I", len(value)))
                result.extend(value)
            elif col_type == ColumnType.DATE:
                days = (value - __import__("datetime").date(1970, 1, 1)).days
                result.extend(struct.pack("<i", days))
            elif col_type == ColumnType.TIMESTAMP:
                epoch = __import__("datetime").datetime(1970, 1, 1)
                micros = int((value - epoch).total_seconds() * 1_000_000)
                result.extend(struct.pack("<q", micros))

        return bytes(result)

    @staticmethod
    def decode(data: bytes, col_type: ColumnType, num_values: int, null_bitmap: bytes | None = None) -> list[Any]:
        """Decode plain-encoded values."""
        values = []
        offset = 0
        null_index = 0

        for i in range(num_values):
            # Check if value is null
            is_null = False
            if null_bitmap:
                byte_idx = null_index // 8
                bit_idx = null_index % 8
                is_null = (null_bitmap[byte_idx] >> bit_idx) & 1 == 0
                null_index += 1

            if is_null:
                values.append(None)
                continue

            if col_type == ColumnType.INT8:
                values.append(struct.unpack("b", data[offset : offset + 1])[0])
                offset += 1
            elif col_type == ColumnType.INT16:
                values.append(struct.unpack("<h", data[offset : offset + 2])[0])
                offset += 2
            elif col_type == ColumnType.INT32:
                values.append(struct.unpack("<i", data[offset : offset + 4])[0])
                offset += 4
            elif col_type == ColumnType.INT64:
                values.append(struct.unpack("<q", data[offset : offset + 8])[0])
                offset += 8
            elif col_type == ColumnType.UINT8:
                values.append(struct.unpack("B", data[offset : offset + 1])[0])
                offset += 1
            elif col_type == ColumnType.UINT16:
                values.append(struct.unpack("<H", data[offset : offset + 2])[0])
                offset += 2
            elif col_type == ColumnType.UINT32:
                values.append(struct.unpack("<I", data[offset : offset + 4])[0])
                offset += 4
            elif col_type == ColumnType.UINT64:
                values.append(struct.unpack("<Q", data[offset : offset + 8])[0])
                offset += 8
            elif col_type == ColumnType.FLOAT32:
                values.append(struct.unpack("<f", data[offset : offset + 4])[0])
                offset += 4
            elif col_type == ColumnType.FLOAT64:
                values.append(struct.unpack("<d", data[offset : offset + 8])[0])
                offset += 8
            elif col_type == ColumnType.BOOL:
                values.append(data[offset] != 0)
                offset += 1
            elif col_type == ColumnType.STRING:
                length = struct.unpack("<I", data[offset : offset + 4])[0]
                offset += 4
                values.append(data[offset : offset + length].decode("utf-8"))
                offset += length
            elif col_type == ColumnType.BINARY:
                length = struct.unpack("<I", data[offset : offset + 4])[0]
                offset += 4
                values.append(bytes(data[offset : offset + length]))
                offset += length
            elif col_type == ColumnType.DATE:
                days = struct.unpack("<i", data[offset : offset + 4])[0]
                offset += 4
                epoch = __import__("datetime").date(1970, 1, 1)
                values.append(epoch + __import__("datetime").timedelta(days=days))
            elif col_type == ColumnType.TIMESTAMP:
                micros = struct.unpack("<q", data[offset : offset + 8])[0]
                offset += 8
                epoch = __import__("datetime").datetime(1970, 1, 1)
                values.append(epoch + __import__("datetime").timedelta(microseconds=micros))

        return values


class DictionaryEncoder:
    """Dictionary encoding with sorted dictionary and integer indices."""

    @staticmethod
    def encode(values: list[Any], col_type: ColumnType) -> tuple[bytes, list[Any]]:
        """Encode values using dictionary encoding.

        Returns (encoded_data, dictionary) where encoded_data is indices
        and dictionary is sorted list of unique values.
        """
        # Build dictionary from non-null unique values
        unique = set(v for v in values if v is not None)
        dictionary = sorted(list(unique))

        # Create index map
        index_map = {v: i for i, v in enumerate(dictionary)}

        # Use compact integer width for indices.
        dict_size = len(dictionary)
        if dict_size <= 0xFF:
            index_size = 1
            null_sentinel = 0xFF
            pack_fmt = "B"
        elif dict_size <= 0xFFFF:
            index_size = 2
            null_sentinel = 0xFFFF
            pack_fmt = "<H"
        else:
            index_size = 4
            null_sentinel = -1
            pack_fmt = "<i"

        # Encode indices.
        result = bytearray()
        for value in values:
            if value is None:
                result.extend(struct.pack(pack_fmt, null_sentinel))
            else:
                idx = index_map[value]
                result.extend(struct.pack(pack_fmt, idx))

        return bytes(result), dictionary

    @staticmethod
    def decode(data: bytes, dictionary: list[Any], num_values: int) -> list[Any]:
        """Decode dictionary-encoded values."""
        values = []
        offset = 0

        if num_values == 0:
            return values

        index_size = len(data) // num_values if num_values else 0
        if index_size == 1:
            unpack_fmt = "B"
            null_sentinel = 0xFF
        elif index_size == 2:
            unpack_fmt = "<H"
            null_sentinel = 0xFFFF
        else:
            unpack_fmt = "<i"
            null_sentinel = -1
            index_size = 4

        for _ in range(num_values):
            idx = struct.unpack(unpack_fmt, data[offset : offset + index_size])[0]
            offset += index_size
            if idx == null_sentinel:
                values.append(None)
            else:
                values.append(dictionary[idx])

        return values


class RLEEncoder:
    """Run-Length Encoding (RLE) with bit-packing for small integers."""

    @staticmethod
    def encode(values: list[Any], col_type: ColumnType, bit_width: int = 8) -> bytes:
        """Encode values using RLE with optional bit-packing.

        For integers, uses bit-width compression. For other types,
        uses simple run-length encoding.
        """
        if not values:
            return b""

        result = bytearray()

        # Simple run-length encoding for all types.
        i = 0
        while i < len(values):
            run_value = values[i]
            run_length = 1

            while i + run_length < len(values) and values[i + run_length] == run_value:
                run_length += 1

            # Encode run: length (varint) + value
            result.extend(RLEEncoder._encode_varint(run_length))
            if run_value is not None:
                result.extend(PlainEncoder.encode([run_value], col_type))
            else:
                result.append(0xFF)

            i += run_length

        return bytes(result)

    @staticmethod
    def _encode_bitpacked(values: list[Any], bit_width: int) -> bytes:
        """Encode integers using bit-packing."""
        if bit_width <= 0 or bit_width > 32:
            bit_width = 32

        result = bytearray()
        result.extend(struct.pack("B", bit_width))

        # Collect non-null values
        non_null = [v for v in values if v is not None]
        if not non_null:
            return bytes(result)

        # Pack bits
        bit_buffer = 0
        bits_in_buffer = 0

        for value in non_null:
            bit_buffer = (bit_buffer << bit_width) | (value & ((1 << bit_width) - 1))
            bits_in_buffer += bit_width

            while bits_in_buffer >= 8:
                bits_in_buffer -= 8
                byte = (bit_buffer >> bits_in_buffer) & 0xFF
                result.append(byte)

        # Flush remaining bits
        if bits_in_buffer > 0:
            byte = (bit_buffer << (8 - bits_in_buffer)) & 0xFF
            result.append(byte)

        return bytes(result)

    @staticmethod
    def decode(data: bytes, col_type: ColumnType, num_values: int) -> list[Any]:
        """Decode RLE-encoded values."""
        if not data or num_values == 0:
            return []

        values = []
        offset = 0

        while len(values) < num_values and offset < len(data):
            # Decode run length
            run_length, length_bytes = RLEEncoder._decode_varint(data[offset:])
            offset += length_bytes

            # Decode run value
            if offset < len(data) and data[offset] == 0xFF:
                value = None
                offset += 1
            else:
                # Decode one value
                decoded = PlainEncoder.decode(data[offset:], col_type, 1)
                value = decoded[0] if decoded else None
                offset += col_type.byte_width() or 1

            # Add run to values
            for _ in range(run_length):
                values.append(value)

        return values[:num_values]

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        """Encode integer as varint (variable-length integer)."""
        result = bytearray()
        while value > 127:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    @staticmethod
    def _decode_varint(data: bytes) -> tuple[int, int]:
        """Decode varint from bytes, return (value, bytes_consumed)."""
        result = 0
        shift = 0
        i = 0

        while i < len(data):
            byte = data[i]
            result |= (byte & 0x7F) << shift
            i += 1
            if byte <= 127:
                break
            shift += 7

        return result, i


class DeltaEncoder:
    """Delta encoding for temporal and monotonic numeric data."""

    @staticmethod
    def encode(values: list[Any], col_type: ColumnType) -> bytes:
        """Encode values using delta encoding (stores differences between consecutive values)."""
        if not values or all(v is None for v in values):
            return b""

        result = bytearray()

        # Filter None values and compute deltas
        non_null = [v for v in values if v is not None]
        if not non_null:
            return b""

        # Store first value explicitly
        first = non_null[0]
        if col_type == ColumnType.TIMESTAMP:
            epoch = __import__("datetime").datetime(1970, 1, 1)
            micros = int((first - epoch).total_seconds() * 1_000_000)
            result.extend(struct.pack("<q", micros))
        elif col_type == ColumnType.DATE:
            days = (first - __import__("datetime").date(1970, 1, 1)).days
            result.extend(struct.pack("<i", days))
        elif col_type in {ColumnType.INT32, ColumnType.INT64}:
            result.extend(struct.pack("<q", first))
        else:
            result.extend(PlainEncoder.encode([first], col_type))

        # Encode deltas
        for i in range(1, len(non_null)):
            if col_type == ColumnType.TIMESTAMP:
                delta = int((non_null[i] - non_null[i - 1]).total_seconds() * 1_000_000)
            elif col_type == ColumnType.DATE:
                delta = (non_null[i] - non_null[i - 1]).days
            else:
                delta = int(non_null[i] - non_null[i - 1])

            # ZigZag encode signed deltas to unsigned varints.
            encoded_delta = delta * 2 if delta >= 0 else (-delta) * 2 - 1
            result.extend(RLEEncoder._encode_varint(encoded_delta))

        return bytes(result)

    @staticmethod
    def decode(data: bytes, col_type: ColumnType, num_values: int) -> list[Any]:
        """Decode delta-encoded values."""
        if not data:
            return []

        values = []
        offset = 0

        # Decode first value
        if col_type == ColumnType.TIMESTAMP:
            micros = struct.unpack("<q", data[offset : offset + 8])[0]
            offset += 8
            epoch = __import__("datetime").datetime(1970, 1, 1)
            current = epoch + __import__("datetime").timedelta(microseconds=micros)
        elif col_type == ColumnType.DATE:
            days = struct.unpack("<i", data[offset : offset + 4])[0]
            offset += 4
            epoch = __import__("datetime").date(1970, 1, 1)
            current = epoch + __import__("datetime").timedelta(days=days)
        elif col_type in {ColumnType.INT32, ColumnType.INT64}:
            current = struct.unpack("<q", data[offset : offset + 8])[0]
            offset += 8
        else:
            decoded = PlainEncoder.decode(data[offset:], col_type, 1)
            current = decoded[0] if decoded else 0
            offset += col_type.byte_width() or 1

        values.append(current)

        # Decode deltas
        while len(values) < num_values and offset < len(data):
            encoded_delta, bytes_read = RLEEncoder._decode_varint(data[offset:])
            offset += bytes_read

            # ZigZag decode unsigned varint back to signed delta.
            if encoded_delta & 1:
                delta = -((encoded_delta + 1) // 2)
            else:
                delta = encoded_delta // 2

            if col_type in {ColumnType.TIMESTAMP, ColumnType.DATE}:
                if col_type == ColumnType.TIMESTAMP:
                    current = current + __import__("datetime").timedelta(microseconds=delta)
                else:
                    current = current + __import__("datetime").timedelta(days=delta)
            else:
                current = current + delta

            values.append(current)

        return values[:num_values]


def select_encoding(values: list[Any], col_type: ColumnType) -> str:
    """Select best encoding based on data characteristics.

    Heuristics:
    - Dictionary encoding if cardinality < 10% of values
    - Delta encoding for sorted temporal data
    - RLE for data with many repeated values
    - Plain encoding as fallback
    """
    if not values:
        return "PLAIN"

    non_null = [v for v in values if v is not None]
    if not non_null:
        return "PLAIN"

    cardinality = len(set(non_null))
    cardinality_ratio = cardinality / len(non_null)

    # Dictionary encoding for low cardinality
    if cardinality_ratio < 0.1 and cardinality > 0:
        return "dictionary"

    # RLE for high repetition
    if cardinality_ratio < 0.5:
        return "RLE"

    # Delta encoding for temporal data
    if col_type.is_temporal():
        return "DELTA"

    # Bit packing for small integers
    if col_type in {ColumnType.INT8, ColumnType.UINT8}:
        return "BIT_PACKED"

    return "PLAIN"


def encode_plain(values: list[Any], col_type: ColumnType) -> bytes:
    """Public API: Encode values using plain encoding."""
    return PlainEncoder.encode(values, col_type)


def decode_plain(data: bytes, col_type: ColumnType, num_values: int, null_bitmap: bytes | None = None) -> list[Any]:
    """Public API: Decode plain-encoded values."""
    return PlainEncoder.decode(data, col_type, num_values, null_bitmap)


def encode_dictionary(values: list[Any], col_type: ColumnType) -> tuple[bytes, list[Any]]:
    """Public API: Encode values using dictionary encoding."""
    return DictionaryEncoder.encode(values, col_type)


def decode_dictionary(data: bytes, dictionary: list[Any], num_values: int) -> list[Any]:
    """Public API: Decode dictionary-encoded values."""
    return DictionaryEncoder.decode(data, dictionary, num_values)


def encode_rle(values: list[Any], col_type: ColumnType, bit_width: int = 8) -> bytes:
    """Public API: Encode values using RLE."""
    return RLEEncoder.encode(values, col_type, bit_width)


def decode_rle(data: bytes, col_type: ColumnType, num_values: int) -> list[Any]:
    """Public API: Decode RLE-encoded values."""
    return RLEEncoder.decode(data, col_type, num_values)


def encode_delta(values: list[Any], col_type: ColumnType) -> bytes:
    """Public API: Encode values using delta encoding."""
    return DeltaEncoder.encode(values, col_type)


def decode_delta(data: bytes, col_type: ColumnType, num_values: int) -> list[Any]:
    """Public API: Decode delta-encoded values."""
    return DeltaEncoder.decode(data, col_type, num_values)
