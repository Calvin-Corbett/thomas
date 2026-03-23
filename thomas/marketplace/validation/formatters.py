"""
Error formatting and reporting.
"""

import json
from typing import Any

from thomas.marketplace.validation._types import Severity, ValidationError, ValidationResult


class JsonErrorFormatter:
    """Format validation errors as JSON."""

    def format(self, result: ValidationResult) -> str:
        """Format result as JSON string.

        Args:
            result: ValidationResult to format.

        Returns:
            JSON string representation.
        """
        data = self.to_dict(result)
        return json.dumps(data, indent=2)

    def to_dict(self, result: ValidationResult) -> dict[str, Any]:
        """Convert result to dictionary.

        Args:
            result: ValidationResult to convert.

        Returns:
            Dictionary representation.
        """
        errors_list = [self._error_to_dict(e) for e in result.errors]
        warnings_list = [self._error_to_dict(e) for e in result.warnings]

        return {
            "valid": result.is_valid,
            "error_count": result.error_count(),
            "warning_count": result.warning_count(),
            "errors": errors_list,
            "warnings": warnings_list,
        }

    @staticmethod
    def _error_to_dict(error: ValidationError) -> dict[str, Any]:
        """Convert single error to dictionary."""
        return {
            "message": error.message,
            "field": error.field,
            "path": error.full_path(),
            "rule": error.rule,
            "severity": error.severity.value,
            "value": str(error.value) if error.value is not None else None,
            "context": error.context,
        }


class HumanErrorFormatter:
    """Format validation errors for humans."""

    def __init__(self, include_paths: bool = True, include_context: bool = False) -> None:
        """Initialize formatter.

        Args:
            include_paths: If True, include full paths in messages.
            include_context: If True, include rule context.
        """
        self.include_paths = include_paths
        self.include_context = include_context

    def format(self, result: ValidationResult) -> str:
        """Format result as human-readable string.

        Args:
            result: ValidationResult to format.

        Returns:
            Formatted string.
        """
        lines = []

        if result.is_valid:
            return "Validation passed!"

        lines.append("Validation failed with the following issues:\n")

        # Errors
        if result.errors:
            lines.append(f"ERRORS ({result.error_count()}):")
            for error in result.errors:
                lines.append(self._format_error(error, indent=2))
            lines.append("")

        # Warnings
        if result.warnings:
            lines.append(f"WARNINGS ({result.warning_count()}):")
            for warning in result.warnings:
                lines.append(self._format_error(warning, indent=2))

        return "\n".join(lines)

    def format_brief(self, result: ValidationResult) -> str:
        """Format as brief single-line summary.

        Args:
            result: ValidationResult to format.

        Returns:
            Brief string.
        """
        if result.is_valid:
            return "Validation passed!"

        error_msg = f"{result.error_count()} error(s)"
        warning_msg = f"{result.warning_count()} warning(s)" if result.warnings else ""
        parts = [error_msg, warning_msg] if warning_msg else [error_msg]
        return f"Validation failed: {', '.join(p for p in parts if p)}"

    def format_by_field(self, result: ValidationResult) -> str:
        """Format errors grouped by field.

        Args:
            result: ValidationResult to format.

        Returns:
            Formatted string with errors by field.
        """
        lines = []
        grouped = result.errors_by_field()

        if not grouped:
            return "Validation passed!"

        for field, errors in sorted(grouped.items()):
            lines.append(f"{field}:")
            for error in errors:
                lines.append(f"  - {error.message} ({error.rule})")

        return "\n".join(lines)

    def _format_error(self, error: ValidationError, indent: int = 0) -> str:
        """Format single error."""
        prefix = " " * indent
        path = error.full_path() if self.include_paths else error.field
        message = f"{prefix}{path}: {error.message}"

        if error.rule:
            message += f" [{error.rule}]"

        if self.include_context and error.context:
            context_str = ", ".join(f"{k}={v}" for k, v in error.context.items())
            message += f" ({context_str})"

        return message


class ErrorGrouper:
    """Group errors by various criteria."""

    @staticmethod
    def by_field(result: ValidationResult) -> dict[str, list[ValidationError]]:
        """Group errors by field path.

        Args:
            result: ValidationResult.

        Returns:
            Mapping of field path to errors.
        """
        return result.errors_by_field()

    @staticmethod
    def by_severity(result: ValidationResult) -> dict[Severity, list[ValidationError]]:
        """Group all issues by severity.

        Args:
            result: ValidationResult.

        Returns:
            Mapping of severity to errors/warnings.
        """
        return result.errors_by_severity()

    @staticmethod
    def by_rule(result: ValidationResult) -> dict[str, list[ValidationError]]:
        """Group errors by validation rule name.

        Args:
            result: ValidationResult.

        Returns:
            Mapping of rule name to errors.
        """
        grouped: dict[str, list[ValidationError]] = {}
        for error in result.errors:
            if error.rule not in grouped:
                grouped[error.rule] = []
            grouped[error.rule].append(error)
        return grouped

    @staticmethod
    def by_depth(result: ValidationResult) -> dict[int, list[ValidationError]]:
        """Group errors by nesting depth.

        Args:
            result: ValidationResult.

        Returns:
            Mapping of depth to errors.
        """
        grouped: dict[int, list[ValidationError]] = {}
        for error in result.errors:
            depth = len(error.path)
            if depth not in grouped:
                grouped[depth] = []
            grouped[depth].append(error)
        return grouped

    @staticmethod
    def critical_only(result: ValidationResult) -> ValidationResult:
        """Filter to errors only (no warnings).

        Args:
            result: ValidationResult.

        Returns:
            New result with only critical errors.
        """
        new_result = ValidationResult(
            is_valid=len([e for e in result.errors if e.severity == Severity.ERROR]) == 0,
            errors=result.errors,
            warnings=[],
            data=result.data,
        )
        return new_result

    @staticmethod
    def summary(result: ValidationResult) -> dict[str, Any]:
        """Generate summary statistics.

        Args:
            result: ValidationResult.

        Returns:
            Summary dictionary.
        """
        by_rule = ErrorGrouper.by_rule(result)
        by_field = ErrorGrouper.by_field(result)
        by_severity = ErrorGrouper.by_severity(result)
        by_depth = ErrorGrouper.by_depth(result)

        return {
            "valid": result.is_valid,
            "total_errors": result.error_count(),
            "total_warnings": result.warning_count(),
            "total_issues": result.error_count() + result.warning_count(),
            "errors_by_rule": {k: len(v) for k, v in by_rule.items()},
            "errors_by_field": {k: len(v) for k, v in by_field.items()},
            "errors_by_severity": {k.value: len(v) for k, v in by_severity.items()},
            "max_depth": max(by_depth.keys()) if by_depth else 0,
        }
