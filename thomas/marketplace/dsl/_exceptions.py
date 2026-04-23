"""Custom exception types for DSL framework."""

from dataclasses import dataclass
from typing import Any


@dataclass
class SourceLocation:
    """Source code location for error reporting."""

    filename: str
    line: int
    column: int

    def __str__(self) -> str:
        """String representation of location."""
        return f"{self.filename}:{self.line}:{self.column}"


class DSLException(Exception):
    """Base exception for all DSL errors."""

    def __init__(self, message: str, location: SourceLocation | None = None) -> None:
        """Initialize DSL exception.

        Args:
            message: Error message
            location: Optional source location of error
        """
        self.message = message
        self.location = location
        full_msg = f"{location}: {message}" if location else message
        super().__init__(full_msg)


class LexerError(DSLException):
    """Raised when lexer encounters invalid input."""

    pass


class ParseError(DSLException):
    """Raised when parser encounters syntax errors."""

    pass


class TypeError(DSLException):
    """Raised for type system errors."""

    pass


class RuntimeError(DSLException):
    """Raised for runtime execution errors."""

    pass


class UndefinedVariable(RuntimeError):
    """Raised when accessing undefined variable."""

    def __init__(self, name: str, location: SourceLocation | None = None) -> None:
        """Initialize undefined variable error.

        Args:
            name: Variable name
            location: Optional source location
        """
        self.name = name
        super().__init__(f"Undefined variable: {name}", location)


class UndefinedFunction(RuntimeError):
    """Raised when calling undefined function."""

    def __init__(self, name: str, location: SourceLocation | None = None) -> None:
        """Initialize undefined function error.

        Args:
            name: Function name
            location: Optional source location
        """
        self.name = name
        super().__init__(f"Undefined function: {name}", location)


class UnificationError(TypeError):
    """Raised when type unification fails."""

    def __init__(self, type1: str, type2: str, location: SourceLocation | None = None) -> None:
        """Initialize unification error.

        Args:
            type1: First type
            type2: Second type
            location: Optional source location
        """
        super().__init__(f"Cannot unify {type1} with {type2}", location)


class ArityError(RuntimeError):
    """Raised when function called with wrong number of arguments."""

    def __init__(self, name: str, expected: int, got: int, location: SourceLocation | None = None) -> None:
        """Initialize arity error.

        Args:
            name: Function name
            expected: Expected number of arguments
            got: Actual number of arguments
            location: Optional source location
        """
        super().__init__(f"Function {name} expects {expected} arguments, got {got}", location)


class RecursionError(RuntimeError):
    """Raised when recursion limit exceeded."""

    def __init__(self, location: SourceLocation | None = None) -> None:
        """Initialize recursion error.

        Args:
            location: Optional source location
        """
        super().__init__("Maximum recursion depth exceeded", location)


class TimeoutError(RuntimeError):
    """Raised when execution exceeds time limit."""

    def __init__(self, location: SourceLocation | None = None) -> None:
        """Initialize timeout error.

        Args:
            location: Optional source location
        """
        super().__init__("Execution timeout", location)


class BreakException(Exception):
    """Control flow exception for break statements."""

    pass


class ContinueException(Exception):
    """Control flow exception for continue statements."""

    pass


class ReturnException(Exception):
    """Control flow exception for return statements."""

    def __init__(self, value: Any) -> None:
        """Initialize return exception.

        Args:
            value: Return value
        """
        self.value = value
        super().__init__()
