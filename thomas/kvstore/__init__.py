"""Thomas KV Store - An LSM-tree key-value store.

A complete, production-quality key-value store implementation with:
- Write-ahead logging for durability
- In-memory skip list memtable
- Multi-level sorted string tables (SSTables)
- Configurable compaction strategies
- Bloom filters for fast negative lookups
- Thread-safe operations
"""

from thomas.kvstore._exceptions import (
    BloomFilterError,
    CompactionError,
    CorruptionError,
    KeyNotFoundError,
    KVStoreError,
    ManifestError,
    SSTableError,
    WALError,
)
from thomas.kvstore._types import (
    BloomFilterConfig,
    CompactionStrategy,
    KeyValue,
    KVStoreConfig,
    SSTableEntry,
    WALEntry,
    WriteOp,
    WriteOperation,
)
from thomas.kvstore.bloom_filter import BloomFilter
from thomas.kvstore.compaction import Compactor, LeveledCompactor, SizeTieredCompactor
from thomas.kvstore.iterators import MergeIterator, RangeMergeIterator
from thomas.kvstore.manifest import Manifest
from thomas.kvstore.memtable import Memtable
from thomas.kvstore.skiplist import SkipList
from thomas.kvstore.sstable import SSTable, SSTableWriter
from thomas.kvstore.store import KVStore
from thomas.kvstore.wal import WAL

__version__ = "1.0.0"

__all__ = [
    # Types and configuration
    "WriteOp",
    "CompactionStrategy",
    "KeyValue",
    "WriteOperation",
    "SSTableEntry",
    "WALEntry",
    "BloomFilterConfig",
    "KVStoreConfig",
    # Exceptions
    "KVStoreError",
    "KeyNotFoundError",
    "CorruptionError",
    "WALError",
    "CompactionError",
    "BloomFilterError",
    "SSTableError",
    "ManifestError",
    # Main components
    "KVStore",
    "Memtable",
    "SkipList",
    "BloomFilter",
    "WAL",
    "SSTable",
    "SSTableWriter",
    "Compactor",
    "LeveledCompactor",
    "SizeTieredCompactor",
    "Manifest",
    "MergeIterator",
    "RangeMergeIterator",
]
