"""
Composite validators for complex validation patterns.
"""

from collections.abc import Callable
from typing import Any

from thomas.marketplace.validation._types import FieldRule, SchemaDefinition, Severity, ValidationError
from thomas.marketplace.validation.core import Validator


class And:
    """Composite: all validators must pass."""

    def __init__(self, validators: list[Callable[[Any], bool]]) -> None:
        """Initialize And composite.

        Args:
            validators: List of validator functions.
        """
        self.validators = validators

    def __call__(self, value: Any) -> bool:
        """Validate: all must pass."""
        return all(v(value) for v in self.validators)


class Or:
    """Composite: at least one validator must pass."""

    def __init__(self, validators: list[Callable[[Any], bool]]) -> None:
        """Initialize Or composite.

        Args:
            validators: List of validator functions.
        """
        self.validators = validators

    def __call__(self, value: Any) -> bool:
        """Validate: at least one must pass."""
        return any(v(value) for v in self.validators)


class Not:
    """Composite: validator must fail."""

    def __init__(self, validator: Callable[[Any], bool]) -> None:
        """Initialize Not composite.

        Args:
            validator: Validator function to invert.
        """
        self.validator = validator

    def __call__(self, value: Any) -> bool:
        """Validate: must fail."""
        return not self.validator(value)


class Conditional:
    """Conditional validation: if condition passes, apply validator."""

    def __init__(
        self,
        condition: Callable[[Any], bool],
        validator: Callable[[Any], bool],
        message: str = "Conditional validation failed",
    ) -> None:
        """Initialize conditional validator.

        Args:
            condition: Condition function.
            validator: Validator to apply if condition passes.
            message: Error message.
        """
        self.condition = condition
        self.validator = validator
        self.message = message

    def __call__(self, value: Any) -> bool:
        """Validate conditionally."""
        if self.condition(value):
            return self.validator(value)
        return True

    def as_rule(self) -> FieldRule:
        """Return as FieldRule."""
        return FieldRule(
            name="conditional",
            validator=self,
            message=self.message,
        )


class DependentFields:
    """Validate field relationships (cross-field validation)."""

    def __init__(self, dependencies: dict[str, Callable[[dict[str, Any]], bool]]) -> None:
        """Initialize dependent fields validator.

        Args:
            dependencies: Mapping of dependent field to validator.
                         Validator receives full object and returns True if valid.
        """
        self.dependencies = dependencies

    def validate(self, data: dict[str, Any]) -> list[ValidationError]:
        """Validate field dependencies.

        Args:
            data: Object with all fields.

        Returns:
            List of validation errors.
        """
        errors = []
        for field_name, validator in self.dependencies.items():
            try:
                if not validator(data):
                    errors.append(
                        ValidationError(
                            message=f"Dependent field validation failed for '{field_name}'",
                            field=field_name,
                            rule="dependent_fields",
                            value=data.get(field_name),
                        )
                    )
            except Exception as e:
                errors.append(
                    ValidationError(
                        message=f"Dependent field validation error for '{field_name}': {str(e)}",
                        field=field_name,
                        rule="dependent_fields",
                        value=data.get(field_name),
                    )
                )
        return errors


class ArrayValidator:
    """Validate array elements with schema."""

    def __init__(
        self,
        item_schema: SchemaDefinition,
        min_items: int | None = None,
        max_items: int | None = None,
        unique_items: bool = False,
    ) -> None:
        """Initialize array validator.

        Args:
            item_schema: Schema for array items.
            min_items: Minimum array length.
            max_items: Maximum array length.
            unique_items: If True, all items must be unique.
        """
        self.item_schema = item_schema
        self.min_items = min_items
        self.max_items = max_items
        self.unique_items = unique_items

    def validate(self, value: Any) -> list[ValidationError]:
        """Validate array.

        Args:
            value: Value to validate.

        Returns:
            List of validation errors.
        """
        errors = []

        if not isinstance(value, list):
            return [
                ValidationError(
                    message="Expected list/array",
                    field="",
                    rule="array_type",
                    value=value,
                )
            ]

        # Check length
        if self.min_items is not None and len(value) < self.min_items:
            errors.append(
                ValidationError(
                    message=f"Array has too few items (minimum: {self.min_items})",
                    field="",
                    rule="min_items",
                    value=value,
                    context={"min": self.min_items, "actual": len(value)},
                )
            )

        if self.max_items is not None and len(value) > self.max_items:
            errors.append(
                ValidationError(
                    message=f"Array has too many items (maximum: {self.max_items})",
                    field="",
                    rule="max_items",
                    value=value,
                    context={"max": self.max_items, "actual": len(value)},
                )
            )

        # Check uniqueness
        if self.unique_items:
            seen = set()
            for idx, item in enumerate(value):
                # Convert to hashable form
                try:
                    hashable = (
                        tuple(item.items())
                        if isinstance(item, dict)
                        else tuple(item)
                        if isinstance(item, list)
                        else item
                    )
                    if hashable in seen:
                        errors.append(
                            ValidationError(
                                message=f"Duplicate item at index {idx}",
                                field="",
                                path=[idx],
                                rule="unique_items",
                                value=item,
                            )
                        )
                    seen.add(hashable)
                except TypeError:
                    # Unhashable type, skip
                    pass

        # Validate items
        validator = Validator()
        for idx, item in enumerate(value):
            result = validator.validate(item, self.item_schema)
            for error in result.errors:
                error.path = [idx] + error.path
                errors.append(error)

        return errors


class MapValidator:
    """Validate dict/object with schema for all values."""

    def __init__(
        self,
        value_schema: SchemaDefinition,
        allowed_keys: list[str] | None = None,
        required_keys: list[str] | None = None,
    ) -> None:
        """Initialize map validator.

        Args:
            value_schema: Schema for all values.
            allowed_keys: If set, only these keys are allowed.
            required_keys: Keys that must be present.
        """
        self.value_schema = value_schema
        self.allowed_keys = allowed_keys
        self.required_keys = required_keys

    def validate(self, value: Any) -> list[ValidationError]:
        """Validate map/dict.

        Args:
            value: Value to validate.

        Returns:
            List of validation errors.
        """
        errors = []

        if not isinstance(value, dict):
            return [
                ValidationError(
                    message="Expected dict/object",
                    field="",
                    rule="map_type",
                    value=value,
                )
            ]

        # Check required keys
        if self.required_keys:
            for key in self.required_keys:
                if key not in value:
                    errors.append(
                        ValidationError(
                            message=f"Required key '{key}' is missing",
                            field=key,
                            rule="required_key",
                            value=None,
                        )
                    )

        # Check allowed keys
        if self.allowed_keys:
            for key in value:
                if key not in self.allowed_keys:
                    errors.append(
                        ValidationError(
                            message=f"Key '{key}' is not allowed",
                            field=key,
                            rule="allowed_key",
                            value=value[key],
                            severity=Severity.WARNING,
                        )
                    )

        # Validate values
        validator = Validator()
        for key, val in value.items():
            result = validator.validate(val, self.value_schema)
            for error in result.errors:
                error.field = key
                error.path = [key] + error.path
                errors.append(error)

        return errors


class IfThenElse:
    """Conditional schema: if condition, then schema1, else schema2."""

    def __init__(
        self,
        if_condition: Callable[[Any], bool],
        then_schema: SchemaDefinition,
        else_schema: SchemaDefinition | None = None,
    ) -> None:
        """Initialize if-then-else validator.

        Args:
            if_condition: Condition to check.
            then_schema: Schema if condition true.
            else_schema: Schema if condition false.
        """
        self.if_condition = if_condition
        self.then_schema = then_schema
        self.else_schema = else_schema

    def validate(self, value: Any) -> list[ValidationError]:
        """Validate conditionally.

        Args:
            value: Value to validate.

        Returns:
            List of validation errors.
        """
        validator = Validator()

        if self.if_condition(value):
            result = validator.validate(value, self.then_schema)
        elif self.else_schema:
            result = validator.validate(value, self.else_schema)
        else:
            return []

        return result.errors
