"""Exception types for the Thomas time-series database."""


class TSDBError(Exception):
    """Base exception for all TSDB errors."""

    pass


class MetricNotFoundError(TSDBError):
    """Raised when a requested metric does not exist.

    Attributes:
        metric_name: Name of the metric that was not found
    """

    def __init__(self, metric_name: str) -> None:
        """Initialize the exception.

        Args:
            metric_name: Name of the missing metric
        """
        self.metric_name = metric_name
        super().__init__(f"Metric not found: {metric_name}")


class RetentionError(TSDBError):
    """Raised when retention policy enforcement fails.

    Attributes:
        policy_name: Name of the policy that failed
        reason: Reason for the failure
    """

    def __init__(self, policy_name: str, reason: str) -> None:
        """Initialize the exception.

        Args:
            policy_name: Name of the policy
            reason: Detailed reason for the error
        """
        self.policy_name = policy_name
        self.reason = reason
        super().__init__(f"Retention error in {policy_name}: {reason}")


class QueryError(TSDBError):
    """Raised when query execution fails.

    Attributes:
        query: The query that failed
        reason: Reason for the failure
    """

    def __init__(self, query: str, reason: str) -> None:
        """Initialize the exception.

        Args:
            query: The query string that failed
            reason: Detailed reason for the error
        """
        self.query = query
        self.reason = reason
        super().__init__(f"Query error: {reason} (query: {query})")


class StorageError(TSDBError):
    """Raised when storage operations fail.

    Attributes:
        operation: The operation that failed
        reason: Reason for the failure
    """

    def __init__(self, operation: str, reason: str) -> None:
        """Initialize the exception.

        Args:
            operation: Description of the operation
            reason: Detailed reason for the error
        """
        self.operation = operation
        self.reason = reason
        super().__init__(f"Storage error during {operation}: {reason}")
