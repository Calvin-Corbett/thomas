"""
Exception classes for the task queue system.

Defines custom exceptions used throughout the task queue module for error handling
and reporting.
"""


class TaskQueueException(Exception):
    """Base exception for all task queue errors."""

    pass


class TaskNotFoundError(TaskQueueException):
    """Raised when a task cannot be found in the queue."""

    def __init__(self, task_id: str) -> None:
        """
        Initialize TaskNotFoundError.

        Args:
            task_id: The ID of the task that was not found.
        """
        super().__init__(f"Task not found: {task_id}")
        self.task_id = task_id


class InvalidTaskError(TaskQueueException):
    """Raised when a task is invalid or malformed."""

    def __init__(self, message: str) -> None:
        """
        Initialize InvalidTaskError.

        Args:
            message: Description of what made the task invalid.
        """
        super().__init__(f"Invalid task: {message}")


class QueueFullError(TaskQueueException):
    """Raised when attempting to add a task to a full queue."""

    def __init__(self, queue_name: str, max_size: int) -> None:
        """
        Initialize QueueFullError.

        Args:
            queue_name: Name of the queue.
            max_size: Maximum size of the queue.
        """
        super().__init__(f"Queue '{queue_name}' is full (max: {max_size})")
        self.queue_name = queue_name
        self.max_size = max_size


class WorkerError(TaskQueueException):
    """Raised when a worker encounters an error."""

    def __init__(self, worker_id: str, message: str) -> None:
        """
        Initialize WorkerError.

        Args:
            worker_id: ID of the worker.
            message: Error message.
        """
        super().__init__(f"Worker {worker_id}: {message}")
        self.worker_id = worker_id


class SchedulerError(TaskQueueException):
    """Raised when scheduler encounters an error."""

    def __init__(self, message: str) -> None:
        """
        Initialize SchedulerError.

        Args:
            message: Error message.
        """
        super().__init__(f"Scheduler error: {message}")


class RetryExhaustedError(TaskQueueException):
    """Raised when a task has exhausted all retries."""

    def __init__(self, task_id: str, max_retries: int, last_error: str) -> None:
        """
        Initialize RetryExhaustedError.

        Args:
            task_id: ID of the task.
            max_retries: Maximum number of retries allowed.
            last_error: The last error that occurred.
        """
        super().__init__(f"Task {task_id} exhausted {max_retries} retries. Last error: {last_error}")
        self.task_id = task_id
        self.max_retries = max_retries
        self.last_error = last_error


class TaskTimeoutError(TaskQueueException):
    """Raised when a task exceeds its timeout."""

    def __init__(self, task_id: str, timeout: float) -> None:
        """
        Initialize TaskTimeoutError.

        Args:
            task_id: ID of the task.
            timeout: Timeout duration in seconds.
        """
        super().__init__(f"Task {task_id} exceeded timeout of {timeout} seconds")
        self.task_id = task_id
        self.timeout = timeout


class MiddlewareError(TaskQueueException):
    """Raised when middleware encounters an error."""

    def __init__(self, middleware_name: str, message: str) -> None:
        """
        Initialize MiddlewareError.

        Args:
            middleware_name: Name of the middleware.
            message: Error message.
        """
        super().__init__(f"Middleware {middleware_name}: {message}")
        self.middleware_name = middleware_name


class RateLimitExceededError(TaskQueueException):
    """Raised when rate limit is exceeded."""

    def __init__(self, resource: str, limit: int, window: float) -> None:
        """
        Initialize RateLimitExceededError.

        Args:
            resource: Name of the rate-limited resource.
            limit: Rate limit threshold.
            window: Time window in seconds.
        """
        super().__init__(f"Rate limit exceeded for {resource}: {limit} per {window}s")
        self.resource = resource
        self.limit = limit
        self.window = window


class WorkflowError(TaskQueueException):
    """Raised when a workflow encounters an error."""

    def __init__(self, workflow_id: str, message: str) -> None:
        """
        Initialize WorkflowError.

        Args:
            workflow_id: ID of the workflow.
            message: Error message.
        """
        super().__init__(f"Workflow {workflow_id}: {message}")
        self.workflow_id = workflow_id


class BatchError(TaskQueueException):
    """Raised when batch processing encounters an error."""

    def __init__(self, batch_id: str, message: str) -> None:
        """
        Initialize BatchError.

        Args:
            batch_id: ID of the batch.
            message: Error message.
        """
        super().__init__(f"Batch {batch_id}: {message}")
        self.batch_id = batch_id
