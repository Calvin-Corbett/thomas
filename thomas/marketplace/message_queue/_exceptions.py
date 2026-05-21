"""
Exception hierarchy for the message queue system.

All exceptions inherit from QueueError and provide specific error handling
for different failure scenarios in the message queue.
"""


class QueueError(Exception):
    """Base exception for all message queue errors."""

    pass


class TopicNotFoundError(QueueError):
    """Raised when attempting to access a topic that does not exist."""

    def __init__(self, topic: str) -> None:
        """
        Initialize TopicNotFoundError.

        Args:
            topic: Name of the missing topic
        """
        self.topic = topic
        super().__init__(f"Topic '{topic}' not found")


class TopicAlreadyExistsError(QueueError):
    """Raised when attempting to create a topic that already exists."""

    def __init__(self, topic: str) -> None:
        """
        Initialize TopicAlreadyExistsError.

        Args:
            topic: Name of the existing topic
        """
        self.topic = topic
        super().__init__(f"Topic '{topic}' already exists")


class ConsumerGroupError(QueueError):
    """Raised for consumer group-related errors."""

    def __init__(self, group: str, message: str) -> None:
        """
        Initialize ConsumerGroupError.

        Args:
            group: Consumer group name
            message: Error description
        """
        self.group = group
        super().__init__(f"Consumer group '{group}': {message}")


class BackpressureError(QueueError):
    """Raised when producer experiences backpressure and cannot buffer more messages."""

    def __init__(self, message: str = "Queue buffer full, backpressure applied") -> None:
        """
        Initialize BackpressureError.

        Args:
            message: Error description
        """
        super().__init__(message)


class DeadLetterError(QueueError):
    """Raised when a message is routed to the dead letter queue."""

    def __init__(self, topic: str, reason: str, max_retries: int) -> None:
        """
        Initialize DeadLetterError.

        Args:
            topic: Topic the message was sent to
            reason: Reason for DLQ routing
            max_retries: Maximum retry attempts configured
        """
        self.topic = topic
        self.reason = reason
        self.max_retries = max_retries
        super().__init__(f"Message routed to DLQ for topic '{topic}': {reason} (max retries: {max_retries})")


class SerializationError(QueueError):
    """Raised when message serialization or deserialization fails."""

    def __init__(self, message: str, original_error: Exception) -> None:
        """
        Initialize SerializationError.

        Args:
            message: Error description
            original_error: The underlying serialization exception
        """
        self.original_error = original_error
        super().__init__(f"{message}: {str(original_error)}")


class PartitionError(QueueError):
    """Raised for partition-related errors."""

    def __init__(self, partition: int, topic: str, message: str) -> None:
        """
        Initialize PartitionError.

        Args:
            partition: Partition number
            topic: Topic name
            message: Error description
        """
        self.partition = partition
        self.topic = topic
        super().__init__(f"Partition {partition} in topic '{topic}': {message}")


class OffsetError(QueueError):
    """Raised for offset-related errors."""

    def __init__(self, offset: int, message: str) -> None:
        """
        Initialize OffsetError.

        Args:
            offset: Invalid offset value
            message: Error description
        """
        self.offset = offset
        super().__init__(f"Offset {offset}: {message}")


class PersistenceError(QueueError):
    """Raised for disk persistence errors."""

    def __init__(self, message: str, original_error: Exception) -> None:
        """
        Initialize PersistenceError.

        Args:
            message: Error description
            original_error: The underlying IO exception
        """
        self.original_error = original_error
        super().__init__(f"{message}: {str(original_error)}")


class TimeoutError(QueueError):
    """Raised when an operation exceeds its timeout."""

    def __init__(self, operation: str, timeout_ms: int) -> None:
        """
        Initialize TimeoutError.

        Args:
            operation: Name of the timed-out operation
            timeout_ms: Timeout duration in milliseconds
        """
        self.operation = operation
        self.timeout_ms = timeout_ms
        super().__init__(f"Operation '{operation}' timed out after {timeout_ms}ms")
