"""
Exceptions for the load balancer module.
"""


class LoadBalancerError(Exception):
    """Base exception for load balancer errors."""

    pass


class NoHealthyBackendError(LoadBalancerError):
    """
    Raised when no healthy backends are available.

    This exception is raised when attempting to route a request but all
    backends are either unhealthy or at capacity.
    """

    def __init__(self, message: str = "No healthy backends available") -> None:
        """
        Initialize the exception.

        Args:
            message: Error message describing why no healthy backends are available.
        """
        super().__init__(message)


class BackendError(LoadBalancerError):
    """
    Raised when a backend encounters an error.

    This exception is raised when communicating with a backend fails,
    such as connection refused or timeout.
    """

    def __init__(self, backend_id: str, message: str) -> None:
        """
        Initialize the exception.

        Args:
            backend_id: ID of the backend that failed.
            message: Error message describing what went wrong.
        """
        self.backend_id = backend_id
        super().__init__(f"Backend {backend_id} error: {message}")


class CircuitOpenError(LoadBalancerError):
    """
    Raised when a circuit breaker is open.

    This exception is raised when attempting to route to a backend
    whose circuit breaker is in the OPEN state.
    """

    def __init__(self, backend_id: str, reset_time: float) -> None:
        """
        Initialize the exception.

        Args:
            backend_id: ID of the backend with open circuit.
            reset_time: Unix timestamp when the circuit will attempt recovery.
        """
        self.backend_id = backend_id
        self.reset_time = reset_time
        super().__init__(f"Circuit breaker open for backend {backend_id}, will retry at {reset_time}")
