"""
Regex engine exceptions.

Defines custom exceptions for the regex engine.
"""


class RegexError(Exception):
    """Base exception for all regex engine errors."""

    pass


class ParseError(RegexError):
    """Raised when regex pattern parsing fails."""

    def __init__(self, message: str, pattern: str = "", position: int = 0) -> None:
        """
        Initialize ParseError.

        Args:
            message: Error message
            pattern: The regex pattern being parsed
            position: Position in pattern where error occurred
        """
        self.message = message
        self.pattern = pattern
        self.position = position
        pointer = " " * position + "^"
        full_msg = f"{message}\n{pattern}\n{pointer}"
        super().__init__(full_msg)


class CompileError(RegexError):
    """Raised when regex compilation fails."""

    pass


class MatchError(RegexError):
    """Raised when pattern matching encounters an error."""

    pass
