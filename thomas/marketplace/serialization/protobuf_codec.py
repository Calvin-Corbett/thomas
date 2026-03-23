"""
Protobuf-style binary codec.

Implements Protocol Buffers-compatible binary serialization with varint
encoding, zigzag for signed integers, length-delimited fields, wire types,
and nested message support.
"""

import struct
from io import BytesIO
from typing import Any

from .codec import Codec
from .exceptions import DeserializationError, SerializationError
from .types import CodecConfig, FieldDescriptor, MessageDescriptor, SerializationFormat


class ProtobufEncoder:
    """Encodes objects to Protobuf binary format."""

    # Wire types
    WIRE_VARINT = 0
    WIRE_64BIT = 1
    WIRE_LENGTH_DELIMITED = 2
    WIRE_32BIT = 5

    def __init__(self) -> None:
        self.stream = BytesIO()

    def encode(self, obj: dict[str, Any], descriptor: MessageDescriptor | None = None) -> bytes:
        """Encode object to Protobuf bytes."""
        if isinstance(obj, dict):
            untyped_tags: dict[str, int] = {}
            for key, value in obj.items():
                if descriptor:
                    field = descriptor.get_field(key)
                    if field:
                        self._encode_field(key, value, field)
                else:
                    # Best effort without descriptor
                    self._encode_untyped_field(key, value, untyped_tags)
        return self.stream.getvalue()

    def _encode_field(self, name: str, value: Any, field: FieldDescriptor) -> None:
        """Encode a single field."""
        if value is None:
            return

        tag = field.tag
        if field.repeated and isinstance(value, list):
            for item in value:
                self._encode_value(tag, item, field.field_type)
        else:
            self._encode_value(tag, value, field.field_type)

    def _encode_untyped_field(self, name: str, value: Any, tag_map: dict[str, int]) -> None:
        """Encode field without schema."""
        # Assign compact deterministic tags in encounter order.
        tag = tag_map.setdefault(name, len(tag_map) + 1)

        if isinstance(value, bool):
            self._encode_value(tag, value, "bool")
        elif isinstance(value, int):
            self._encode_value(tag, value, "int64")
        elif isinstance(value, float):
            self._encode_value(tag, value, "double")
        elif isinstance(value, str):
            self._encode_value(tag, value, "string")
        elif isinstance(value, bytes):
            self._encode_value(tag, value, "bytes")
        elif isinstance(value, dict):
            self._encode_value(tag, value, "message")
        elif isinstance(value, list):
            for item in value:
                self._encode_untyped_field(f"{name}[]", item, tag_map)

    def _encode_value(self, tag: int, value: Any, field_type: str) -> None:
        """Encode a value with given type."""
        field_bytes = self._encode_field_value(value, field_type)
        self._write_tag_and_wire_type(tag, self._get_wire_type(field_type))

        if field_type in ("string", "bytes", "message"):
            self._write_varint(len(field_bytes))

        self.stream.write(field_bytes)

    def _encode_field_value(self, value: Any, field_type: str) -> bytes:
        """Encode field value to bytes."""
        stream = BytesIO()

        if field_type == "bool":
            stream.write(b"\x01" if value else b"\x00")
        elif field_type in ("int32", "int64"):
            self._write_varint_to_stream(stream, value)
        elif field_type in ("sint32", "sint64"):
            zigzag_value = self._zigzag_encode(value)
            self._write_varint_to_stream(stream, zigzag_value)
        elif field_type in ("float", "fixed32"):
            stream.write(struct.pack("<f", value))
        elif field_type in ("double", "fixed64"):
            stream.write(struct.pack("<d", value))
        elif field_type == "string":
            stream.write(value.encode("utf-8"))
        elif field_type == "bytes":
            if isinstance(value, str):
                stream.write(value.encode("utf-8"))
            else:
                stream.write(value)
        elif field_type == "message":
            if isinstance(value, dict):
                nested_encoder = ProtobufEncoder()
                stream.write(nested_encoder.encode(value))

        return stream.getvalue()

    def _write_tag_and_wire_type(self, tag: int, wire_type: int) -> None:
        """Write tag and wire type as a single varint."""
        key = (tag << 3) | wire_type
        self._write_varint(key)

    def _write_varint(self, value: int) -> None:
        """Write a varint to stream."""
        self._write_varint_to_stream(self.stream, value)

    @staticmethod
    def _write_varint_to_stream(stream: BytesIO, value: int) -> None:
        """Write a varint to a stream."""
        while value > 0x7F:
            stream.write(bytes([(value & 0x7F) | 0x80]))
            value >>= 7
        stream.write(bytes([value & 0x7F]))

    @staticmethod
    def _get_wire_type(field_type: str) -> int:
        """Get wire type for field type."""
        if field_type in ("double", "fixed64"):
            return ProtobufEncoder.WIRE_64BIT
        elif field_type in ("float", "fixed32"):
            return ProtobufEncoder.WIRE_32BIT
        elif field_type in ("string", "bytes", "message"):
            return ProtobufEncoder.WIRE_LENGTH_DELIMITED
        else:
            return ProtobufEncoder.WIRE_VARINT

    @staticmethod
    def _zigzag_encode(value: int) -> int:
        """Encode signed int using zigzag."""
        return (value << 1) ^ (value >> 31)


class ProtobufDecoder:
    """Decodes Protobuf binary format to objects."""

    WIRE_VARINT = 0
    WIRE_64BIT = 1
    WIRE_LENGTH_DELIMITED = 2
    WIRE_32BIT = 5

    def __init__(self) -> None:
        self.stream = BytesIO()
        self.pos = 0

    def decode(
        self,
        data: bytes,
        descriptor: MessageDescriptor | None = None,
    ) -> dict[str, Any]:
        """Decode Protobuf bytes to object."""
        self.stream = BytesIO(data)
        self.pos = 0
        result = {}

        try:
            while self.stream.tell() < len(data):
                tag, wire_type = self._read_tag()

                if descriptor:
                    field = descriptor.get_field_by_tag(tag)
                    if field:
                        value = self._read_value(wire_type, field.field_type)
                        if field.repeated:
                            if field.name not in result:
                                result[field.name] = []
                            result[field.name].append(value)
                        else:
                            result[field.name] = value
                    else:
                        # Skip unknown field
                        self._skip_field(wire_type)
                else:
                    # Try to decode without schema
                    value = self._read_value(wire_type, "unknown")
                    result[f"field_{tag}"] = value
                    result["field_"] = value
        except (struct.error, EOFError) as e:
            raise DeserializationError(f"Invalid Protobuf: {e}", data=data) from e

        return result

    def _read_tag(self) -> tuple[int, int]:
        """Read tag and wire type."""
        key = self._read_varint()
        tag = key >> 3
        wire_type = key & 0x07
        return tag, wire_type

    def _read_value(self, wire_type: int, field_type: str) -> Any:
        """Read a value based on wire type."""
        if wire_type == self.WIRE_VARINT:
            value = self._read_varint()
            if field_type == "bool":
                return bool(value)
            if field_type in ("sint32", "sint64"):
                return self._zigzag_decode(value)
            return value
        elif wire_type == self.WIRE_64BIT:
            data = self.stream.read(8)
            if field_type in ("double", "fixed64"):
                return struct.unpack("<d", data)[0]
            return struct.unpack("<Q", data)[0]
        elif wire_type == self.WIRE_LENGTH_DELIMITED:
            length = self._read_varint()
            data = self.stream.read(length)
            if field_type == "string":
                return data.decode("utf-8")
            elif field_type == "bytes":
                return data
            elif field_type == "message":
                # Recursive decode
                decoder = ProtobufDecoder()
                return decoder.decode(data)
            return data
        elif wire_type == self.WIRE_32BIT:
            data = self.stream.read(4)
            if field_type in ("float", "fixed32"):
                return struct.unpack("<f", data)[0]
            return struct.unpack("<I", data)[0]
        else:
            raise DeserializationError(f"Unknown wire type: {wire_type}")

    def _skip_field(self, wire_type: int) -> None:
        """Skip a field of unknown type."""
        if wire_type == self.WIRE_VARINT:
            self._read_varint()
        elif wire_type == self.WIRE_64BIT:
            self.stream.read(8)
        elif wire_type == self.WIRE_LENGTH_DELIMITED:
            length = self._read_varint()
            self.stream.read(length)
        elif wire_type == self.WIRE_32BIT:
            self.stream.read(4)

    def _read_varint(self) -> int:
        """Read a varint."""
        result = 0
        shift = 0

        while True:
            byte_data = self.stream.read(1)
            if not byte_data:
                raise EOFError("Unexpected end of data")

            byte = byte_data[0]
            result |= (byte & 0x7F) << shift

            if (byte & 0x80) == 0:
                break

            shift += 7

        return result

    @staticmethod
    def _zigzag_decode(value: int) -> int:
        """Decode signed int from zigzag."""
        return (value >> 1) ^ -(value & 1)


class ProtobufCodec(Codec):
    """Protobuf serialization codec."""

    @property
    def format(self) -> SerializationFormat:
        """Return Protobuf format identifier."""
        return SerializationFormat.PROTOBUF

    def encode(
        self,
        obj: Any,
        config: CodecConfig | None = None,
        descriptor: MessageDescriptor | None = None,
    ) -> bytes:
        """Encode object to Protobuf bytes.

        Args:
            obj: Object to serialize (dict).
            config: Optional codec configuration.
            descriptor: Optional message schema descriptor.

        Returns:
            Protobuf bytes.

        Raises:
            SerializationError: If encoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            encoder = ProtobufEncoder()
            return encoder.encode(obj, descriptor)
        except (TypeError, ValueError, SerializationError) as e:
            raise SerializationError(f"Failed to encode to Protobuf: {e}") from e

    def decode(
        self,
        data: bytes,
        config: CodecConfig | None = None,
        descriptor: MessageDescriptor | None = None,
    ) -> dict[str, Any]:
        """Decode Protobuf bytes to object.

        Args:
            data: Protobuf bytes.
            config: Optional codec configuration.
            descriptor: Optional message schema descriptor.

        Returns:
            Deserialized object.

        Raises:
            DeserializationError: If decoding fails.
        """
        if config is None:
            config = CodecConfig(format=self.format)

        try:
            decoder = ProtobufDecoder()
            return decoder.decode(data, descriptor)
        except DeserializationError:
            raise
        except Exception as e:
            raise DeserializationError(f"Failed to decode Protobuf: {e}", data=data) from e
