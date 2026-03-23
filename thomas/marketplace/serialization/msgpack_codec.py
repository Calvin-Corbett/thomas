"""
MessagePack-compatible binary codec.

Implements efficient binary serialization compatible with the MessagePack
specification. Includes custom type extensions for datetime, UUID, Decimal,
bytes, and other special types.
"""

import struct
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from io import BytesIO
from typing import Any

from .codec import Codec
from .exceptions import DeserializationError, SerializationError
from .types import CodecConfig, SerializationFormat


class MessagePackEncoder:
    """Encodes objects to MessagePack binary format."""

    # MessagePack type codes
    POSITIVE_FIXINT_MAX = 0x7F
    FIXMAP_MAX = 15
    FIXARRAY_MAX = 15
    FIXSTR_MAX = 31

    def __init__(self, allow_nan: bool = False) -> None:
        self.allow_nan = allow_nan
        self.stream = BytesIO()

    def encode(self, obj: Any) -> bytes:
        """Encode object to MessagePack bytes."""
        self._encode_value(obj)
        return self.stream.getvalue()

    def _encode_value(self, obj: Any) -> None:
        """Recursively encode a value."""
        if obj is None:
            self.stream.write(b"\xc0")  # nil
        elif isinstance(obj, bool):
            self.stream.write(b"\xc3" if obj else b"\xc2")  # true/false
        elif isinstance(obj, int):
            self._encode_int(obj)
        elif isinstance(obj, float):
            self._encode_float(obj)
        elif isinstance(obj, str):
            self._encode_str(obj)
        elif isinstance(obj, bytes):
            self._encode_bin(obj)
        elif isinstance(obj, (list, tuple)):
            self._encode_array(obj)
        elif isinstance(obj, dict):
            self._encode_map(obj)
        elif isinstance(obj, Decimal):
            self._encode_decimal(obj)
        elif isinstance(obj, uuid.UUID):
            self._encode_uuid(obj)
        elif isinstance(obj, datetime):
            self._encode_datetime(obj)
        elif isinstance(obj, date):
            self._encode_date(obj)
        elif isinstance(obj, time):
            self._encode_time(obj)
        elif isinstance(obj, Enum):
            self._encode_enum(obj)
        else:
            raise SerializationError(f"Cannot encode type {type(obj)}")

    def _encode_int(self, value: int) -> None:
        """Encode integer."""
        if 0 <= value <= self.POSITIVE_FIXINT_MAX:
            self.stream.write(bytes([value]))
        elif -32 <= value < 0:
            self.stream.write(struct.pack("b", value))
        elif 0 <= value <= 0xFF:
            self.stream.write(b"\xcc" + struct.pack(">B", value))
        elif -128 <= value <= 127:
            self.stream.write(b"\xd0" + struct.pack(">b", value))
        elif 0 <= value <= 0xFFFF:
            self.stream.write(b"\xcd" + struct.pack(">H", value))
        elif -32768 <= value <= 32767:
            self.stream.write(b"\xd1" + struct.pack(">h", value))
        elif 0 <= value <= 0xFFFFFFFF:
            self.stream.write(b"\xce" + struct.pack(">I", value))
        elif -2147483648 <= value <= 2147483647:
            self.stream.write(b"\xd2" + struct.pack(">i", value))
        else:
            self.stream.write(b"\xcf" + struct.pack(">Q", value))

    def _encode_float(self, value: float) -> None:
        """Encode floating point."""
        if not self.allow_nan and (value != value or value == float("inf") or value == float("-inf")):
            raise SerializationError(f"Cannot encode NaN or Infinity: {value}")
        self.stream.write(b"\xcb" + struct.pack(">d", value))

    def _encode_str(self, value: str) -> None:
        """Encode string."""
        data = value.encode("utf-8")
        length = len(data)

        if length <= self.FIXSTR_MAX:
            self.stream.write(bytes([0xA0 | length]))
        elif length <= 0xFF:
            self.stream.write(b"\xd9" + struct.pack(">B", length))
        elif length <= 0xFFFF:
            self.stream.write(b"\xda" + struct.pack(">H", length))
        else:
            self.stream.write(b"\xdb" + struct.pack(">I", length))

        self.stream.write(data)

    def _encode_bin(self, value: bytes) -> None:
        """Encode binary data."""
        length = len(value)

        if length <= 0xFF:
            self.stream.write(b"\xc4" + struct.pack(">B", length))
        elif length <= 0xFFFF:
            self.stream.write(b"\xc5" + struct.pack(">H", length))
        else:
            self.stream.write(b"\xc6" + struct.pack(">I", length))

        self.stream.write(value)

    def _encode_array(self, value: list | tuple) -> None:
        """Encode array."""
        length = len(value)

        if length <= self.FIXARRAY_MAX:
            self.stream.write(bytes([0x90 | length]))
        elif length <= 0xFFFF:
            self.stream.write(b"\xdc" + struct.pack(">H", length))
        else:
            self.stream.write(b"\xdd" + struct.pack(">I", length))

        for item in value:
            self._encode_value(item)

    def _encode_map(self, value: dict) -> None:
        """Encode dictionary as map."""
        length = len(value)

        if length <= self.FIXMAP_MAX:
            self.stream.write(bytes([0x80 | length]))
        elif length <= 0xFFFF:
            self.stream.write(b"\xde" + struct.pack(">H", length))
        else:
            self.stream.write(b"\xdf" + struct.pack(">I", length))

        for k, v in value.items():
            self._encode_str(str(k))
            self._encode_value(v)

    def _encode_decimal(self, value: Decimal) -> None:
        """Encode Decimal as extension."""
        if value.is_nan() or value.is_infinite():
            if not self.allow_nan:
                raise SerializationError("Cannot encode NaN or Infinity")
        self.stream.write(b"\xd6")  # fixext 8
        self.stream.write(b"\x01")  # type code 1 = Decimal
        self.stream.write(str(value).encode("utf-8")[:8].ljust(8, b"\x00"))

    def _encode_uuid(self, value: uuid.UUID) -> None:
        """Encode UUID as extension."""
        self.stream.write(b"\xd8")  # ext 8
        self.stream.write(b"\x02")  # type code 2 = UUID
        self.stream.write(b"\x10")  # length 16
        self.stream.write(value.bytes)

    def _encode_datetime(self, value: datetime) -> None:
        """Encode datetime as extension."""
        iso_str = value.isoformat().encode("utf-8")
        self.stream.write(b"\xd9")  # ext 16
        self.stream.write(b"\x03")  # type code 3 = datetime
        self.stream.write(struct.pack(">H", len(iso_str)))
        self.stream.write(iso_str)

    def _encode_date(self, value: date) -> None:
        """Encode date as extension."""
        iso_str = value.isoformat().encode("utf-8")
        self.stream.write(b"\xd9")
        self.stream.write(b"\x04")  # type code 4 = date
        self.stream.write(struct.pack(">H", len(iso_str)))
        self.stream.write(iso_str)

    def _encode_time(self, value: time) -> None:
        """Encode time as extension."""
        iso_str = value.isoformat().encode("utf-8")
        self.stream.write(b"\xd9")
        self.stream.write(b"\x05")  # type code 5 = time
        self.stream.write(struct.pack(">H", len(iso_str)))
        self.stream.write(iso_str)

    def _encode_enum(self, value: Enum) -> None:
        """Encode Enum as map."""
        self._encode_map({"_enum_type": value.__class__.__name__, "_enum_value": value.value})


class MessagePackDecoder:
    """Decodes MessagePack binary format to objects."""

    def __init__(self) -> None:
        self.stream = BytesIO()
        self.pos = 0

    def decode(self, data: bytes) -> Any:
        """Decode MessagePack bytes to object."""
        self.stream = BytesIO(data)
        self.pos = 0
        try:
            result = self._decode_value()
            return result
        except (struct.error, EOFError) as e:
            raise DeserializationError(f"Invalid MessagePack: {e}", data=data) from e

    def _read(self, n: int) -> bytes:
        """Read n bytes from stream."""
        data = self.stream.read(n)
        if len(data) < n:
            raise EOFError("Unexpected end of data")
        self.pos += n
        return data

    def _decode_value(self) -> Any:
        """Recursively decode a value."""
        first_byte = ord(self._read(1))

        # Positive fixint
        if (first_byte & 0x80) == 0:
            return first_byte

        # Negative fixint
        if (first_byte & 0xE0) == 0xE0:
            return struct.unpack("b", bytes([first_byte]))[0]

        # Fixmap
        if (first_byte & 0xF0) == 0x80:
            return self._decode_map(first_byte & 0x0F)

        # Fixarray
        if (first_byte & 0xF0) == 0x90:
            return self._decode_array(first_byte & 0x0F)

        # Fixstr
        if (first_byte & 0xE0) == 0xA0:
            return self._decode_str(first_byte & 0x1F)

        # Fixed types
        if first_byte == 0xC0:  # nil
            return None
        elif first_byte == 0xC2:  # false
            return False
        elif first_byte == 0xC3:  # true
            return True
        elif first_byte == 0xC4:  # bin 8
            return self._decode_bin(struct.unpack(">B", self._read(1))[0])
        elif first_byte == 0xC5:  # bin 16
            return self._decode_bin(struct.unpack(">H", self._read(2))[0])
        elif first_byte == 0xC6:  # bin 32
            return self._decode_bin(struct.unpack(">I", self._read(4))[0])
        elif first_byte == 0xCC:  # uint 8
            return struct.unpack(">B", self._read(1))[0]
        elif first_byte == 0xCD:  # uint 16
            return struct.unpack(">H", self._read(2))[0]
        elif first_byte == 0xCE:  # uint 32
            return struct.unpack(">I", self._read(4))[0]
        elif first_byte == 0xCF:  # uint 64
            return struct.unpack(">Q", self._read(8))[0]
        elif first_byte == 0xD0:  # int 8
            return struct.unpack(">b", self._read(1))[0]
        elif first_byte == 0xD1:  # int 16
            return struct.unpack(">h", self._read(2))[0]
        elif first_byte == 0xD2:  # int 32
            return struct.unpack(">i", self._read(4))[0]
        elif first_byte == 0xD3:  # int 64
            return struct.unpack(">q", self._read(8))[0]
        elif first_byte == 0xCB:  # float 64
            return struct.unpack(">d", self._read(8))[0]
        elif first_byte == 0xD9:  # str 8
            return self._decode_str(struct.unpack(">B", self._read(1))[0])
        elif first_byte == 0xDA:  # str 16
            return self._decode_str(struct.unpack(">H", self._read(2))[0])
        elif first_byte == 0xDB:  # str 32
            return self._decode_str(struct.unpack(">I", self._read(4))[0])
        elif first_byte == 0xDC:  # array 16
            return self._decode_array(struct.unpack(">H", self._read(2))[0])
        elif first_byte == 0xDD:  # array 32
            return self._decode_array(struct.unpack(">I", self._read(4))[0])
        elif first_byte == 0xDE:  # map 16
            return self._decode_map(struct.unpack(">H", self._read(2))[0])
        elif first_byte == 0xDF:  # map 32
            return self._decode_map(struct.unpack(">I", self._read(4))[0])

        raise DeserializationError(f"Unknown MessagePack type: 0x{first_byte:02x}")

    def _decode_str(self, length: int) -> str:
        """Decode string."""
        return self._read(length).decode("utf-8")

    def _decode_bin(self, length: int) -> bytes:
        """Decode binary data."""
        return self._read(length)

    def _decode_array(self, length: int) -> list:
        """Decode array."""
        return [self._decode_value() for _ in range(length)]

    def _decode_map(self, length: int) -> dict:
        """Decode map."""
        result = {}
        for _ in range(length):
            key = self._decode_str_key()
            value = self._decode_value()
            result[key] = value
        return result

    def _decode_str_key(self) -> str:
        """Decode a map key (must be string)."""
        first_byte = ord(self._read(1))
        if (first_byte & 0xE0) == 0xA0:
            return self._decode_str(first_byte & 0x1F)
        elif first_byte == 0xD9:
            return self._decode_str(struct.unpack(">B", self._read(1))[0])
        elif first_byte == 0xDA:
            return self._decode_str(struct.unpack(">H", self._read(2))[0])
        raise DeserializationError("Map keys must be strings")


class MessagePackCodec(Codec):
    """MessagePack serialization codec."""

    @property
    def format(self) -> SerializationFormat:
        """Return MessagePack format identifier."""
        return SerializationFormat.MSGPACK

    def encode(self, obj: Any, config: CodecConfig | None = None) -> bytes:
        """Encode object to MessagePack bytes.

        Args:
            obj: Object to serialize.
            config: Optional codec configuration.

        Returns:
            MessagePack bytes.

        Raises:
            SerializationError: If encoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            encoder = MessagePackEncoder(allow_nan=config.allow_nan)
            return encoder.encode(obj)
        except (TypeError, ValueError, SerializationError) as e:
            raise SerializationError(f"Failed to encode to MessagePack: {e}") from e

    def decode(self, data: bytes, config: CodecConfig | None = None) -> Any:
        """Decode MessagePack bytes to object.

        Args:
            data: MessagePack bytes.
            config: Optional codec configuration.

        Returns:
            Deserialized object.

        Raises:
            DeserializationError: If decoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            decoder = MessagePackDecoder()
            return decoder.decode(data)
        except DeserializationError:
            raise
        except Exception as e:
            raise DeserializationError(f"Failed to decode MessagePack: {e}", data=data) from e
