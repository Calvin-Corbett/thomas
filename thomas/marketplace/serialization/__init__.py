"""
Thomas Serialization Module - Public API

Provides a flexible codec registry for multiple serialization formats including
JSON, MessagePack, Protobuf, and CBOR with support for schema evolution,
compression, and wire format negotiation.
"""

from .cbor_codec import CBORCodec
from .codec import Codec, CodecRegistry, codec_registry
from .compression import CompressionAlgorithm, compress, decompress
from .exceptions import (
    CodecNotFoundError,
    DeserializationError,
    IncompatibleSchemaError,
    SchemaVersionError,
    SerializationError,
)
from .json_codec import JSONCodec
from .msgpack_codec import MessagePackCodec
from .protobuf_codec import ProtobufCodec
from .registry import benchmark_codecs, format_negotiate, register_codec
from .schema_evolution import (
    FieldDescriptor,
    MessageDescriptor,
    SchemaVersion,
    apply_migration,
    check_backward_compatibility,
    check_forward_compatibility,
)
from .types import CodecConfig, CompressionType, SerializationFormat, WireMessage
from .wire_format import WireFormatter, pack_message, unpack_message

__all__ = [
    # Core types
    "SerializationFormat",
    "CompressionType",
    "CodecConfig",
    "WireMessage",
    "SchemaVersion",
    "MessageDescriptor",
    "FieldDescriptor",
    # Codecs
    "Codec",
    "CodecRegistry",
    "codec_registry",
    "JSONCodec",
    "MessagePackCodec",
    "ProtobufCodec",
    "CBORCodec",
    # Compression
    "CompressionAlgorithm",
    "compress",
    "decompress",
    # Exceptions
    "SerializationError",
    "DeserializationError",
    "SchemaVersionError",
    "CodecNotFoundError",
    "IncompatibleSchemaError",
    # Registry and negotiation
    "format_negotiate",
    "benchmark_codecs",
    "register_codec",
    # Schema evolution
    "check_forward_compatibility",
    "check_backward_compatibility",
    "apply_migration",
    # Wire format
    "WireFormatter",
    "pack_message",
    "unpack_message",
]

__version__ = "0.1.0"
