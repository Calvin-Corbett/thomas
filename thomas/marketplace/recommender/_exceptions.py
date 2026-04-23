"""
Custom exceptions for the recommender system.
"""


class RecommenderError(Exception):
    """Base exception for all recommender-related errors."""

    pass


class ColdStartError(RecommenderError):
    """Raised when insufficient data for making recommendations.

    This occurs when a user or item is new and lacks historical interaction data.
    """

    def __init__(self, entity_type: str, entity_id: str, message: str = "") -> None:
        """Initialize cold start error.

        Args:
            entity_type: Type of entity ("user" or "item").
            entity_id: ID of the entity with cold start problem.
            message: Additional error message.
        """
        self.entity_type = entity_type
        self.entity_id = entity_id
        default_msg = f"Cold start problem for {entity_type} '{entity_id}'"
        full_msg = f"{default_msg}: {message}" if message else default_msg
        super().__init__(full_msg)


class InsufficientDataError(RecommenderError):
    """Raised when there's insufficient data for training or prediction.

    This can occur when a user has too few ratings, or when the dataset is too sparse.
    """

    def __init__(self, minimum: int, actual: int, resource_type: str = "ratings") -> None:
        """Initialize insufficient data error.

        Args:
            minimum: Minimum data points required.
            actual: Actual data points available.
            resource_type: Type of resource (e.g., "ratings", "interactions").
        """
        self.minimum = minimum
        self.actual = actual
        msg = f"Insufficient {resource_type}: need {minimum}, got {actual}"
        super().__init__(msg)
