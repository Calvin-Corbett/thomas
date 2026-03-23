"""
Exception classes for graph analytics module.

Defines custom exceptions for error handling in graph operations.
"""


class GraphAnalyticsError(Exception):
    """
    Base exception for graph analytics operations.

    Raised when a general graph operation fails.
    """

    pass


class GraphNotConnectedError(GraphAnalyticsError):
    """
    Exception raised when a graph operation requires connectivity.

    Raised when attempting an operation that requires the graph
    (or a subgraph) to be connected but it is not.
    """

    def __init__(self, message: str = "Graph is not connected") -> None:
        """
        Initialize exception.

        Args:
            message: Error message describing the issue.
        """
        super().__init__(message)


class NegativeCycleError(GraphAnalyticsError):
    """
    Exception raised when a negative cycle is detected.

    Raised when attempting shortest path computation in a graph
    with negative-weight edges that form a cycle.
    """

    def __init__(self, message: str = "Negative cycle detected") -> None:
        """
        Initialize exception.

        Args:
            message: Error message describing the negative cycle.
        """
        super().__init__(message)


class InvalidGraphError(GraphAnalyticsError):
    """
    Exception raised for invalid graph structure or operations.

    Raised when graph operations violate constraints or invariants.
    """

    pass


class NoPathError(GraphAnalyticsError):
    """
    Exception raised when no path exists between nodes.

    Raised when attempting to find a path between nodes that are
    not connected.
    """

    pass


class CycleDetectedError(GraphAnalyticsError):
    """
    Exception raised when a cycle is detected in a DAG operation.

    Raised when attempting topological sort or other DAG operations
    on a graph with cycles.
    """

    pass
