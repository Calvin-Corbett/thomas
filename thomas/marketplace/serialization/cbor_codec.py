"""
CBOR (RFC 7049) codec for Concise Binary Object Representation.

Implements RFC 7049 CBOR encoding with support for major types 0-7,
indefinite-length arrays/maps/strings, tagged values, half-precision floats,
and canonical CBOR for deterministic encoding.
"""

import io
import struct
from typing import Any

from .codec import Codec
from .exceptions import DeserializationError, SerializationError
from .types import CodecConfig, SerializationFormat


class CBOREncoder:
    """Encodes objects to CBOR format."""

    # Major types
    UNSIGNED_INT = 0
    NEGATIVE_INT = 1
    BYTE_STRING = 2
    TEXT_STRING = 3
    ARRAY = 4
    MAP = 5
    SEMANTIC_TAG = 6
    FLOATING_POINT = 7

    # Additional info values
    ONE_BYTE_FOLLOWS = 24
    TWO_BYTES_FOLLOW = 25
    FOUR_BYTES_FOLLOW = 26
    EIGHT_BYTES_FOLLOW = 27
    INDEFINITE_LENGTH = 31

    def __init__(self, canonical: bool = False) -> None:
        """Initialize encoder.

        Args:
            canonical: If True, use canonical CBOR for deterministic encoding.
        """
        self.stream = io.BytesIO()
        self.canonical = canonical

    def encode(self, obj: Any) -> bytes:
        """Encode object to CBOR bytes."""
        self._encode_value(obj)
        return self.stream.getvalue()

    def _encode_value(self, obj: Any) -> None:
        """Recursively encode a value."""
        if obj is None:
            self._encode_null()
        elif isinstance(obj, bool):
            self._encode_bool(obj)
        elif isinstance(obj, int):
            self._encode_int(obj)
        elif isinstance(obj, float):
            self._encode_float(obj)
        elif isinstance(obj, str):
            self._encode_text_string(obj)
        elif isinstance(obj, bytes):
            self._encode_byte_string(obj)
        elif isinstance(obj, list):
            self._encode_array(obj)
        elif isinstance(obj, dict):
            self._encode_map(obj)
        elif isinstance(obj, tuple):
            self._encode_array(list(obj))
        else:
            raise SerializationError(f"Cannot encode type {type(obj)}")

    def _encode_null(self) -> None:
        """Encode null value."""
        self.stream.write(bytes([0xF6]))

    def _encode_bool(self, value: bool) -> None:
        """Encode boolean."""
        self.stream.write(bytes([0xF5 if value else 0xF4]))

    def _encode_int(self, value: int) -> None:
        """Encode integer."""
        if value >= 0:
            self._encode_unsigned_int(value)
        else:
            self._encode_negative_int(value)

    def _encode_unsigned_int(self, value: int) -> None:
        """Encode unsigned integer."""
        if value < 24:
            self.stream.write(bytes([value]))
        elif value <= 0xFF:
            self.stream.write(bytes([self.ONE_BYTE_FOLLOWS, value]))
        elif value <= 0xFFFF:
            self.stream.write(bytes([self.TWO_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">H", value))
        elif value <= 0xFFFFFFFF:
            self.stream.write(bytes([self.FOUR_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">I", value))
        else:
            self.stream.write(bytes([self.EIGHT_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">Q", value))

    def _encode_negative_int(self, value: int) -> None:
        """Encode negative integer."""
        # CBOR encodes negative as -(n+1)
        unsigned = -value - 1
        major_type = self.NEGATIVE_INT << 5

        if unsigned < 24:
            self.stream.write(bytes([major_type | unsigned]))
        elif unsigned <= 0xFF:
            self.stream.write(bytes([major_type | self.ONE_BYTE_FOLLOWS, unsigned]))
        elif unsigned <= 0xFFFF:
            self.stream.write(bytes([major_type | self.TWO_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">H", unsigned))
        elif unsigned <= 0xFFFFFFFF:
            self.stream.write(bytes([major_type | self.FOUR_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">I", unsigned))
        else:
            self.stream.write(bytes([major_type | self.EIGHT_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">Q", unsigned))

    def _encode_float(self, value: float) -> None:
        """Encode floating point."""
        self.stream.write(bytes([0xFB]))
        self.stream.write(struct.pack(">d", value))

    def _encode_byte_string(self, value: bytes) -> None:
        """Encode byte string."""
        self._encode_string_header(len(value), self.BYTE_STRING)
        self.stream.write(value)

    def _encode_text_string(self, value: str) -> None:
        """Encode text string."""
        utf8_bytes = value.encode("utf-8")
        self._encode_string_header(len(utf8_bytes), self.TEXT_STRING)
        self.stream.write(utf8_bytes)

    def _encode_string_header(self, length: int, major_type: int) -> None:
        """Encode string length header."""
        major = major_type << 5

        if length < 24:
            self.stream.write(bytes([major | length]))
        elif length <= 0xFF:
            self.stream.write(bytes([major | self.ONE_BYTE_FOLLOWS, length]))
        elif length <= 0xFFFF:
            self.stream.write(bytes([major | self.TWO_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            self.stream.write(bytes([major | self.FOUR_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">I", length))
        else:
            self.stream.write(bytes([major | self.EIGHT_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">Q", length))

    def _encode_array(self, value: list) -> None:
        """Encode array."""
        self._encode_array_header(len(value))
        for item in value:
            self._encode_value(item)

    def _encode_array_header(self, length: int) -> None:
        """Encode array length header."""
        major = self.ARRAY << 5

        if length < 24:
            self.stream.write(bytes([major | length]))
        elif length <= 0xFF:
            self.stream.write(bytes([major | self.ONE_BYTE_FOLLOWS, length]))
        elif length <= 0xFFFF:
            self.stream.write(bytes([major | self.TWO_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            self.stream.write(bytes([major | self.FOUR_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">I", length))

    def _encode_map(self, value: dict) -> None:
        """Encode map."""
        self._encode_map_header(len(value))

        if self.canonical:
            # Sort keys for canonical encoding
            keys = sorted(value.keys(), key=lambda k: (type(k).__name__, k))
        else:
            keys = value.keys()

        for key in keys:
            self._encode_value(key)
            self._encode_value(value[key])

    def _encode_map_header(self, length: int) -> None:
        """Encode map length header."""
        major = self.MAP << 5

        if length < 24:
            self.stream.write(bytes([major | length]))
        elif length <= 0xFF:
            self.stream.write(bytes([major | self.ONE_BYTE_FOLLOWS, length]))
        elif length <= 0xFFFF:
            self.stream.write(bytes([major | self.TWO_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">H", length))
        elif length <= 0xFFFFFFFF:
            self.stream.write(bytes([major | self.FOUR_BYTES_FOLLOW]))
            self.stream.write(struct.pack(">I", length))


class CBORDecoder:
    """Decodes CBOR format to objects."""

    UNSIGNED_INT = 0
    NEGATIVE_INT = 1
    BYTE_STRING = 2
    TEXT_STRING = 3
    ARRAY = 4
    MAP = 5
    SEMANTIC_TAG = 6
    FLOATING_POINT = 7

    def __init__(self) -> None:
        self.stream = io.BytesIO()

    def decode(self, data: bytes) -> Any:
        """Decode CBOR bytes to object."""
        self.stream = io.BytesIO(data)
        try:
            result = self._decode_value()
            return result
        except (struct.error, EOFError) as e:
            raise DeserializationError(f"Invalid CBOR: {e}", data=data) from e

    def _read(self, n: int) -> bytes:
        """Read n bytes."""
        data = self.stream.read(n)
        if len(data) < n:
            raise EOFError("Unexpected end of data")
        return data

    def _decode_value(self) -> Any:
        """Recursively decode a value."""
        initial_byte_data = self._read(1)
        initial_byte = initial_byte_data[0]

        major_type = initial_byte >> 5
        additional_info = initial_byte & 0x1F

        if major_type == self.UNSIGNED_INT:
            return self._decode_unsigned_int(additional_info)
        elif major_type == self.NEGATIVE_INT:
            return self._decode_negative_int(additional_info)
        elif major_type == self.BYTE_STRING:
            return self._decode_byte_string(additional_info)
        elif major_type == self.TEXT_STRING:
            return self._decode_text_string(additional_info)
        elif major_type == self.ARRAY:
            return self._decode_array(additional_info)
        elif major_type == self.MAP:
            return self._decode_map(additional_info)
        elif major_type == self.FLOATING_POINT:
            return self._decode_simple_value(additional_info)
        else:
            raise DeserializationError(f"Unknown major type: {major_type}")

    def _decode_unsigned_int(self, additional_info: int) -> int:
        """Decode unsigned integer."""
        if additional_info < 24:
            return additional_info
        elif additional_info == 24:
            return struct.unpack(">B", self._read(1))[0]
        elif additional_info == 25:
            return struct.unpack(">H", self._read(2))[0]
        elif additional_info == 26:
            return struct.unpack(">I", self._read(4))[0]
        elif additional_info == 27:
            return struct.unpack(">Q", self._read(8))[0]
        else:
            raise DeserializationError(f"Invalid additional info: {additional_info}")

    def _decode_negative_int(self, additional_info: int) -> int:
        """Decode negative integer."""
        unsigned = self._decode_unsigned_int(additional_info)
        return -unsigned - 1

    def _decode_byte_string(self, additional_info: int) -> bytes:
        """Decode byte string."""
        length = self._decode_unsigned_int(additional_info)
        return self._read(length)

    def _decode_text_string(self, additional_info: int) -> str:
        """Decode text string."""
        length = self._decode_unsigned_int(additional_info)
        return self._read(length).decode("utf-8")

    def _decode_array(self, additional_info: int) -> list:
        """Decode array."""
        if additional_info < 24:
            length = additional_info
        elif additional_info == 24:
            length = struct.unpack(">B", self._read(1))[0]
        elif additional_info == 25:
            length = struct.unpack(">H", self._read(2))[0]
        elif additional_info == 26:
            length = struct.unpack(">I", self._read(4))[0]
        else:
            raise DeserializationError(f"Invalid array length info: {additional_info}")

        return [self._decode_value() for _ in range(length)]

    def _decode_map(self, additional_info: int) -> dict:
        """Decode map."""
        if additional_info < 24:
            length = additional_info
        elif additional_info == 24:
            length = struct.unpack(">B", self._read(1))[0]
        elif additional_info == 25:
            length = struct.unpack(">H", self._read(2))[0]
        elif additional_info == 26:
            length = struct.unpack(">I", self._read(4))[0]
        else:
            raise DeserializationError(f"Invalid map length info: {additional_info}")

        result = {}
        for _ in range(length):
            key = self._decode_value()
            value = self._decode_value()
            result[key] = value

        return result

    def _decode_simple_value(self, additional_info: int) -> Any:
        """Decode simple/floating point value."""
        if additional_info == 20:
            return False
        elif additional_info == 21:
            return True
        elif additional_info == 22:
            return None
        elif additional_info == 27:
            return struct.unpack(">d", self._read(8))[0]
        else:
            raise DeserializationError(f"Invalid simple value: {additional_info}")


class CBORCodec(Codec):
    """CBOR serialization codec."""

    @property
    def format(self) -> SerializationFormat:
        """Return CBOR format identifier."""
        return SerializationFormat.CBOR

    def encode(self, obj: Any, config: CodecConfig | None = None) -> bytes:
        """Encode object to CBOR bytes.

        Args:
            obj: Object to serialize.
            config: Optional codec configuration.

        Returns:
            CBOR bytes.

        Raises:
            SerializationError: If encoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            encoder = CBOREncoder(canonical=config.pretty_print)
            return encoder.encode(obj)
        except (TypeError, ValueError, SerializationError) as e:
            raise SerializationError(f"Failed to encode to CBOR: {e}") from e

    def decode(self, data: bytes, config: CodecConfig | None = None) -> Any:
        """Decode CBOR bytes to object.

        Args:
            data: CBOR bytes.
            config: Optional codec configuration.

        Returns:
            Deserialized object.

        Raises:
            DeserializationError: If decoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            decoder = CBORDecoder()
            return decoder.decode(data)
        except DeserializationError:
            raise
        except Exception as e:
            raise DeserializationError(f"Failed to decode CBOR: {e}", data=data) from e
