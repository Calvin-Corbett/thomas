"""Data types and configuration for the KV store."""

from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class WriteOp(Enum):
    """Write operation type."""

    PUT = "put"
    DELETE = "delete"


class CompactionStrategy(Enum):
    """Compaction strategy."""

    SIZE_TIERED = "size_tiered"
    LEVELED = "leveled"


class KeyValue(NamedTuple):
    """A key-value pair."""

    key: bytes
    value: bytes


class WriteOperation(NamedTuple):
    """A write operation to be stored in WAL and memtable."""

    op: WriteOp
    key: bytes
    value: bytes | None
    sequence: int


class SSTableEntry(NamedTuple):
    """Entry in an SSTable."""

    key: bytes
    value: bytes | None  # None indicates tombstone
    sequence: int


class WALEntry(NamedTuple):
    """Entry in the write-ahead log."""

    sequence: int
    op: WriteOp
    key: bytes
    value: bytes | None
    timestamp: float


@dataclass
class BloomFilterConfig:
    """Configuration for Bloom filter."""

    expected_items: int = 10000
    false_positive_rate: float = 0.01

    def __post_init__(self):
        if not 0 < self.false_positive_rate < 1:
            raise ValueError("false_positive_rate must be between 0 and 1")
        if self.expected_items <= 0:
            raise ValueError("expected_items must be positive")


@dataclass
class KVStoreConfig:
    """Configuration for the KV store."""

    # Memtable settings
    memtable_size_mb: int = 64
    memtable_skiplist_max_level: int = 16

    # WAL settings
    wal_sync_mode: str = "periodic"  # "always", "periodic", "os"
    wal_sync_interval_ms: int = 100
    wal_rotation_size_mb: int = 100

    # SSTable settings
    sstable_block_size_bytes: int = 4096

    # Compaction settings
    compaction_strategy: CompactionStrategy = CompactionStrategy.LEVELED
    compaction_level0_file_count_threshold: int = 4
    compaction_level_multiplier: int = 10

    # Bloom filter settings
    bloom_filter_config: BloomFilterConfig = field(default_factory=BloomFilterConfig)

    # Storage paths
    data_dir: str = "./data"

    def __post_init__(self):
        if self.memtable_size_mb <= 0:
            raise ValueError("memtable_size_mb must be positive")
        if self.memtable_skiplist_max_level < 1:
            raise ValueError("memtable_skiplist_max_level must be >= 1")
        if self.wal_sync_mode not in ("always", "periodic", "os"):
            raise ValueError("wal_sync_mode must be 'always', 'periodic', or 'os'")
        if self.sstable_block_size_bytes < 1024:
            raise ValueError("sstable_block_size_bytes must be >= 1024")
        if self.compaction_level0_file_count_threshold < 2:
            raise ValueError("compaction_level0_file_count_threshold must be >= 2")
        if self.compaction_level_multiplier < 2:
            raise ValueError("compaction_level_multiplier must be >= 2")
