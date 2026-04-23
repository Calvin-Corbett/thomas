"""
Columnar Storage and Analytics Engine

A high-performance columnar database engine inspired by Apache Arrow and Parquet,
providing efficient storage, compression, indexing, and vectorized query execution.
"""

from thomas.marketplace.columnar._exceptions import (
    ColumnarException,
    ColumnTypeError,
    CompressionError,
    EncodingError,
    QueryError,
    StorageError,
)
from thomas.marketplace.columnar._exceptions import (
    IndexError as ColumnarIndexError,
)
from thomas.marketplace.columnar._types import (
    ColumnChunk,
    ColumnType,
    Compression,
    DataPage,
    DictionaryPage,
    Encoding,
    Field,
    PageHeader,
    RowGroup,
    Schema,
    Statistics,
)
from thomas.marketplace.columnar.compression import (
    compress_lz4,
    compress_snappy,
    compress_zstd,
    decompress_lz4,
    decompress_snappy,
    decompress_zstd,
    select_compression,
)
from thomas.marketplace.columnar.encoding import (
    decode_delta,
    decode_dictionary,
    decode_plain,
    decode_rle,
    encode_delta,
    encode_dictionary,
    encode_plain,
    encode_rle,
    select_encoding,
)
from thomas.marketplace.columnar.indexes import (
    BitmapIndex,
    BloomFilter,
    IndexAdvisor,
    InvertedIndex,
    ZoneMap,
)
from thomas.marketplace.columnar.partitioning import (
    HashPartitioner,
    ListPartitioner,
    PartitionPruner,
    PartitionScheme,
    RangePartitioner,
)
from thomas.marketplace.columnar.query import (
    ColumnBatch,
    QueryExecutor,
    VectorizedAggregation,
    VectorizedFilter,
)
from thomas.marketplace.columnar.storage import (
    ColumnarFileReader,
    ColumnarFileWriter,
    ColumnChunkReader,
    ColumnChunkWriter,
    RowGroupReader,
    RowGroupWriter,
)

__all__ = [
    "ColumnType",
    "Schema",
    "Field",
    "ColumnChunk",
    "RowGroup",
    "DataPage",
    "DictionaryPage",
    "PageHeader",
    "Statistics",
    "Encoding",
    "Compression",
    "ColumnarException",
    "ColumnTypeError",
    "CompressionError",
    "EncodingError",
    "StorageError",
    "QueryError",
    "ColumnarIndexError",
    "encode_plain",
    "decode_plain",
    "encode_dictionary",
    "decode_dictionary",
    "encode_rle",
    "decode_rle",
    "encode_delta",
    "decode_delta",
    "select_encoding",
    "compress_lz4",
    "decompress_lz4",
    "compress_snappy",
    "decompress_snappy",
    "compress_zstd",
    "decompress_zstd",
    "select_compression",
    "ColumnChunkWriter",
    "ColumnChunkReader",
    "RowGroupWriter",
    "RowGroupReader",
    "ColumnarFileWriter",
    "ColumnarFileReader",
    "ColumnBatch",
    "QueryExecutor",
    "VectorizedFilter",
    "VectorizedAggregation",
    "BitmapIndex",
    "ZoneMap",
    "BloomFilter",
    "InvertedIndex",
    "IndexAdvisor",
    "PartitionScheme",
    "RangePartitioner",
    "HashPartitioner",
    "ListPartitioner",
    "PartitionPruner",
]

__version__ = "0.1.0"
