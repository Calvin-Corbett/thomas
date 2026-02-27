"""Exception classes for the DataFrame library."""


class DataFrameError(Exception):
    """Base exception for DataFrame operations."""

    pass


class ColumnNotFoundError(DataFrameError):
    """Raised when a column does not exist."""

    def __init__(self, column: str, available_columns: list[str] | None = None) -> None:
        """Initialize the exception.

        Args:
            column: The column that was not found
            available_columns: List of available columns
        """
        msg = f"Column '{column}' not found"
        if available_columns:
            msg += f". Available columns: {available_columns}"
        super().__init__(msg)


class TypeMismatchError(DataFrameError):
    """Raised when data types do not match."""

    def __init__(self, expected: str, actual: str) -> None:
        """Initialize the exception.

        Args:
            expected: The expected type
            actual: The actual type
        """
        super().__init__(f"Type mismatch: expected {expected}, got {actual}")


class ShapeError(DataFrameError):
    """Raised when shapes do not match for an operation."""

    def __init__(self, shape1: tuple[int, ...], shape2: tuple[int, ...]) -> None:
        """Initialize the exception.

        Args:
            shape1: First shape
            shape2: Second shape
        """
        super().__init__(f"Shape mismatch: {shape1} vs {shape2}")


class MergeError(DataFrameError):
    """Raised when a merge/join operation fails."""

    def __init__(self, reason: str) -> None:
        """Initialize the exception.

        Args:
            reason: Reason for the merge failure
        """
        super().__init__(f"Merge failed: {reason}")
