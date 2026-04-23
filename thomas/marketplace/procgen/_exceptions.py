"""
Exceptions for procedural generation module.
"""


class ProcGenError(Exception):
    """Base exception for all procedural generation errors."""

    pass


class InvalidConfigError(ProcGenError):
    """Raised when configuration is invalid."""

    def __init__(self, message: str, config_key: str | None = None) -> None:
        """
        Initialize InvalidConfigError.

        Args:
            message: Error message describing the problem
            config_key: The configuration key that caused the error
        """
        self.config_key = config_key
        if config_key:
            full_message = f"Invalid config '{config_key}': {message}"
        else:
            full_message = f"Invalid config: {message}"
        super().__init__(full_message)


class GenerationError(ProcGenError):
    """Raised when generation process fails."""

    def __init__(self, message: str, step: str | None = None, seed: int | None = None) -> None:
        """
        Initialize GenerationError.

        Args:
            message: Error message describing what failed
            step: The generation step that failed
            seed: The random seed used (for debugging)
        """
        self.step = step
        self.seed = seed
        if step:
            full_message = f"Generation failed at '{step}': {message}"
        else:
            full_message = f"Generation failed: {message}"
        super().__init__(full_message)
