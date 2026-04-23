"""Compiler exceptions with location information."""

from __future__ import annotations

from dataclasses import dataclass

from ._types import SourceLocation


@dataclass
class CompilerError(Exception):
    """Base compiler error."""

    message: str
    location: SourceLocation | None = None

    def __str__(self) -> str:
        if self.location:
            return f"{self.location}: {self.message}"
        return self.message


@dataclass
class LexError(CompilerError):
    """Lexical analysis error."""

    message: str
    location: SourceLocation

    def __str__(self) -> str:
        return f"Lexical error at {self.location}: {self.message}"


@dataclass
class ParseError(CompilerError):
    """Parser error."""

    message: str
    location: SourceLocation

    def __str__(self) -> str:
        return f"Parse error at {self.location}: {self.message}"


@dataclass
class TypeError(CompilerError):
    """Type checking error."""

    message: str
    location: SourceLocation

    def __str__(self) -> str:
        return f"Type error at {self.location}: {self.message}"


@dataclass
class CodegenError(CompilerError):
    """Code generation error."""

    message: str
    location: SourceLocation | None = None

    def __str__(self) -> str:
        if self.location:
            return f"Codegen error at {self.location}: {self.message}"
        return f"Codegen error: {self.message}"


@dataclass
class RuntimeError(CompilerError):
    """Runtime error in the VM."""

    message: str
    location: SourceLocation | None = None

    def __str__(self) -> str:
        if self.location:
            return f"Runtime error at {self.location}: {self.message}"
        return f"Runtime error: {self.message}"


class CompilerErrorCollector:
    """Collects multiple errors without stopping compilation."""

    def __init__(self) -> None:
        self.errors: list[CompilerError] = []

    def add(self, error: CompilerError) -> None:
        """Add an error."""
        self.errors.append(error)

    def has_errors(self) -> bool:
        """Check if any errors were collected."""
        return len(self.errors) > 0

    def raise_if_errors(self) -> None:
        """Raise an exception if errors were collected."""
        if self.has_errors():
            msg = "\n".join(str(e) for e in self.errors)
            raise CompilerError(f"Compilation failed with {len(self.errors)} error(s):\n{msg}")

    def clear(self) -> None:
        """Clear all errors."""
        self.errors = []
