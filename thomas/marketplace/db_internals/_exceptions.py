"""
Custom exception types for the database engine.

This module defines all exception classes used throughout the database system
for error handling, validation, and constraint violations.
"""


class DatabaseException(Exception):
    """Base exception class for all database errors."""

    def __init__(self, message: str, error_code: int = 0) -> None:
        """Initialize exception with message and error code."""
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class StorageException(DatabaseException):
    """Raised when storage engine encounters an error."""

    pass


class BufferPoolException(DatabaseException):
    """Raised when buffer pool operations fail."""

    pass


class PageException(DatabaseException):
    """Raised for page-related errors."""

    pass


class TransactionException(DatabaseException):
    """Raised for transaction-related errors."""

    pass


class LockException(DatabaseException):
    """Raised when lock acquisition or lock manager fails."""

    pass


class DeadlockException(LockException):
    """Raised when a deadlock is detected."""

    pass


class LockTimeoutException(LockException):
    """Raised when lock acquisition times out."""

    pass


class ConstraintViolationException(DatabaseException):
    """Raised when a constraint violation occurs."""

    pass


class PrimaryKeyViolationException(ConstraintViolationException):
    """Raised when PRIMARY KEY constraint is violated."""

    pass


class UniqueConstraintViolationException(ConstraintViolationException):
    """Raised when UNIQUE constraint is violated."""

    pass


class ForeignKeyViolationException(ConstraintViolationException):
    """Raised when FOREIGN KEY constraint is violated."""

    pass


class NotNullViolationException(ConstraintViolationException):
    """Raised when NOT NULL constraint is violated."""

    pass


class CheckConstraintViolationException(ConstraintViolationException):
    """Raised when CHECK constraint is violated."""

    pass


class SchemaException(DatabaseException):
    """Raised for schema/catalog-related errors."""

    pass


class TableNotFoundException(SchemaException):
    """Raised when a referenced table is not found."""

    pass


class ColumnNotFoundException(SchemaException):
    """Raised when a referenced column is not found."""

    pass


class IndexNotFoundException(SchemaException):
    """Raised when a referenced index is not found."""

    pass


class DuplicateTableException(SchemaException):
    """Raised when attempting to create a table that already exists."""

    pass


class DuplicateIndexException(SchemaException):
    """Raised when attempting to create an index that already exists."""

    pass


class InvalidSchemaException(SchemaException):
    """Raised for invalid schema definition."""

    pass


class ParseException(DatabaseException):
    """Raised when SQL parsing fails."""

    pass


class SyntaxException(ParseException):
    """Raised for SQL syntax errors."""

    pass


class InvalidDataTypeException(ParseException):
    """Raised for invalid data type specification."""

    pass


class OptimizerException(DatabaseException):
    """Raised when query optimization fails."""

    pass


class ExecutorException(DatabaseException):
    """Raised during query execution."""

    pass


class TypeMismatchException(ExecutorException):
    """Raised when operand types don't match operation."""

    pass


class DivisionByZeroException(ExecutorException):
    """Raised when division by zero is encountered."""

    pass


class WALException(DatabaseException):
    """Raised for write-ahead log errors."""

    pass


class CheckpointException(WALException):
    """Raised when checkpoint fails."""

    pass


class RecoveryException(WALException):
    """Raised during crash recovery."""

    pass


class IndexException(DatabaseException):
    """Raised for B+ tree index errors."""

    pass


class TreeException(IndexException):
    """Raised for B+ tree structure errors."""

    pass


class KeyNotFoundException(IndexException):
    """Raised when a key is not found in the index."""

    pass


class DuplicateKeyException(IndexException):
    """Raised when attempting to insert a duplicate key in a unique index."""

    pass


class IOException(DatabaseException):
    """Raised for I/O operation failures."""

    pass


class DiskException(IOException):
    """Raised for disk-related errors."""

    pass


class DataCorruptionException(DatabaseException):
    """Raised when data corruption is detected."""

    pass


class VersionMismatchException(DatabaseException):
    """Raised when database version is not compatible."""

    pass


class CatalogException(DatabaseException):
    """Raised for catalog/metadata errors."""

    pass


class StatisticsException(DatabaseException):
    """Raised when statistics gathering fails."""

    pass


class ConfigurationException(DatabaseException):
    """Raised for configuration errors."""

    pass


class NotImplementedException(DatabaseException):
    """Raised when a feature is not yet implemented."""

    pass


class InvalidOperationException(DatabaseException):
    """Raised for invalid database operations."""

    pass


class StateException(DatabaseException):
    """Raised when an operation is invalid for current state."""

    pass


class ResourceExhaustedException(DatabaseException):
    """Raised when a resource limit is reached."""

    pass


class MemoryException(ResourceExhaustedException):
    """Raised when memory allocation fails."""

    pass


class DiskFullException(ResourceExhaustedException):
    """Raised when disk is full."""

    pass
