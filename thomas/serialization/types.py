"""
Core type definitions for the serialization module.

Defines SerializationFormat enum, CodecConfig, SchemaVersion, and WireMessage
dataclasses used throughout the serialization system.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SerializationFormat(str, Enum):
    """Supported serialization formats."""

    JSON = "json"
    MSGPACK = "msgpack"
    PROTOBUF = "protobuf"
    CBOR = "cbor"


class CompressionType(str, Enum):
    """Supported compression algorithms."""

    NONE = "none"
    ZLIB = "zlib"
    GZIP = "gzip"
    LZ77 = "lz77"


@dataclass
class CodecConfig:
    """Configuration for codec behavior.

    Attributes:
        format: The serialization format to use.
        version: Schema version for compatibility checking.
        strict_mode: If True, raise errors on unknown fields.
        pretty_print: If True, format output for readability (JSON only).
        compression: Compression algorithm to apply.
        compression_level: Level of compression (1-9, higher = more compression).
        compression_threshold: Skip compression if payload < threshold bytes.
        allow_nan: Allow NaN/Infinity in floating point numbers (JSON only).
    """

    format: SerializationFormat = SerializationFormat.JSON
    version: int = 1
    strict_mode: bool = False
    pretty_print: bool = False
    compression: CompressionType = CompressionType.NONE
    compression_level: int = 6
    compression_threshold: int = 256
    allow_nan: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.compression_level <= 9:
            raise ValueError(f"compression_level must be 1-9, got {self.compression_level}")
        if self.compression_threshold < 0:
            raise ValueError(f"compression_threshold must be non-negative, got {self.compression_threshold}")


@dataclass
class SchemaVersion:
    """Represents a schema version for forward/backward compatibility.

    Attributes:
        major: Major version number (breaking changes).
        minor: Minor version number (backwards-compatible additions).
        patch: Patch version number (bug fixes).
    """

    major: int
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: "SchemaVersion") -> bool:
        return (self.major, self.minor, self.patch) < (
            other.major,
            other.minor,
            other.patch,
        )

    def __le__(self, other: "SchemaVersion") -> bool:
        return (self.major, self.minor, self.patch) <= (
            other.major,
            other.minor,
            other.patch,
        )

    def __gt__(self, other: "SchemaVersion") -> bool:
        return (self.major, self.minor, self.patch) > (
            other.major,
            other.minor,
            other.patch,
        )

    def __ge__(self, other: "SchemaVersion") -> bool:
        return (self.major, self.minor, self.patch) >= (
            other.major,
            other.minor,
            other.patch,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SchemaVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (
            other.major,
            other.minor,
            other.patch,
        )

    def is_compatible_with(self, other: "SchemaVersion") -> bool:
        """Check if this version is forward-compatible with another.

        Versions are compatible if they have the same major version.
        """
        return self.major == other.major


@dataclass
class FieldDescriptor:
    """Describes a field in a message schema.

    Attributes:
        name: Field name.
        field_type: Python type or string type name.
        tag: Field tag number (protobuf-style).
        required: Whether field is required.
        default: Default value if field is missing.
        repeated: Whether field is a repeated/array type.
        embedded: Whether field contains nested messages.
        deprecated: Whether this field is deprecated.
    """

    name: str
    field_type: str
    tag: int
    required: bool = False
    default: Any = None
    repeated: bool = False
    embedded: bool = False
    deprecated: bool = False

    def __post_init__(self) -> None:
        if self.tag < 1 or self.tag > 536870911:  # Max protobuf tag
            raise ValueError(f"Field tag must be 1-536870911, got {self.tag}")


@dataclass
class MessageDescriptor:
    """Describes a complete message schema.

    Attributes:
        name: Message name.
        version: Schema version.
        fields: Mapping of field names to FieldDescriptor objects.
        reserved_tags: Set of reserved field tags.
    """

    name: str
    version: SchemaVersion
    fields: dict[str, FieldDescriptor] = field(default_factory=dict)
    reserved_tags: set = field(default_factory=set)

    def __post_init__(self) -> None:
        # Validate no duplicate tags
        tags = [f.tag for f in self.fields.values()]
        if len(tags) != len(set(tags)):
            raise ValueError("Duplicate field tags detected")

        for tag in self.reserved_tags:
            if any(f.tag == tag for f in self.fields.values()):
                raise ValueError(f"Reserved tag {tag} is used by a field")

    def get_field(self, name: str) -> FieldDescriptor | None:
        """Get field descriptor by name."""
        return self.fields.get(name)

    def get_field_by_tag(self, tag: int) -> FieldDescriptor | None:
        """Get field descriptor by tag number."""
        for field in self.fields.values():
            if field.tag == tag:
                return field
        return None


@dataclass
class WireMessage:
    """Represents a serialized message with metadata.

    Attributes:
        format: Serialization format used.
        version: Schema version of payload.
        compressed: Compression algorithm applied (if any).
        payload: Raw serialized bytes.
        metadata: Optional metadata dictionary.
    """

    format: SerializationFormat
    version: int
    compressed: CompressionType
    payload: bytes
    metadata: dict[str, Any] = field(default_factory=dict)

    def size(self) -> int:
        """Return total wire size including headers."""
        # Rough estimation: format (1) + version (1) + compressed (1) + payload
        return 3 + len(self.payload)

    def compression_ratio(self) -> float | None:
        """Return compression ratio (original/compressed) if compressed."""
        original_size = self.metadata.get("original_size")
        if original_size:
            return original_size / len(self.payload)
        return None
