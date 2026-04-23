"""
Configuration validation framework.

Provides schema validation, compliance checking, and pre/post-execution
validation for configurations and resources.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValidationType(Enum):
    """Types of validation operations."""

    SCHEMA = "schema"
    COMPLIANCE = "compliance"
    SYNTAX = "syntax"
    DEPENDENCY = "dependency"
    PERFORMANCE = "performance"


@dataclass
class ValidationError:
    """Represents a validation error."""

    code: str
    message: str
    path: str = ""
    severity: str = "error"  # error, warning, info
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary representation."""
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "severity": self.severity,
            "metadata": self.metadata,
        }


@dataclass
class ValidationRule:
    """Represents a validation rule."""

    name: str
    rule_type: ValidationType
    condition: Callable[[Any], bool]
    error_message: str
    auto_fix: Callable[[Any], Any] | None = None
    enabled: bool = True

    def validate(self, value: Any) -> bool | ValidationError:
        """Execute validation rule."""
        if not self.enabled:
            return True

        try:
            is_valid = self.condition(value)
            if not is_valid:
                return ValidationError(
                    code=self.name,
                    message=self.error_message,
                    severity="error",
                )
            return True
        except Exception as e:
            return ValidationError(
                code=f"{self.name}_exception",
                message=f"Validation failed: {str(e)}",
                severity="error",
                metadata={"exception": str(e)},
            )

    def apply_fix(self, value: Any) -> Any | None:
        """Apply automatic fix if available."""
        if self.auto_fix:
            try:
                return self.auto_fix(value)
            except Exception:
                return None
        return None


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    is_valid: bool
    validation_type: ValidationType
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)
    duration_ms: float = 0.0
    total_checks: int = 0
    passed_checks: int = 0

    @property
    def error_count(self) -> int:
        """Get count of errors."""
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        """Get count of warnings."""
        return len(self.warnings)

    @property
    def success_rate(self) -> float:
        """Get success rate as percentage."""
        if self.total_checks == 0:
            return 100.0
        return (self.passed_checks / self.total_checks) * 100

    def add_error(self, error: ValidationError) -> None:
        """Add an error to results."""
        self.errors.append(error)

    def add_warning(self, warning: ValidationError) -> None:
        """Add a warning to results."""
        self.warnings.append(warning)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another validation result."""
        merged = ValidationResult(
            is_valid=self.is_valid and other.is_valid,
            validation_type=self.validation_type,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
            total_checks=self.total_checks + other.total_checks,
            passed_checks=self.passed_checks + other.passed_checks,
        )
        return merged

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "validation_type": self.validation_type.value,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "success_rate": self.success_rate,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class Validator:
    """Main validation engine for configurations."""

    def __init__(self) -> None:
        """Initialize validator with default rules."""
        self.rules: dict[str, ValidationRule] = {}
        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Setup built-in validation rules."""
        # Type checking rules
        self.add_rule(
            ValidationRule(
                name="string_type",
                rule_type=ValidationType.SCHEMA,
                condition=lambda x: isinstance(x, str),
                error_message="Value must be a string",
            )
        )

        self.add_rule(
            ValidationRule(
                name="integer_type",
                rule_type=ValidationType.SCHEMA,
                condition=lambda x: isinstance(x, int),
                error_message="Value must be an integer",
            )
        )

        self.add_rule(
            ValidationRule(
                name="not_empty",
                rule_type=ValidationType.SCHEMA,
                condition=lambda x: bool(x) if x is not None else False,
                error_message="Value cannot be empty",
                auto_fix=lambda x: x.strip() if isinstance(x, str) else x,
            )
        )

    def add_rule(self, rule: ValidationRule) -> None:
        """Register a validation rule."""
        self.rules[rule.name] = rule

    def remove_rule(self, rule_name: str) -> None:
        """Remove a validation rule."""
        if rule_name in self.rules:
            del self.rules[rule_name]

    def enable_rule(self, rule_name: str) -> None:
        """Enable a specific rule."""
        if rule_name in self.rules:
            self.rules[rule_name].enabled = True

    def disable_rule(self, rule_name: str) -> None:
        """Disable a specific rule."""
        if rule_name in self.rules:
            self.rules[rule_name].enabled = False

    def validate_value(self, value: Any, rule_names: list[str]) -> ValidationResult:
        """Validate a value against multiple rules."""
        result = ValidationResult(
            is_valid=True,
            validation_type=ValidationType.SCHEMA,
        )

        for rule_name in rule_names:
            if rule_name not in self.rules:
                continue

            rule = self.rules[rule_name]
            validation_result = rule.validate(value)

            result.total_checks += 1
            if validation_result is True:
                result.passed_checks += 1
            else:
                result.is_valid = False
                result.add_error(validation_result)

        return result

    def validate_schema(self, data: Any, schema: dict[str, Any]) -> ValidationResult:
        """Validate data against a schema definition."""
        result = ValidationResult(
            is_valid=True,
            validation_type=ValidationType.SCHEMA,
        )

        if not isinstance(data, dict):
            error = ValidationError(
                code="invalid_root_type",
                message="Data must be a dictionary",
            )
            result.add_error(error)
            return result

        for key, schema_def in schema.items():
            result.total_checks += 1

            if key not in data:
                if schema_def.get("required", False):
                    error = ValidationError(
                        code="missing_required_field",
                        message=f"Required field '{key}' is missing",
                        path=key,
                    )
                    result.is_valid = False
                    result.add_error(error)
                continue

            value = data[key]
            expected_type = schema_def.get("type")

            if expected_type and not isinstance(value, expected_type):
                error = ValidationError(
                    code="type_mismatch",
                    message=f"Field '{key}' must be {expected_type.__name__}",
                    path=key,
                    metadata={"expected": expected_type.__name__, "actual": type(value).__name__},
                )
                result.is_valid = False
                result.add_error(error)
                continue

            # Pattern validation
            if "pattern" in schema_def:
                pattern = schema_def["pattern"]
                if isinstance(value, str) and not re.match(pattern, value):
                    error = ValidationError(
                        code="pattern_mismatch",
                        message=f"Field '{key}' does not match pattern",
                        path=key,
                        metadata={"pattern": pattern},
                    )
                    result.is_valid = False
                    result.add_error(error)
                    continue

            # Range validation
            if "min_value" in schema_def:
                if value < schema_def["min_value"]:
                    error = ValidationError(
                        code="below_minimum",
                        message=f"Field '{key}' is below minimum",
                        path=key,
                        metadata={"min": schema_def["min_value"]},
                    )
                    result.is_valid = False
                    result.add_error(error)

            if "max_value" in schema_def:
                if value > schema_def["max_value"]:
                    error = ValidationError(
                        code="above_maximum",
                        message=f"Field '{key}' is above maximum",
                        path=key,
                        metadata={"max": schema_def["max_value"]},
                    )
                    result.is_valid = False
                    result.add_error(error)

            result.passed_checks += 1

        return result

    def validate_syntax(self, config_str: str) -> ValidationResult:
        """Validate configuration syntax."""
        result = ValidationResult(
            is_valid=True,
            validation_type=ValidationType.SYNTAX,
        )

        # Basic bracket matching
        brackets = {"(": ")", "[": "]", "{": "}"}
        stack: list[str] = []

        for i, char in enumerate(config_str):
            if char in brackets:
                stack.append(char)
            elif char in brackets.values():
                if not stack:
                    error = ValidationError(
                        code="mismatched_bracket",
                        message=f"Unexpected closing bracket '{char}' at position {i}",
                        metadata={"position": i},
                    )
                    result.add_error(error)
                    result.is_valid = False
                elif brackets[stack[-1]] == char:
                    stack.pop()
                    result.total_checks += 1
                    result.passed_checks += 1
                else:
                    error = ValidationError(
                        code="mismatched_bracket",
                        message=f"Mismatched bracket at position {i}",
                        metadata={"position": i},
                    )
                    result.add_error(error)
                    result.is_valid = False

        if stack:
            for bracket in stack:
                error = ValidationError(
                    code="unclosed_bracket",
                    message=f"Unclosed bracket '{bracket}'",
                )
                result.add_error(error)
                result.is_valid = False

        return result
