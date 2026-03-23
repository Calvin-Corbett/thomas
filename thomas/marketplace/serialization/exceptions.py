"""
Exception classes for the serialization module.

Provides specific exception types for various serialization errors including
codec not found, deserialization failures, schema version issues, and
incompatible schema evolutions.
"""


class SerializationError(Exception):
    """Base exception for serialization errors."""

    pass


class DeserializationError(SerializationError):
    """Raised when deserialization fails."""

    def __init__(
        self,
        message: str,
        data: bytes | None = None,
        position: int | None = None,
    ) -> None:
        """Initialize deserialization error.

        Args:
            message: Error description.
            data: Raw data that failed to deserialize.
            position: Byte position where error occurred.
        """
        super().__init__(message)
        self.data = data
        self.position = position

    def __str__(self) -> str:
        result = super().__str__()
        if self.position is not None:
            result += f" at byte position {self.position}"
        return result


class SchemaVersionError(SerializationError):
    """Raised when schema version is incompatible."""

    def __init__(
        self,
        message: str,
        expected_version: int | None = None,
        actual_version: int | None = None,
    ) -> None:
        """Initialize schema version error.

        Args:
            message: Error description.
            expected_version: Expected schema version.
            actual_version: Actual schema version encountered.
        """
        super().__init__(message)
        self.expected_version = expected_version
        self.actual_version = actual_version


class CodecNotFoundError(SerializationError):
    """Raised when a codec for a format is not registered."""

    def __init__(self, format_name: str) -> None:
        """Initialize codec not found error.

        Args:
            format_name: The format that has no registered codec.
        """
        super().__init__(f"No codec registered for format: {format_name}")
        self.format_name = format_name


class IncompatibleSchemaError(SerializationError):
    """Raised when schema evolution is not possible."""

    def __init__(
        self,
        message: str,
        old_version: str | None = None,
        new_version: str | None = None,
    ) -> None:
        """Initialize incompatible schema error.

        Args:
            message: Error description.
            old_version: Old schema version string.
            new_version: New schema version string.
        """
        super().__init__(message)
        self.old_version = old_version
        self.new_version = new_version
