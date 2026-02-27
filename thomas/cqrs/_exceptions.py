"""
Custom exceptions for CQRS pattern implementation.

Provides specific exception types for various error scenarios
in command processing, query execution, and event sourcing.
"""


class CQRSException(Exception):
    """Base exception for all CQRS-related errors."""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        """
        Initialize CQRS exception.

        Args:
            message: Error message
            error_code: Optional error code for categorization
        """
        self.message = message
        self.error_code = error_code or "UNKNOWN_ERROR"
        super().__init__(message)


class CommandExecutionException(CQRSException):
    """Raised when command execution fails."""

    pass


class CommandValidationException(CQRSException):
    """Raised when command validation fails."""

    pass


class CommandTimeoutException(CQRSException):
    """Raised when command execution times out."""

    pass


class QueryExecutionException(CQRSException):
    """Raised when query execution fails."""

    pass


class QueryTimeoutException(CQRSException):
    """Raised when query execution times out."""

    pass


class AggregateNotFoundException(CQRSException):
    """Raised when an aggregate cannot be found."""

    def __init__(self, aggregate_id: str, aggregate_type: str) -> None:
        """
        Initialize exception with aggregate details.

        Args:
            aggregate_id: ID of missing aggregate
            aggregate_type: Type of aggregate
        """
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        super().__init__(f"Aggregate {aggregate_type}({aggregate_id}) not found", error_code="AGGREGATE_NOT_FOUND")


class ConcurrencyException(CQRSException):
    """Raised when optimistic concurrency check fails."""

    def __init__(self, aggregate_id: str, expected_version: int, actual_version: int) -> None:
        """
        Initialize concurrency exception.

        Args:
            aggregate_id: ID of conflicting aggregate
            expected_version: Expected version
            actual_version: Actual version
        """
        self.aggregate_id = aggregate_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Concurrency conflict on {aggregate_id}: " f"expected {expected_version}, got {actual_version}",
            error_code="CONCURRENCY_CONFLICT",
        )


class EventStoreException(CQRSException):
    """Raised for event store operation failures."""

    pass


class SnapshotException(CQRSException):
    """Raised for snapshot-related failures."""

    pass


class ProjectionException(CQRSException):
    """Raised when projection rebuild or update fails."""

    pass


class SagaException(CQRSException):
    """Raised for saga-related failures."""

    pass


class SagaTimeoutException(CQRSException):
    """Raised when saga execution times out."""

    pass


class SagaCompensationException(CQRSException):
    """Raised when saga compensation step fails."""

    pass


class MiddlewareException(CQRSException):
    """Raised for middleware-related failures."""

    pass


class SerializationException(CQRSException):
    """Raised for event serialization/deserialization failures."""

    pass


class DeserializationException(CQRSException):
    """Raised for event deserialization failures."""

    pass


class DuplicateCommandException(CQRSException):
    """Raised when duplicate command is detected."""

    def __init__(self, command_id: str) -> None:
        """
        Initialize duplicate command exception.

        Args:
            command_id: ID of duplicate command
        """
        self.command_id = command_id
        super().__init__(f"Duplicate command: {command_id}", error_code="DUPLICATE_COMMAND")


class ReadModelException(CQRSException):
    """Raised for read model operation failures."""

    pass


class ProcessManagerException(CQRSException):
    """Raised for process manager failures."""

    pass


class InvalidEventTypeException(CQRSException):
    """Raised when event type is not registered."""

    def __init__(self, event_type: str) -> None:
        """
        Initialize invalid event type exception.

        Args:
            event_type: The unregistered event type
        """
        self.event_type = event_type
        super().__init__(f"Event type not registered: {event_type}", error_code="INVALID_EVENT_TYPE")


class UpcastingException(CQRSException):
    """Raised when event upcasting fails."""

    pass
