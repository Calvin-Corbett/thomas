"""
Custom exception types for the columnar storage engine.
"""


class ColumnarException(Exception):
    """Base exception for all columnar engine errors."""

    pass


class ColumnTypeError(ColumnarException):
    """Exception raised for type-related errors."""

    def __init__(self, message: str) -> None:
        """Initialize ColumnTypeError."""
        super().__init__(f"Type error: {message}")


class CompressionError(ColumnarException):
    """Exception raised for compression/decompression failures."""

    def __init__(self, message: str) -> None:
        """Initialize CompressionError."""
        super().__init__(f"Compression error: {message}")


class EncodingError(ColumnarException):
    """Exception raised for encoding/decoding failures."""

    def __init__(self, message: str) -> None:
        """Initialize EncodingError."""
        super().__init__(f"Encoding error: {message}")


class StorageError(ColumnarException):
    """Exception raised for storage layer errors."""

    def __init__(self, message: str) -> None:
        """Initialize StorageError."""
        super().__init__(f"Storage error: {message}")


class QueryError(ColumnarException):
    """Exception raised for query execution errors."""

    def __init__(self, message: str) -> None:
        """Initialize QueryError."""
        super().__init__(f"Query error: {message}")


class IndexError(ColumnarException):
    """Exception raised for index-related errors."""

    def __init__(self, message: str) -> None:
        """Initialize IndexError."""
        super().__init__(f"Index error: {message}")


class SchemaError(ColumnarException):
    """Exception raised for schema validation errors."""

    def __init__(self, message: str) -> None:
        """Initialize SchemaError."""
        super().__init__(f"Schema error: {message}")


class PartitionError(ColumnarException):
    """Exception raised for partitioning errors."""

    def __init__(self, message: str) -> None:
        """Initialize PartitionError."""
        super().__init__(f"Partition error: {message}")


class IOError(ColumnarException):
    """Exception raised for I/O operation errors."""

    def __init__(self, message: str) -> None:
        """Initialize IOError."""
        super().__init__(f"I/O error: {message}")
