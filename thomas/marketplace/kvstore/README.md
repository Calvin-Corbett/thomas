# Thomas KV Store - LSM-Tree Key-Value Store

A complete, production-quality implementation of a Log-Structured Merge (LSM) tree key-value store with durability, automatic compaction, and crash recovery.

## Quick Start

```python
from thomas.marketplace.kvstore import KVStore, KVStoreConfig

# Create and use store
config = KVStoreConfig(data_dir="/tmp/kvstore")
with KVStore(config) as store:
    store.put(b"key", b"value")
    value = store.get(b"key")
    store.delete(b"key")
    
    # Range scan
    for key, val in store.scan(start_key=b"a", end_key=b"z"):
        print(key, val)
```

## Features

- **Write-Ahead Log**: Crash-safe writes
- **Memtable**: Skip list-based in-memory buffer
- **SSTables**: Immutable sorted disk storage
- **Bloom Filters**: Fast negative lookups
- **Compaction**: Automatic background optimization
- **Range Queries**: Efficient key range scanning
- **Multiple Strategies**: Size-tiered and leveled compaction
- **Thread-Safe**: Safe concurrent reads

## Architecture

### Components

1. **Skip List** - Probabilistic O(log n) sorted storage
2. **Memtable** - In-memory buffer with auto-flush
3. **WAL** - Write-ahead log for durability
4. **Bloom Filter** - Probabilistic membership testing
5. **SSTable** - Immutable on-disk key-value storage
6. **Manifest** - Metadata tracking
7. **Compaction** - Background optimization
8. **Iterators** - Merge-based iteration
9. **KVStore** - Main orchestrator

### Data Flow

```
put(key, value)
    ↓
[Write to WAL] (durable)
    ↓
[Write to Memtable] (fast)
    ↓
[Check size] 
    ↓
[Flush to SSTable] (if needed)
    ↓
[Compact SSTables] (background)
```

## Configuration Options

```python
KVStoreConfig(
    # Memtable settings
    memtable_size_mb=64,
    memtable_skiplist_max_level=16,
    
    # WAL settings
    wal_sync_mode="periodic",  # always, periodic, os
    wal_sync_interval_ms=100,
    wal_rotation_size_mb=100,
    
    # SSTable settings
    sstable_block_size_bytes=4096,
    
    # Compaction settings
    compaction_strategy=CompactionStrategy.LEVELED,
    compaction_level0_file_count_threshold=4,
    compaction_level_multiplier=10,
    
    # Bloom filter settings
    bloom_filter_config=BloomFilterConfig(
        expected_items=10000,
        false_positive_rate=0.01
    ),
    
    # Storage
    data_dir="./data"
)
```

## API Reference

### Put
```python
store.put(key: bytes, value: bytes)
```
Inserts or updates a key-value pair. All writes are persisted to WAL before returning.

### Get
```python
value = store.get(key: bytes) -> bytes
```
Retrieves the value for a key. Raises `KeyNotFoundError` if not found.

### Delete
```python
store.delete(key: bytes)
```
Marks a key for deletion (tombstone). The key is immediately unavailable but cleanup happens during compaction.

### Contains
```python
exists = store.contains(key: bytes) -> bool
```
Checks if a key exists and is not deleted.

### Scan
```python
for key, value in store.scan(start_key=None, end_key=None):
    print(key, value)
```
Iterates over keys in range [start_key, end_key).

### Stats
```python
stats = store.stats()
```
Returns statistics including:
- `memtable_size_bytes`: Current memtable size
- `memtable_entries`: Number of entries
- `levels`: Per-level file counts and sizes
- `sequence`: Current sequence number
- `compaction_estimate_mb`: Work remaining

### Compact
```python
store.compact()
```
Triggers manual compaction of all levels.

### Close
```python
store.close()
```
Flushes memtable and closes all files. Can also use context manager.

## Testing

Run tests with pytest:
```bash
pytest tests/test_kvstore_*.py -v
```

Test coverage includes:
- Skip list operations (264 lines)
- Bloom filter functionality (174 lines)
- WAL write and recovery (276 lines)
- SSTable format and operations (280 lines)
- Full store integration (337 lines)
- Compaction logic (290 lines)

## Performance

**Write Path**: O(log n) memtable + O(1) WAL append
**Read Path**: O(log n) per SSTable level + Bloom filter fast-path
**Space**: Minimal overhead during compaction

## Files

- `_types.py` - Data types and configuration
- `_exceptions.py` - Exception hierarchy
- `skiplist.py` - Skip list data structure
- `memtable.py` - In-memory buffer
- `wal.py` - Write-ahead log
- `bloom_filter.py` - Bloom filter
- `sstable.py` - Sorted string table
- `iterators.py` - Merge iterators
- `manifest.py` - Metadata tracking
- `compaction.py` - Compaction engine
- `store.py` - Main KV store
- `__init__.py` - Public API

## Implementation Quality

- Full type annotations with Python 3.9+ syntax
- Comprehensive docstrings (Google style)
- Real algorithms with proper error handling
- Thread-safe operations with locks
- Atomic manifest updates
- CRC32 checksum validation
- Corruption detection

## Design Highlights

1. **Skip List vs B-Tree**: Skip lists provide simpler concurrent implementation with O(log n) operations
2. **Block-based SSTable**: Better sequential I/O and easier indexing
3. **Bloom Filters**: Reduce unnecessary disk I/O for missing keys
4. **Leveled Compaction**: Better write amplification than size-tiered approach
5. **Background Compaction**: Automatic optimization without blocking writes
6. **WAL First**: Durability guaranteed before in-memory updates
7. **Tombstones**: Efficient deferred deletion matching LSM design

## Limitations & Future Work

- No built-in compression
- No column families
- No range deletions
- No snapshots
- No backup utilities
- Single-threaded compaction

## License

Part of the Thomas project - "Everything Assistant"
