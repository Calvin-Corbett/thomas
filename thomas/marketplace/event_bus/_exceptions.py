"""
Exception definitions for the event bus system.

Provides domain-specific exceptions for error handling and reporting.
"""


class EventBusError(Exception):
    """Base exception for all event bus errors."""

    pass


class HandlerError(EventBusError):
    """Raised when an event handler fails to process an event."""

    def __init__(
        self,
        handler_id: str,
        event_id: str,
        original_error: Exception,
    ) -> None:
        self.handler_id = handler_id
        self.event_id = event_id
        self.original_error = original_error
        super().__init__(f"Handler {handler_id} failed on event {event_id}: {original_error}")


class EventStoreError(EventBusError):
    """Raised when event store operations fail."""

    pass


class ConcurrencyError(EventStoreError):
    """Raised when optimistic concurrency check fails."""

    def __init__(self, stream_name: str, expected_version: int, actual_version: int):
        self.stream_name = stream_name
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Concurrency error in stream {stream_name}: "
            f"expected version {expected_version}, "
            f"but actual version is {actual_version}"
        )


class ReplayError(EventBusError):
    """Raised when event replay fails."""

    def __init__(self, stream_name: str, position: int, original_error: Exception):
        self.stream_name = stream_name
        self.position = position
        self.original_error = original_error
        super().__init__(f"Replay failed in stream {stream_name} at position {position}: {original_error}")


class SubscriptionError(EventBusError):
    """Raised for subscription-related errors."""

    pass
