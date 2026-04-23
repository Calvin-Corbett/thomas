"""
Exception classes for the scheduler system.

Defines all custom exceptions used throughout the scheduler.
"""


class SchedulerException(Exception):
    """Base exception for all scheduler errors."""

    pass


class JobNotFound(SchedulerException):
    """Raised when a job cannot be found."""

    def __init__(self, job_id: str) -> None:
        """Initialize exception.

        Args:
            job_id: ID of the job that was not found
        """
        super().__init__(f"Job not found: {job_id}")
        self.job_id = job_id


class JobAlreadyExists(SchedulerException):
    """Raised when attempting to add a job with duplicate ID."""

    def __init__(self, job_id: str) -> None:
        """Initialize exception.

        Args:
            job_id: ID of the duplicate job
        """
        super().__init__(f"Job already exists: {job_id}")
        self.job_id = job_id


class InvalidTrigger(SchedulerException):
    """Raised when a trigger is invalid."""

    def __init__(self, message: str) -> None:
        """Initialize exception.

        Args:
            message: Description of the validation error
        """
        super().__init__(f"Invalid trigger: {message}")


class InvalidCronExpression(SchedulerException):
    """Raised when a cron expression is invalid."""

    def __init__(self, expression: str, reason: str) -> None:
        """Initialize exception.

        Args:
            expression: The invalid cron expression
            reason: Explanation of why it's invalid
        """
        super().__init__(f"Invalid cron expression '{expression}': {reason}")
        self.expression = expression
        self.reason = reason


class JobExecutionError(SchedulerException):
    """Raised when a job execution fails."""

    def __init__(self, job_id: str, message: str, original_error: Exception) -> None:
        """Initialize exception.

        Args:
            job_id: ID of the job that failed
            message: Error description
            original_error: The underlying exception
        """
        super().__init__(f"Job {job_id} failed: {message}")
        self.job_id = job_id
        self.original_error = original_error


class JobTimeout(SchedulerException):
    """Raised when a job execution times out."""

    def __init__(self, job_id: str, timeout_seconds: int) -> None:
        """Initialize exception.

        Args:
            job_id: ID of the job that timed out
            timeout_seconds: Configured timeout duration
        """
        super().__init__(f"Job {job_id} timed out after {timeout_seconds} seconds")
        self.job_id = job_id
        self.timeout_seconds = timeout_seconds


class CycleDetected(SchedulerException):
    """Raised when a cycle is detected in job dependencies."""

    def __init__(self, cycle_path: list[str]) -> None:
        """Initialize exception.

        Args:
            cycle_path: List of job IDs forming the cycle
        """
        super().__init__(f"Cycle detected in job dependencies: {' -> '.join(cycle_path)}")
        self.cycle_path = cycle_path


class InvalidDAG(SchedulerException):
    """Raised when DAG structure is invalid."""

    def __init__(self, message: str) -> None:
        """Initialize exception.

        Args:
            message: Description of the validation error
        """
        super().__init__(f"Invalid DAG: {message}")


class PersistenceError(SchedulerException):
    """Raised when persistence operations fail."""

    def __init__(self, operation: str, message: str) -> None:
        """Initialize exception.

        Args:
            operation: The persistence operation that failed
            message: Error description
        """
        super().__init__(f"Persistence error during {operation}: {message}")
        self.operation = operation


class DistributedSchedulingError(SchedulerException):
    """Raised when distributed scheduling fails."""

    def __init__(self, message: str) -> None:
        """Initialize exception.

        Args:
            message: Error description
        """
        super().__init__(f"Distributed scheduling error: {message}")


class LeaderElectionFailed(SchedulerException):
    """Raised when leader election fails."""

    def __init__(self, message: str) -> None:
        """Initialize exception.

        Args:
            message: Error description
        """
        super().__init__(f"Leader election failed: {message}")


class RateLimitExceeded(SchedulerException):
    """Raised when rate limits are exceeded."""

    def __init__(self, job_id: str, limit_type: str) -> None:
        """Initialize exception.

        Args:
            job_id: ID of the job that hit the limit
            limit_type: Type of limit (e.g., 'concurrent', 'throughput')
        """
        super().__init__(f"Job {job_id} exceeded {limit_type} rate limit")
        self.job_id = job_id
        self.limit_type = limit_type
