"""
Exception classes for Markdown parsing and rendering.
"""


class MarkdownError(Exception):
    """Base exception for Markdown processing errors."""

    def __init__(self, message: str, line: int = 0, column: int = 0) -> None:
        """Initialize exception with message and position.

        Args:
            message: Error description
            line: Line number where error occurred (1-indexed)
            column: Column number where error occurred (0-indexed)
        """
        self.message = message
        self.line = line
        self.column = column
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format error message with position information."""
        if self.line > 0:
            return f"{self.message} (line {self.line}, col {self.column})"
        return self.message

    def __repr__(self) -> str:
        """Return string representation."""
        return f"{self.__class__.__name__}({repr(self.message)})"


class ParseError(MarkdownError):
    """Error during Markdown parsing.

    Raised when the parser encounters invalid syntax or unexpected input.
    """

    pass


class RenderError(MarkdownError):
    """Error during rendering to HTML or text.

    Raised when an error occurs while converting AST to output format.
    """

    pass
