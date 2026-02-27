"""Exception classes for the visualization library."""


class VisualizationError(Exception):
    """Base exception for visualization errors."""

    pass


class InvalidScaleError(VisualizationError):
    """Raised when scale configuration is invalid."""

    def __init__(self, message: str) -> None:
        """Initialize InvalidScaleError.

        Args:
            message: Error message
        """
        super().__init__(f"Invalid scale: {message}")


class InvalidDataError(VisualizationError):
    """Raised when data is invalid or malformed."""

    def __init__(self, message: str) -> None:
        """Initialize InvalidDataError.

        Args:
            message: Error message
        """
        super().__init__(f"Invalid data: {message}")


class RenderError(VisualizationError):
    """Raised when rendering fails."""

    def __init__(self, message: str) -> None:
        """Initialize RenderError.

        Args:
            message: Error message
        """
        super().__init__(f"Render error: {message}")


class LayoutError(VisualizationError):
    """Raised when layout calculation fails."""

    def __init__(self, message: str) -> None:
        """Initialize LayoutError.

        Args:
            message: Error message
        """
        super().__init__(f"Layout error: {message}")


class InteractionError(VisualizationError):
    """Raised when interaction handling fails."""

    def __init__(self, message: str) -> None:
        """Initialize InteractionError.

        Args:
            message: Error message
        """
        super().__init__(f"Interaction error: {message}")
