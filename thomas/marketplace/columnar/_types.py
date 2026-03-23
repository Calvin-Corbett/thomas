"""
Type system and data structure definitions for columnar storage engine.

Defines column types, schema, field metadata, column chunks, row groups,
pages, statistics, and compression/encoding options.
"""

import struct
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, auto
from typing import Any, Optional


class ColumnType(Enum):
    """Enumeration of supported column data types."""

    INT8 = auto()
    INT16 = auto()
    INT32 = auto()
    INT64 = auto()
    UINT8 = auto()
    UINT16 = auto()
    UINT32 = auto()
    UINT64 = auto()
    FLOAT32 = auto()
    FLOAT64 = auto()
    BOOL = auto()
    STRING = auto()
    BINARY = auto()
    DATE = auto()
    TIMESTAMP = auto()
    DECIMAL = auto()
    LIST = auto()
    STRUCT = auto()
    MAP = auto()

    def byte_width(self) -> int | None:
        """Return fixed byte width for primitive types, None for variable-length."""
        widths = {
            ColumnType.INT8: 1,
            ColumnType.INT16: 2,
            ColumnType.INT32: 4,
            ColumnType.INT64: 8,
            ColumnType.UINT8: 1,
            ColumnType.UINT16: 2,
            ColumnType.UINT32: 4,
            ColumnType.UINT64: 8,
            ColumnType.FLOAT32: 4,
            ColumnType.FLOAT64: 8,
            ColumnType.BOOL: 1,
            ColumnType.DATE: 4,
            ColumnType.TIMESTAMP: 8,
        }
        return widths.get(self)

    def is_numeric(self) -> bool:
        """Check if type is numeric."""
        numeric_types = {
            ColumnType.INT8,
            ColumnType.INT16,
            ColumnType.INT32,
            ColumnType.INT64,
            ColumnType.UINT8,
            ColumnType.UINT16,
            ColumnType.UINT32,
            ColumnType.UINT64,
            ColumnType.FLOAT32,
            ColumnType.FLOAT64,
            ColumnType.DECIMAL,
        }
        return self in numeric_types

    def is_integer(self) -> bool:
        """Check if type is integer."""
        int_types = {
            ColumnType.INT8,
            ColumnType.INT16,
            ColumnType.INT32,
            ColumnType.INT64,
            ColumnType.UINT8,
            ColumnType.UINT16,
            ColumnType.UINT32,
            ColumnType.UINT64,
        }
        return self in int_types

    def is_floating_point(self) -> bool:
        """Check if type is floating point."""
        return self in {ColumnType.FLOAT32, ColumnType.FLOAT64}

    def is_string_like(self) -> bool:
        """Check if type is string or binary."""
        return self in {ColumnType.STRING, ColumnType.BINARY}

    def is_temporal(self) -> bool:
        """Check if type is date or timestamp."""
        return self in {ColumnType.DATE, ColumnType.TIMESTAMP}


class Encoding(Enum):
    """Column encoding schemes."""

    PLAIN = auto()
    DICTIONARY = auto()
    RLE = auto()
    DELTA = auto()
    BIT_PACKED = auto()
    HYBRID_RLE_BIT_PACKED = auto()
    BYTE_ARRAY = auto()
    BOOLEAN = auto()


class Compression(Enum):
    """Compression algorithms."""

    NONE = auto()
    LZ4 = auto()
    SNAPPY = auto()
    ZSTD = auto()


@dataclass
class Field:
    """Field definition in schema."""

    name: str
    column_type: ColumnType
    nullable: bool = True
    scale: int = 0  # For DECIMAL type
    precision: int = 0  # For DECIMAL type
    element_type: Optional["Field"] = None  # For LIST type
    key_type: Optional["Field"] = None  # For MAP type
    value_type: Optional["Field"] = None  # For MAP type
    fields: list["Field"] = field(default_factory=list)  # For STRUCT type

    def __post_init__(self) -> None:
        """Validate field configuration."""
        if self.column_type == ColumnType.DECIMAL and (self.precision <= 0 or self.scale < 0):
            raise ValueError("DECIMAL requires positive precision and non-negative scale")
        if self.column_type == ColumnType.LIST and self.element_type is None:
            raise ValueError("LIST type requires element_type")
        if self.column_type == ColumnType.MAP and (self.key_type is None or self.value_type is None):
            raise ValueError("MAP type requires key_type and value_type")
        if self.column_type == ColumnType.STRUCT and not self.fields:
            raise ValueError("STRUCT type requires fields")

    def clone(self) -> "Field":
        """Create a copy of this field."""
        return Field(
            name=self.name,
            column_type=self.column_type,
            nullable=self.nullable,
            scale=self.scale,
            precision=self.precision,
            element_type=self.element_type.clone() if self.element_type else None,
            key_type=self.key_type.clone() if self.key_type else None,
            value_type=self.value_type.clone() if self.value_type else None,
            fields=[f.clone() for f in self.fields],
        )


@dataclass
class Schema:
    """Column schema definition."""

    fields: list[Field]
    metadata: dict[str, str] = field(default_factory=dict)

    def get_field(self, name: str) -> Field | None:
        """Get field by name."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def get_field_index(self, name: str) -> int:
        """Get field index by name, raises ValueError if not found."""
        for i, f in enumerate(self.fields):
            if f.name == name:
                return i
        raise ValueError(f"Field '{name}' not found in schema")

    def clone(self) -> "Schema":
        """Create a copy of this schema."""
        return Schema(
            fields=[f.clone() for f in self.fields],
            metadata=dict(self.metadata),
        )


@dataclass
class Statistics:
    """Column chunk statistics for predicate pushdown and optimization."""

    min_value: Any = None
    max_value: Any = None
    null_count: int = 0
    distinct_count: int = 0
    total_value_count: int = 0

    def is_null_only(self) -> bool:
        """Check if all values are null."""
        return self.total_value_count == self.null_count

    def get_null_fraction(self) -> float:
        """Get fraction of null values."""
        if self.total_value_count == 0:
            return 0.0
        return self.null_count / self.total_value_count

    def update(self, values: list[Any]) -> None:
        """Update statistics based on values."""
        non_null = [v for v in values if v is not None]

        self.total_value_count = len(values)
        self.null_count = len(values) - len(non_null)

        if non_null:
            self.min_value = min(non_null)
            self.max_value = max(non_null)
            self.distinct_count = len(set(non_null))
        else:
            self.min_value = None
            self.max_value = None
            self.distinct_count = 0


@dataclass
class PageHeader:
    """Header metadata for a data page."""

    page_type: str  # "DATA_PAGE", "INDEX_PAGE", "DICTIONARY_PAGE"
    uncompressed_size: int
    compressed_size: int
    data_page_header: dict[str, Any] | None = None
    dictionary_page_header: dict[str, Any] | None = None
    index_page_header: dict[str, Any] | None = None


@dataclass
class DataPage:
    """Column data page with values and nulls."""

    column_index: int
    page_number: int
    encoding: Encoding
    compression: Compression
    data: bytes
    null_bitmap: bytes | None = None
    statistics: Statistics | None = None
    is_dictionary_encoded: bool = False

    def uncompressed_size(self) -> int:
        """Return uncompressed data size in bytes."""
        size = len(self.data)
        if self.null_bitmap:
            size += len(self.null_bitmap)
        return size


@dataclass
class DictionaryPage:
    """Dictionary page for dictionary encoding."""

    column_index: int
    dictionary_values: list[Any]
    encoding: Encoding = Encoding.DICTIONARY
    compression: Compression = Compression.NONE
    data: bytes = field(default_factory=bytes)

    def get_dictionary_size(self) -> int:
        """Get number of distinct values in dictionary."""
        return len(self.dictionary_values)

    def encode_value(self, value: Any) -> int:
        """Get dictionary index for value, -1 if not found."""
        try:
            return self.dictionary_values.index(value)
        except ValueError:
            return -1


@dataclass
class ColumnChunk:
    """Column chunk: pages for a single column in a row group."""

    column_index: int
    column_name: str
    column_type: ColumnType
    encoding: Encoding
    compression: Compression
    pages: list[DataPage] = field(default_factory=list)
    dictionary_page: DictionaryPage | None = None
    statistics: Statistics | None = None

    def add_page(self, page: DataPage) -> None:
        """Add data page to chunk."""
        self.pages.append(page)

    def get_total_uncompressed_size(self) -> int:
        """Calculate total uncompressed size of all pages."""
        size = sum(page.uncompressed_size() for page in self.pages)
        if self.dictionary_page:
            size += len(self.dictionary_page.data)
        return size

    def get_total_compressed_size(self) -> int:
        """Calculate total compressed size of all pages."""
        size = sum(len(page.data) for page in self.pages)
        if self.dictionary_page:
            size += len(self.dictionary_page.data)
        return size


@dataclass
class RowGroup:
    """Row group: collection of column chunks for a range of rows."""

    group_id: int
    num_rows: int
    column_chunks: dict[int, ColumnChunk] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_column_chunk(self, column_chunk: ColumnChunk) -> None:
        """Add column chunk to row group."""
        self.column_chunks[column_chunk.column_index] = column_chunk

    def get_column_chunk(self, column_index: int) -> ColumnChunk | None:
        """Get column chunk by index."""
        return self.column_chunks.get(column_index)

    def get_total_uncompressed_size(self) -> int:
        """Calculate total uncompressed size of all chunks."""
        return sum(chunk.get_total_uncompressed_size() for chunk in self.column_chunks.values())

    def get_total_compressed_size(self) -> int:
        """Calculate total compressed size of all chunks."""
        return sum(chunk.get_total_compressed_size() for chunk in self.column_chunks.values())

    def get_compression_ratio(self) -> float:
        """Calculate compression ratio."""
        uncompressed = self.get_total_uncompressed_size()
        if uncompressed == 0:
            return 1.0
        compressed = self.get_total_compressed_size()
        return uncompressed / compressed if compressed > 0 else 1.0


@dataclass
class ColumnarFileMetadata:
    """Metadata for a columnar file."""

    schema: Schema
    num_rows: int
    created_by: str = "thomas-columnar/0.1.0"
    created_at: int | None = None
    row_groups: list[RowGroup] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def get_total_uncompressed_size(self) -> int:
        """Calculate total uncompressed size across all row groups."""
        return sum(rg.get_total_uncompressed_size() for rg in self.row_groups)

    def get_total_compressed_size(self) -> int:
        """Calculate total compressed size across all row groups."""
        return sum(rg.get_total_compressed_size() for rg in self.row_groups)

    def get_compression_ratio(self) -> float:
        """Calculate overall compression ratio."""
        uncompressed = self.get_total_uncompressed_size()
        if uncompressed == 0:
            return 1.0
        compressed = self.get_total_compressed_size()
        return uncompressed / compressed if compressed > 0 else 1.0


class TypeSerDe:
    """Type serialization/deserialization utilities."""

    @staticmethod
    def serialize_int8(value: int) -> bytes:
        """Serialize INT8 value."""
        return struct.pack("b", value)

    @staticmethod
    def deserialize_int8(data: bytes) -> int:
        """Deserialize INT8 value."""
        return struct.unpack("b", data[:1])[0]

    @staticmethod
    def serialize_int32(value: int) -> bytes:
        """Serialize INT32 value."""
        return struct.pack("<i", value)

    @staticmethod
    def deserialize_int32(data: bytes) -> int:
        """Deserialize INT32 value."""
        return struct.unpack("<i", data[:4])[0]

    @staticmethod
    def serialize_int64(value: int) -> bytes:
        """Serialize INT64 value."""
        return struct.pack("<q", value)

    @staticmethod
    def deserialize_int64(data: bytes) -> int:
        """Deserialize INT64 value."""
        return struct.unpack("<q", data[:8])[0]

    @staticmethod
    def serialize_float64(value: float) -> bytes:
        """Serialize FLOAT64 value."""
        return struct.pack("<d", value)

    @staticmethod
    def deserialize_float64(data: bytes) -> float:
        """Deserialize FLOAT64 value."""
        return struct.unpack("<d", data[:8])[0]

    @staticmethod
    def serialize_bool(value: bool) -> bytes:
        """Serialize BOOL value."""
        return b"\x01" if value else b"\x00"

    @staticmethod
    def deserialize_bool(data: bytes) -> bool:
        """Deserialize BOOL value."""
        return data[0] != 0

    @staticmethod
    def serialize_string(value: str) -> bytes:
        """Serialize STRING value."""
        encoded = value.encode("utf-8")
        length = struct.pack("<I", len(encoded))
        return length + encoded

    @staticmethod
    def deserialize_string(data: bytes, offset: int = 0) -> tuple[str, int]:
        """Deserialize STRING value, return (value, bytes_consumed)."""
        length = struct.unpack("<I", data[offset : offset + 4])[0]
        value = data[offset + 4 : offset + 4 + length].decode("utf-8")
        return value, 4 + length

    @staticmethod
    def serialize_date(value: date) -> bytes:
        """Serialize DATE value as days since epoch."""
        days = (value - date(1970, 1, 1)).days
        return struct.pack("<i", days)

    @staticmethod
    def deserialize_date(data: bytes) -> date:
        """Deserialize DATE value."""
        days = struct.unpack("<i", data[:4])[0]
        epoch = date(1970, 1, 1)
        return epoch + __import__("datetime").timedelta(days=days)

    @staticmethod
    def serialize_timestamp(value: datetime) -> bytes:
        """Serialize TIMESTAMP as microseconds since epoch."""
        epoch = datetime(1970, 1, 1)
        micros = int((value - epoch).total_seconds() * 1_000_000)
        return struct.pack("<q", micros)

    @staticmethod
    def deserialize_timestamp(data: bytes) -> datetime:
        """Deserialize TIMESTAMP value."""
        micros = struct.unpack("<q", data[:8])[0]
        epoch = datetime(1970, 1, 1)
        return epoch + __import__("datetime").timedelta(microseconds=micros)
