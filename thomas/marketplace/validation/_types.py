"""
Core type definitions for the validation module.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(Enum):
    """Error severity levels."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationError:
    """Represents a single validation error with path tracking."""

    message: str
    """Human-readable error message."""

    field: str
    """Field name where error occurred."""

    path: list[str | int] = field(default_factory=list)
    """Nested path to the error (e.g., ['user', 'address', 0, 'zipcode'])."""

    rule: str = ""
    """Name of the validation rule that failed."""

    value: Any = None
    """The value that failed validation."""

    severity: Severity = Severity.ERROR
    """Error severity level."""

    context: dict[str, Any] = field(default_factory=dict)
    """Additional context (min, max, pattern, etc.)."""

    def full_path(self) -> str:
        """Return full path as dotted string."""
        if not self.path:
            return self.field
        path_str = ".".join(str(p) for p in self.path)
        return f"{path_str}.{self.field}" if self.field else path_str

    def __str__(self) -> str:
        """Return formatted error message with path."""
        return f"{self.full_path()}: {self.message}"


@dataclass
class ValidationResult:
    """Result of validation containing all errors and status."""

    is_valid: bool
    """True if validation passed, False otherwise."""

    errors: list[ValidationError] = field(default_factory=list)
    """List of all validation errors found."""

    warnings: list[ValidationError] = field(default_factory=list)
    """List of all validation warnings."""

    data: Any = None
    """Original or coerced data."""

    coerced_data: Any = None
    """Data after type coercion, if applicable."""

    sanitized_data: Any = None
    """Data after sanitization, if applicable."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata about validation run."""

    def error_count(self) -> int:
        """Count of errors with ERROR severity."""
        return sum(1 for e in self.errors if e.severity == Severity.ERROR)

    def warning_count(self) -> int:
        """Count of warnings."""
        return len(self.warnings)

    def all_issues(self) -> list[ValidationError]:
        """Return all errors and warnings."""
        return self.errors + self.warnings

    def errors_by_field(self) -> dict[str, list[ValidationError]]:
        """Group errors by field path."""
        grouped: dict[str, list[ValidationError]] = {}
        for error in self.errors:
            key = error.full_path()
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(error)
        return grouped

    def errors_by_severity(self) -> dict[Severity, list[ValidationError]]:
        """Group all issues by severity."""
        grouped: dict[Severity, list[ValidationError]] = {}
        for issue in self.all_issues():
            if issue.severity not in grouped:
                grouped[issue.severity] = []
            grouped[issue.severity].append(issue)
        return grouped


@dataclass
class TypeSpec:
    """Type specification for validation."""

    name: str
    """Type name (int, str, dict, list, etc.)."""

    nullable: bool = False
    """If True, None/null values are allowed."""

    strict: bool = False
    """If True, no type coercion is performed."""

    default: Any = None
    """Default value if field is missing."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional type metadata."""


@dataclass
class FieldRule:
    """A validation rule applied to a field."""

    name: str
    """Rule name (required, pattern, email, etc.)."""

    validator: Callable[[Any], bool]
    """Function that returns True if valid."""

    message: str = ""
    """Error message template."""

    severity: Severity = Severity.ERROR
    """Severity of violations."""

    context: dict[str, Any] = field(default_factory=dict)
    """Additional context for the rule."""

    enabled: bool = True
    """If False, rule is skipped."""


@dataclass
class SchemaDefinition:
    """Definition of a schema for validation."""

    type: str = "object"
    """Schema type: object, array, string, number, etc."""

    properties: dict[str, "SchemaDefinition"] = field(default_factory=dict)
    """Sub-schemas for object properties."""

    required: list[str] = field(default_factory=list)
    """List of required property names."""

    items: Optional["SchemaDefinition"] = None
    """Schema for array items."""

    rules: list[FieldRule] = field(default_factory=list)
    """Custom validation rules."""

    anyOf: list["SchemaDefinition"] = field(default_factory=list)
    """Schema alternatives (one must validate)."""

    oneOf: list["SchemaDefinition"] = field(default_factory=list)
    """Exactly one schema must validate."""

    allOf: list["SchemaDefinition"] = field(default_factory=list)
    """All schemas must validate."""

    ref: str | None = None
    """Reference to named schema."""

    title: str = ""
    """Human-readable schema title."""

    description: str = ""
    """Schema description."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional schema metadata."""

    nullable: bool = False
    """If True, null values are allowed."""

    default: Any = None
    """Default value."""


@dataclass
class ValidatorConfig:
    """Configuration for Validator behavior."""

    fail_fast: bool = False
    """If True, stop at first error. Default: accumulate all errors."""

    allow_coercion: bool = True
    """If True, attempt type coercion."""

    allow_sanitization: bool = True
    """If True, apply sanitization rules."""

    strict_types: bool = False
    """If True, no type coercion, strict type checking."""

    allow_unknown_fields: bool = True
    """If True, allow fields not in schema."""

    trim_strings: bool = True
    """If True, trim whitespace from strings."""

    normalize_unicode: bool = False
    """If True, normalize unicode in strings."""

    max_array_length: int | None = None
    """Maximum array length, None for unlimited."""

    max_object_depth: int | None = 50
    """Maximum nesting depth for objects."""

    max_errors: int | None = None
    """Stop after this many errors, None for unlimited."""

    include_metadata: bool = False
    """If True, include validation metadata in result."""

    locale: str = "en"
    """Locale for error messages."""

    timezone: str = "UTC"
    """Timezone for date/time validation."""

    custom_coercers: dict[str, Callable[[Any], Any]] = field(default_factory=dict)
    """Custom type coercion functions."""

    custom_rules: dict[str, Callable[[Any], bool]] = field(default_factory=dict)
    """Custom validation rules by name."""
