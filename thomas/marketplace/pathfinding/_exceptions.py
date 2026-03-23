"""
Custom exceptions for the pathfinding module.
"""


class PathfindingException(Exception):
    """
    Base exception for all pathfinding-related errors.

    This is the parent class for all custom exceptions in the pathfinding module.
    """

    pass


class NoPathFoundError(PathfindingException):
    """
    Raised when no path exists between start and goal nodes.

    This exception indicates that the search algorithm explored all reachable nodes
    but never reached the goal, meaning no path exists (either the goal is unreachable
    or it lies in a disconnected component of the graph).
    """

    def __init__(self, start: str, goal: str) -> None:
        """
        Initialize the exception.

        Args:
            start: Start node identifier.
            goal: Goal node identifier.
        """
        super().__init__(f"No path found from {start} to {goal}")
        self.start = start
        self.goal = goal


class InvalidGraphError(PathfindingException):
    """
    Raised when the graph structure is invalid for the operation.

    This exception indicates that the graph configuration doesn't meet the requirements
    of the operation, such as missing nodes, disconnected components, or negative cycles
    in algorithms that don't support them.
    """

    def __init__(self, message: str) -> None:
        """
        Initialize the exception.

        Args:
            message: Description of what makes the graph invalid.
        """
        super().__init__(f"Invalid graph: {message}")
        self.message = message


class InvalidPositionError(PathfindingException):
    """
    Raised when a position is invalid for grid or mesh pathfinding.

    This exception indicates that a position is outside the valid bounds of a grid,
    not on a navigation mesh, or otherwise inaccessible for pathfinding operations.
    """

    def __init__(self, x: float, y: float, context: str = "") -> None:
        """
        Initialize the exception.

        Args:
            x: X coordinate of the invalid position.
            y: Y coordinate of the invalid position.
            context: Additional context about why position is invalid.
        """
        message = f"Invalid position ({x}, {y})"
        if context:
            message += f": {context}"
        super().__init__(message)
        self.x = x
        self.y = y
        self.context = context


class InfiniteLoopError(PathfindingException):
    """
    Raised when an algorithm detects an infinite loop or unbounded search.

    This exception is raised when an iterative algorithm exceeds a maximum iteration
    count or when circular dependencies are detected in the search process.
    """

    def __init__(self, max_iterations: int) -> None:
        """
        Initialize the exception.

        Args:
            max_iterations: Maximum iterations that were exceeded.
        """
        super().__init__(f"Algorithm exceeded maximum iterations: {max_iterations}")
        self.max_iterations = max_iterations
