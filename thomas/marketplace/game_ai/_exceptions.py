"""
Exception types for game AI systems.

Provides custom exception classes for error handling across
different AI modules.
"""


class GameAIError(Exception):
    """Base exception for all game AI errors."""

    pass


class PathfindingError(GameAIError):
    """Exception raised during pathfinding operations.

    Raised when pathfinding fails, such as:
    - No path exists between points
    - Invalid start or goal positions
    - Corrupted navigation mesh
    """

    pass


class BehaviorTreeError(GameAIError):
    """Exception raised during behavior tree operations.

    Raised when:
    - Invalid tree structure
    - Missing required node
    - Recursive node definitions
    """

    pass
