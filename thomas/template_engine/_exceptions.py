"""Custom exceptions for the template engine."""


class TemplateError(Exception):
    """Base exception for all template engine errors."""

    def __init__(self, message: str, lineno: int | None = None, name: str | None = None) -> None:
        """
        Initialize a template error.

        Args:
            message: Error message
            lineno: Line number where error occurred
            name: Template name
        """
        self.message = message
        self.lineno = lineno
        self.name = name
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format error message with location info."""
        parts = []
        if self.name:
            parts.append(f"in template '{self.name}'")
        if self.lineno is not None:
            parts.append(f"on line {self.lineno}")
        location = ", ".join(parts)
        if location:
            return f"{self.message} ({location})"
        return self.message


class TemplateSyntaxError(TemplateError):
    """Raised when template has invalid syntax."""

    pass


class TemplateRuntimeError(TemplateError):
    """Raised during template rendering."""

    pass


class UndefinedError(TemplateRuntimeError):
    """Raised when accessing undefined variable in strict mode."""

    pass


class FilterNotFoundError(TemplateRuntimeError):
    """Raised when filter is not found."""

    pass


class TestNotFoundError(TemplateRuntimeError):
    """Raised when test function is not found."""

    pass


class LoopContextError(TemplateRuntimeError):
    """Raised when accessing loop context outside of loop."""

    pass


class InheritanceError(TemplateSyntaxError):
    """Raised for block inheritance errors."""

    pass


class MacroError(TemplateRuntimeError):
    """Raised when macro call fails."""

    pass


class CircularIncludeError(TemplateRuntimeError):
    """Raised for circular template includes."""

    pass
