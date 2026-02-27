"""
Core validation engine.
"""

from typing import Any

from thomas.validation._exceptions import ValidationException
from thomas.validation._types import (
    FieldRule,
    SchemaDefinition,
    Severity,
    ValidationError,
    ValidationResult,
    ValidatorConfig,
)
from thomas.validation.schema import Schema


class Validator:
    """Main validator class for schema validation."""

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        """Initialize validator.

        Args:
            config: ValidatorConfig instance or None for defaults.
        """
        self.config = config or ValidatorConfig()
        self._depth = 0
        self._error_count = 0

    def validate(
        self,
        data: Any,
        schema: SchemaDefinition | dict[str, Any],
    ) -> ValidationResult:
        """Validate data against schema.

        Args:
            data: Data to validate.
            schema: SchemaDefinition or dict schema.

        Returns:
            ValidationResult with errors and warnings.

        Raises:
            ValidationException: On critical validation errors.
        """
        self._depth = 0
        self._error_count = 0

        if isinstance(schema, dict):
            schema = Schema.from_dict(schema).definition

        result = ValidationResult(
            is_valid=True,
            data=data,
        )

        self._validate_value(data, schema, result, [])

        result.is_valid = len([e for e in result.errors if e.severity == Severity.ERROR]) == 0
        result.metadata["depth"] = self._depth
        result.metadata["error_count"] = self._error_count

        return result

    def _validate_value(
        self,
        value: Any,
        schema: SchemaDefinition,
        result: ValidationResult,
        path: list[str | int],
    ) -> None:
        """Recursively validate a value.

        Args:
            value: Value to validate.
            schema: Schema definition.
            result: Accumulating result.
            path: Current path in nested structure.
        """
        # Check max errors
        if self.config.max_errors and self._error_count >= self.config.max_errors:
            return

        # Check depth
        if self.config.max_object_depth and self._depth >= self.config.max_object_depth:
            self._add_error(
                result,
                f"Maximum nesting depth ({self.config.max_object_depth}) exceeded",
                "",
                path,
                "max_depth",
                value,
            )
            return

        # Handle null/None
        if value is None:
            if schema.nullable or schema.default is not None:
                return
            self._add_error(result, "Value is required (null not allowed)", "", path, "nullable", value)
            return

        # Validate type
        self._validate_type(value, schema, result, path)

        # Validate against anyOf
        if schema.anyOf:
            if not self._validate_any_of(value, schema.anyOf, path):
                self._add_error(
                    result,
                    "Value does not match any of the allowed schemas",
                    "",
                    path,
                    "anyOf",
                    value,
                )

        # Validate against oneOf
        if schema.oneOf:
            matches = sum(1 for s in schema.oneOf if self._matches_schema(value, s, path))
            if matches != 1:
                self._add_error(
                    result,
                    f"Value must match exactly one schema, matched {matches}",
                    "",
                    path,
                    "oneOf",
                    value,
                )

        # Validate against allOf
        if schema.allOf:
            if not all(self._matches_schema(value, s, path) for s in schema.allOf):
                self._add_error(
                    result,
                    "Value does not match all required schemas",
                    "",
                    path,
                    "allOf",
                    value,
                )

        # Type-specific validation
        if schema.type == "object" and isinstance(value, dict):
            self._validate_object(value, schema, result, path)
        elif schema.type == "array" and isinstance(value, list):
            self._validate_array(value, schema, result, path)
        elif schema.type in ("string", "number", "integer", "boolean"):
            self._validate_scalar(value, schema, result, path)

        # Apply custom rules
        for rule in schema.rules:
            if not rule.enabled:
                continue
            try:
                if not rule.validator(value):
                    self._add_error(
                        result,
                        rule.message or f"Failed {rule.name} validation",
                        "",
                        path,
                        rule.name,
                        value,
                        rule.severity,
                        rule.context,
                    )
            except Exception as e:
                self._add_error(
                    result,
                    f"Rule {rule.name} raised exception: {str(e)}",
                    "",
                    path,
                    rule.name,
                    value,
                )

    def _validate_type(
        self,
        value: Any,
        schema: SchemaDefinition,
        result: ValidationResult,
        path: list[str | int],
    ) -> None:
        """Validate value type against schema."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "object": dict,
            "array": list,
        }

        if schema.type not in type_map:
            return

        expected_type = type_map[schema.type]
        if not isinstance(value, expected_type):
            self._add_error(
                result,
                f"Expected {schema.type}, got {type(value).__name__}",
                "",
                path,
                "type",
                value,
                context={"expected": schema.type, "actual": type(value).__name__},
            )

    def _validate_object(
        self,
        value: dict[str, Any],
        schema: SchemaDefinition,
        result: ValidationResult,
        path: list[str | int],
    ) -> None:
        """Validate object/dict value."""
        self._depth += 1

        # Check required fields
        for field_name in schema.required:
            if field_name not in value:
                self._add_error(
                    result,
                    f"Required field '{field_name}' is missing",
                    field_name,
                    path,
                    "required",
                    None,
                )

        # Check unknown fields
        if not self.config.allow_unknown_fields:
            for field_name in value:
                if field_name not in schema.properties:
                    self._add_error(
                        result,
                        f"Unknown field '{field_name}'",
                        field_name,
                        path,
                        "unknown_field",
                        value[field_name],
                        Severity.WARNING,
                    )

        # Validate properties
        for field_name, field_value in value.items():
            if field_name in schema.properties:
                field_path = path + [field_name]
                self._validate_value(field_value, schema.properties[field_name], result, field_path)

        self._depth -= 1

    def _validate_array(
        self,
        value: list[Any],
        schema: SchemaDefinition,
        result: ValidationResult,
        path: list[str | int],
    ) -> None:
        """Validate array value."""
        if self.config.max_array_length and len(value) > self.config.max_array_length:
            self._add_error(
                result,
                f"Array exceeds maximum length ({self.config.max_array_length})",
                "",
                path,
                "max_array_length",
                value,
                context={"max": self.config.max_array_length, "actual": len(value)},
            )
            return

        self._depth += 1

        if schema.items:
            for idx, item in enumerate(value):
                item_path = path + [idx]
                self._validate_value(item, schema.items, result, item_path)

        self._depth -= 1

    def _validate_scalar(
        self,
        value: Any,
        schema: SchemaDefinition,
        result: ValidationResult,
        path: list[str | int],
    ) -> None:
        """Validate scalar values (string, number, etc.)."""
        pass  # Type already validated in _validate_type

    def _validate_any_of(
        self,
        value: Any,
        schemas: list[SchemaDefinition],
        path: list[str | int],
    ) -> bool:
        """Check if value matches any schema."""
        for schema in schemas:
            if self._matches_schema(value, schema, path):
                return True
        return False

    def _matches_schema(
        self,
        value: Any,
        schema: SchemaDefinition,
        path: list[str | int],
    ) -> bool:
        """Check if value matches schema without adding errors."""
        # Create temporary result to test
        temp_result = ValidationResult(is_valid=True)
        self._validate_value(value, schema, temp_result, path)
        return len([e for e in temp_result.errors if e.severity == Severity.ERROR]) == 0

    def _add_error(
        self,
        result: ValidationResult,
        message: str,
        field: str = "",
        path: list[str | int] | None = None,
        rule: str = "",
        value: Any = None,
        severity: Severity = Severity.ERROR,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Add error to result."""
        if self.config.max_errors and self._error_count >= self.config.max_errors:
            return

        error = ValidationError(
            message=message,
            field=field,
            path=path or [],
            rule=rule,
            value=value,
            severity=severity,
            context=context or {},
        )

        if severity == Severity.ERROR:
            result.errors.append(error)
            self._error_count += 1
        else:
            result.warnings.append(error)

        if self.config.fail_fast and severity == Severity.ERROR:
            raise ValidationException("Validation failed", [error])

    def validate_field(
        self,
        field_value: Any,
        rules: list[FieldRule],
    ) -> list[ValidationError]:
        """Validate a single field against rules.

        Args:
            field_value: Value to validate.
            rules: List of validation rules.

        Returns:
            List of validation errors.
        """
        errors = []
        for rule in rules:
            if not rule.enabled:
                continue
            try:
                if not rule.validator(field_value):
                    errors.append(
                        ValidationError(
                            message=rule.message or f"Failed {rule.name}",
                            field="",
                            rule=rule.name,
                            value=field_value,
                            severity=rule.severity,
                            context=rule.context,
                        )
                    )
            except Exception as e:
                errors.append(
                    ValidationError(
                        message=f"Rule {rule.name} error: {str(e)}",
                        field="",
                        rule=rule.name,
                        value=field_value,
                    )
                )
        return errors

    def set_config(self, **kwargs: Any) -> None:
        """Update validator configuration.

        Args:
            **kwargs: Configuration keys and values.
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
