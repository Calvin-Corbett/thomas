"""Data types for code generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GeneratedCode:
    """Generated code with metadata."""

    code: str
    """The generated code"""

    language: str
    """Programming language (python, javascript, sql, go, etc.)"""

    template: str
    """Name of template used"""

    filepath_suggestion: str
    """Suggested file path for the generated code"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "language": self.language,
            "template": self.template,
            "filepath_suggestion": self.filepath_suggestion,
        }


@dataclass
class GeneratedFile:
    """A file to be generated as part of a project scaffold."""

    path: str
    """File path relative to project root"""

    content: str
    """File content"""

    language: str
    """Programming language/type"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": self.path,
            "content": self.content,
            "language": self.language,
        }


@dataclass
class ProjectScaffold:
    """Scaffolded project structure."""

    name: str
    """Project name"""

    files: list[GeneratedFile] = field(default_factory=list)
    """Generated files"""

    structure: dict[str, Any] = field(default_factory=dict)
    """Project structure metadata"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "files": [f.to_dict() for f in self.files],
            "structure": self.structure,
        }


@dataclass
class CRUDOutput:
    """Generated CRUD operations."""

    model: str
    """Model/entity name"""

    create: str
    """Create operation code"""

    read: str
    """Read operation code"""

    update: str
    """Update operation code"""

    delete: str
    """Delete operation code"""

    tests: str
    """Test code"""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "model": self.model,
            "create": self.create,
            "read": self.read,
            "update": self.update,
            "delete": self.delete,
            "tests": self.tests,
        }
