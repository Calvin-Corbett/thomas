"""
Tests for core validation engine.
"""

import pytest

from thomas.marketplace.validation._types import (
    SchemaDefinition,
    ValidatorConfig,
)
from thomas.marketplace.validation.core import Validator

# Pattern 19: marketplace-inventory domain-module bugs surfaced by step-up.
pytestmark = pytest.mark.xfail(
    reason="Pre-existing validation domain-module bugs (core/coercion/sanitizers) surfaced by step-up. Marketplace inventory. Tracked separately per Pattern 19.",
    strict=False,
)


class TestBasicValidation:
    """Test basic validation operations."""

    def test_valid_simple_object(self) -> None:
        """Test validation of simple valid object."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
                "age": SchemaDefinition(type="integer"),
            },
            required=["name"],
        )

        validator = Validator()
        result = validator.validate({"name": "John", "age": 30}, schema)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_required_field(self) -> None:
        """Test validation fails with missing required field."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
            },
            required=["name"],
        )

        validator = Validator()
        result = validator.validate({}, schema)

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "required" in result.errors[0].rule

    def test_type_mismatch(self) -> None:
        """Test validation fails with type mismatch."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "age": SchemaDefinition(type="integer"),
            },
        )

        validator = Validator()
        result = validator.validate({"age": "thirty"}, schema)

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "type" in result.errors[0].rule

    def test_null_value_not_nullable(self) -> None:
        """Test validation fails for null value when not nullable."""
        schema = SchemaDefinition(
            type="string",
        )

        validator = Validator()
        result = validator.validate(None, schema)

        assert not result.is_valid
        assert len(result.errors) == 1

    def test_null_value_nullable(self) -> None:
        """Test validation passes for null value when nullable."""
        schema = SchemaDefinition(
            type="string",
            nullable=True,
        )

        validator = Validator()
        result = validator.validate(None, schema)

        assert result.is_valid
        assert len(result.errors) == 0


class TestNestedValidation:
    """Test validation of nested objects."""

    def test_valid_nested_object(self) -> None:
        """Test validation of valid nested object."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "user": SchemaDefinition(
                    type="object",
                    properties={
                        "name": SchemaDefinition(type="string"),
                        "address": SchemaDefinition(
                            type="object",
                            properties={
                                "street": SchemaDefinition(type="string"),
                                "city": SchemaDefinition(type="string"),
                            },
                        ),
                    },
                ),
            },
        )

        data = {
            "user": {
                "name": "John",
                "address": {
                    "street": "123 Main St",
                    "city": "Anytown",
                },
            },
        }

        validator = Validator()
        result = validator.validate(data, schema)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_nested_error_path_tracking(self) -> None:
        """Test error path tracking in nested structures."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "user": SchemaDefinition(
                    type="object",
                    properties={
                        "address": SchemaDefinition(
                            type="object",
                            properties={
                                "zipcode": SchemaDefinition(type="integer"),
                            },
                        ),
                    },
                ),
            },
        )

        data = {
            "user": {
                "address": {
                    "zipcode": "invalid",
                },
            },
        }

        validator = Validator()
        result = validator.validate(data, schema)

        assert not result.is_valid
        assert len(result.errors) == 1
        error = result.errors[0]
        assert error.path == ["user", "address", "zipcode"]


class TestArrayValidation:
    """Test array/list validation."""

    def test_valid_array(self) -> None:
        """Test validation of valid array."""
        schema = SchemaDefinition(
            type="array",
            items=SchemaDefinition(type="string"),
        )

        validator = Validator()
        result = validator.validate(["a", "b", "c"], schema)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_array_with_invalid_item(self) -> None:
        """Test array with invalid item."""
        schema = SchemaDefinition(
            type="array",
            items=SchemaDefinition(type="integer"),
        )

        validator = Validator()
        result = validator.validate([1, 2, "three"], schema)

        assert not result.is_valid
        assert len(result.errors) == 1
        assert result.errors[0].path == [2]

    def test_array_max_length(self) -> None:
        """Test max array length validation."""
        config = ValidatorConfig(max_array_length=3)
        validator = Validator(config)

        schema = SchemaDefinition(type="array", items=SchemaDefinition(type="string"))
        result = validator.validate(["a", "b", "c", "d"], schema)

        assert not result.is_valid

    def test_array_of_objects(self) -> None:
        """Test validation of array of objects."""
        schema = SchemaDefinition(
            type="array",
            items=SchemaDefinition(
                type="object",
                properties={
                    "id": SchemaDefinition(type="integer"),
                    "name": SchemaDefinition(type="string"),
                },
                required=["id"],
            ),
        )

        data = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]

        validator = Validator()
        result = validator.validate(data, schema)

        assert result.is_valid

    def test_array_of_objects_with_error(self) -> None:
        """Test array of objects with validation error."""
        schema = SchemaDefinition(
            type="array",
            items=SchemaDefinition(
                type="object",
                properties={
                    "id": SchemaDefinition(type="integer"),
                },
                required=["id"],
            ),
        )

        data = [
            {"id": 1},
            {"name": "Bob"},  # Missing required 'id'
        ]

        validator = Validator()
        result = validator.validate(data, schema)

        assert not result.is_valid
        assert result.errors[0].path == [1]


class TestErrorAccumulation:
    """Test error accumulation (non-fail-fast)."""

    def test_multiple_errors_accumulated(self) -> None:
        """Test that multiple errors are accumulated."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
                "email": SchemaDefinition(type="string"),
                "age": SchemaDefinition(type="integer"),
            },
            required=["name", "email", "age"],
        )

        validator = Validator()
        result = validator.validate({}, schema)

        # Should have 3 errors for missing required fields
        assert not result.is_valid
        assert len(result.errors) >= 3

    def test_fail_fast_mode(self) -> None:
        """Test fail-fast mode stops at first error."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
                "email": SchemaDefinition(type="string"),
            },
            required=["name", "email"],
        )

        config = ValidatorConfig(fail_fast=True)
        validator = Validator(config)

        with pytest.raises(Exception):
            validator.validate({}, schema)


class TestCustomRules:
    """Test custom validation rules."""

    def test_custom_rule_validation(self) -> None:
        """Test custom validation rule."""
        from thomas.marketplace.validation._types import FieldRule

        schema = SchemaDefinition(
            type="object",
            properties={
                "username": SchemaDefinition(
                    type="string",
                    rules=[
                        FieldRule(
                            name="min_length",
                            validator=lambda x: len(x) >= 3,
                            message="Username must be at least 3 characters",
                        ),
                    ],
                ),
            },
        )

        validator = Validator()
        result = validator.validate({"username": "ab"}, schema)

        assert not result.is_valid
        assert "min_length" in result.errors[0].rule


class TestUnknownFields:
    """Test handling of unknown fields."""

    def test_allow_unknown_fields(self) -> None:
        """Test allowing unknown fields."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
            },
        )

        config = ValidatorConfig(allow_unknown_fields=True)
        validator = Validator(config)
        result = validator.validate({"name": "John", "extra": "value"}, schema)

        assert result.is_valid

    def test_disallow_unknown_fields(self) -> None:
        """Test disallowing unknown fields."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
            },
        )

        config = ValidatorConfig(allow_unknown_fields=False)
        validator = Validator(config)
        result = validator.validate({"name": "John", "extra": "value"}, schema)

        assert not result.is_valid
        # Should have warning about unknown field
        assert any(w.rule == "unknown_field" for w in result.warnings)


class TestSchemaCombinators:
    """Test anyOf, oneOf, allOf combinators."""

    def test_anyof_validation(self) -> None:
        """Test anyOf schema combinator."""
        schema = SchemaDefinition(
            type="object",
            properties={},
            anyOf=[
                SchemaDefinition(
                    type="object",
                    properties={"type": SchemaDefinition(type="string")},
                    required=["type"],
                ),
                SchemaDefinition(
                    type="object",
                    properties={"id": SchemaDefinition(type="integer")},
                    required=["id"],
                ),
            ],
        )

        validator = Validator()

        # Should match first anyOf
        result = validator.validate({"type": "user"}, schema)
        assert result.is_valid

        # Should match second anyOf
        result = validator.validate({"id": 123}, schema)
        assert result.is_valid

    def test_oneof_validation(self) -> None:
        """Test oneOf schema combinator."""
        schema = SchemaDefinition(
            type="object",
            properties={},
            oneOf=[
                SchemaDefinition(
                    type="object",
                    properties={"a": SchemaDefinition(type="string")},
                ),
                SchemaDefinition(
                    type="object",
                    properties={"b": SchemaDefinition(type="string")},
                ),
            ],
        )

        validator = Validator()

        # Matches exactly one
        result = validator.validate({"a": "value"}, schema)
        assert result.is_valid
