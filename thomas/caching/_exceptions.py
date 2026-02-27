"""Exception types for the caching module."""


class CacheError(Exception):
    """Base exception for all cache-related errors."""

    pass


class CacheMissError(CacheError):
    """Raised when a cache lookup misses and strict mode is enabled."""

    def __init__(self, key: str) -> None:
        """Initialize the exception.

        Args:
            key: The cache key that was not found.
        """
        super().__init__(f"Cache miss for key: {key}")
        self.key = key


class CacheFullError(CacheError):
    """Raised when cache is full and cannot accommodate a new entry."""

    def __init__(self, message: str = "Cache is full") -> None:
        """Initialize the exception.

        Args:
            message: Detailed error message.
        """
        super().__init__(message)


class SerializationError(CacheError):
    """Raised when serialization or deserialization fails."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        """Initialize the exception.

        Args:
            message: Detailed error message.
            original_error: The underlying exception that caused this error.
        """
        super().__init__(message)
        self.original_error = original_error


class CacheCorruptionError(CacheError):
    """Raised when cache data appears corrupted or invalid."""

    def __init__(self, message: str) -> None:
        """Initialize the exception.

        Args:
            message: Description of the corruption detected.
        """
        super().__init__(message)


class CacheExpirationError(CacheError):
    """Raised when an entry has expired."""

    def __init__(self, key: str) -> None:
        """Initialize the exception.

        Args:
            key: The expired cache key.
        """
        super().__init__(f"Cache entry expired: {key}")
        self.key = key


class EvictionError(CacheError):
    """Raised when forced eviction fails."""

    def __init__(self, message: str = "Eviction failed") -> None:
        """Initialize the exception.

        Args:
            message: Description of the eviction failure.
        """
        super().__init__(message)
