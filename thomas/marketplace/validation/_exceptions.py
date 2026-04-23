"""
Validation-specific exceptions.
"""


class ValidationException(Exception):
    """Base exception for validation errors."""

    def __init__(self, message: str, errors: list | None = None) -> None:
        """Initialize validation exception.

        Args:
            message: Error message.
            errors: List of ValidationError objects.
        """
        super().__init__(message)
        self.message = message
        self.errors = errors or []

    def __str__(self) -> str:
        """String representation."""
        if self.errors:
            error_str = "\n  ".join(str(e) for e in self.errors[:5])
            suffix = f"\n  ... and {len(self.errors) - 5} more" if len(self.errors) > 5 else ""
            return f"{self.message}\n  {error_str}{suffix}"
        return self.message


class SchemaError(ValidationException):
    """Raised when schema definition is invalid."""

    pass


class RuleError(ValidationException):
    """Raised when a validation rule is malformed."""

    pass


class CircularReferenceError(ValidationException):
    """Raised when a circular schema reference is detected."""

    def __init__(self, ref_chain: list[str]) -> None:
        """Initialize circular reference error.

        Args:
            ref_chain: List of schema references forming the cycle.
        """
        chain_str = " -> ".join(ref_chain)
        message = f"Circular schema reference detected: {chain_str}"
        super().__init__(message)
        self.ref_chain = ref_chain
