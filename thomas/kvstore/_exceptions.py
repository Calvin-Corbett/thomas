"""Exception types for the KV store."""


class KVStoreError(Exception):
    """Base exception for KV store errors."""

    pass


class KeyNotFoundError(KVStoreError):
    """Raised when a key is not found."""

    pass


class CorruptionError(KVStoreError):
    """Raised when data corruption is detected."""

    pass


class WALError(KVStoreError):
    """Raised when a WAL operation fails."""

    pass


class CompactionError(KVStoreError):
    """Raised when compaction fails."""

    pass


class BloomFilterError(KVStoreError):
    """Raised when Bloom filter operation fails."""

    pass


class SSTableError(KVStoreError):
    """Raised when SSTable operation fails."""

    pass


class ManifestError(KVStoreError):
    """Raised when manifest operation fails."""

    pass
