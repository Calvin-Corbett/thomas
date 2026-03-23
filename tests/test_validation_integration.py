"""
End-to-end integration tests for validation module.
"""

import pytest

from thomas.marketplace.validation._types import SchemaDefinition, ValidatorConfig
from thomas.marketplace.validation.coercion import CoercionConfig, TypeCoercer
from thomas.marketplace.validation.core import Validator
from thomas.marketplace.validation.decorators import schema_class, validate_args, validate_return
from thomas.marketplace.validation.formatters import ErrorGrouper, HumanErrorFormatter, JsonErrorFormatter
from thomas.marketplace.validation.sanitizers import InputSanitizer, SanitizerConfig
from thomas.marketplace.validation.schema import Schema, SchemaRegistry


class TestCompleteValidationPipeline:
    """Test complete validation pipeline."""

    def test_validate_coerce_sanitize(self) -> None:
        """Test validation with coercion and sanitization."""
        schema = Schema.from_dict(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                    "email": {"type": "string"},
                },
                "required": ["name", "age"],
            }
        )

        # Input with type mismatches
        dirty_data = {
            "name": "  <p>John</p>  ",
            "age": "30",
            "email": "john@example.com",
        }

        # Coerce types
        coercer = TypeCoercer(CoercionConfig(coerce_strings=True))
        coerced = {
            "name": coercer.coerce(dirty_data["name"], "string"),
            "age": coercer.coerce(dirty_data["age"], "integer"),
            "email": coercer.coerce(dirty_data["email"], "string"),
        }

        # Sanitize
        sanitizer = InputSanitizer(SanitizerConfig(strip_html=True, trim_whitespace=True))
        sanitized = sanitizer.sanitize_dict(coerced)

        # Validate
        validator = Validator()
        result = validator.validate(sanitized, schema.definition)

        assert result.is_valid
        assert sanitized["name"] == "John"
        assert sanitized["age"] == 30


class TestErrorFormatting:
    """Test error formatting and reporting."""

    def test_human_error_formatter(self) -> None:
        """Test human-readable error formatting."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
                "age": SchemaDefinition(type="integer"),
            },
            required=["name", "age"],
        )

        validator = Validator()
        result = validator.validate({}, schema)

        formatter = HumanErrorFormatter()
        output = formatter.format(result)

        assert "ERRORS" in output
        assert "required" in output.lower()

    def test_json_error_formatter(self) -> None:
        """Test JSON error formatting."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "value": SchemaDefinition(type="integer"),
            },
        )

        validator = Validator()
        result = validator.validate({"value": "invalid"}, schema)

        formatter = JsonErrorFormatter()
        json_output = formatter.format(result)

        assert "valid" in json_output
        assert "errors" in json_output

    def test_error_grouping(self) -> None:
        """Test error grouping."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "a": SchemaDefinition(type="integer"),
                "b": SchemaDefinition(type="integer"),
                "c": SchemaDefinition(type="integer"),
            },
            required=["a", "b", "c"],
        )

        validator = Validator()
        result = validator.validate({}, schema)

        grouped_by_field = ErrorGrouper.by_field(result)
        assert len(grouped_by_field) >= 3

        grouped_by_rule = ErrorGrouper.by_rule(result)
        assert "required" in grouped_by_rule


class TestSchemaRegistryIntegration:
    """Test schema registry with validation."""

    def test_complex_schema_with_references(self) -> None:
        """Test validation with schema references."""
        registry = SchemaRegistry()

        # Register base schemas
        address_schema = SchemaDefinition(
            type="object",
            properties={
                "street": SchemaDefinition(type="string"),
                "city": SchemaDefinition(type="string"),
            },
            required=["city"],
        )
        registry.register("address", address_schema)

        # Register user schema with address reference
        user_schema = SchemaDefinition(
            type="object",
            properties={
                "name": SchemaDefinition(type="string"),
                "address": SchemaDefinition(ref="address"),
            },
            required=["name"],
        )
        registry.register("user", user_schema)

        # Resolve and validate
        resolved = registry.resolve_refs(user_schema)
        validator = Validator()

        data = {
            "name": "John",
            "address": {
                "street": "123 Main",
                "city": "Boston",
            },
        }

        result = validator.validate(data, resolved)
        assert result.is_valid


class TestDecoratorValidation:
    """Test validation decorators."""

    def test_validate_args_decorator(self) -> None:
        """Test @validate_args decorator."""

        @validate_args(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
            }
        )
        def process_user(name: str, age: int = 0) -> str:
            return f"{name} is {age}"

        # Valid call
        result = process_user("John", age=30)
        assert "John" in result

        # Invalid call should raise
        from thomas.marketplace.validation._exceptions import ValidationException

        with pytest.raises(ValidationException):
            process_user(age=30)  # Missing required 'name'

    def test_validate_return_decorator(self) -> None:
        """Test @validate_return decorator."""

        @validate_return(
            {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                },
            }
        )
        def fetch_result() -> dict:
            return {"success": True, "message": "OK"}

        result = fetch_result()
        assert result["success"]

    def test_schema_class_decorator(self) -> None:
        """Test @schema_class decorator."""

        @schema_class(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                },
                "required": ["name", "email"],
            }
        )
        class User:
            def __init__(self, name: str, email: str):
                self.name = name
                self.email = email

        # Valid initialization
        user = User("John", "john@example.com")
        assert user.name == "John"

        # Invalid initialization should raise
        from thomas.marketplace.validation._exceptions import ValidationException

        with pytest.raises(ValidationException):
            User("John", 123)  # email should be string


class TestNestedValidationScenario:
    """Test validation of complex nested scenarios."""

    def test_nested_arrays_of_objects(self) -> None:
        """Test validation of nested arrays with objects."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "organization": SchemaDefinition(
                    type="object",
                    properties={
                        "name": SchemaDefinition(type="string"),
                        "departments": SchemaDefinition(
                            type="array",
                            items=SchemaDefinition(
                                type="object",
                                properties={
                                    "name": SchemaDefinition(type="string"),
                                    "employees": SchemaDefinition(
                                        type="array",
                                        items=SchemaDefinition(
                                            type="object",
                                            properties={
                                                "name": SchemaDefinition(type="string"),
                                                "role": SchemaDefinition(type="string"),
                                            },
                                            required=["name"],
                                        ),
                                    ),
                                },
                                required=["name"],
                            ),
                        ),
                    },
                    required=["name"],
                ),
            },
        )

        data = {
            "organization": {
                "name": "TechCorp",
                "departments": [
                    {
                        "name": "Engineering",
                        "employees": [
                            {"name": "Alice", "role": "Senior Engineer"},
                            {"name": "Bob", "role": "Junior Engineer"},
                        ],
                    },
                    {
                        "name": "Sales",
                        "employees": [
                            {"name": "Charlie", "role": "Sales Manager"},
                        ],
                    },
                ],
            },
        }

        validator = Validator()
        result = validator.validate(data, schema)

        assert result.is_valid
        assert len(result.errors) == 0

    def test_nested_validation_error_paths(self) -> None:
        """Test error path tracking in deeply nested structures."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "org": SchemaDefinition(
                    type="object",
                    properties={
                        "depts": SchemaDefinition(
                            type="array",
                            items=SchemaDefinition(
                                type="object",
                                properties={
                                    "empls": SchemaDefinition(
                                        type="array",
                                        items=SchemaDefinition(
                                            type="object",
                                            properties={
                                                "age": SchemaDefinition(type="integer"),
                                            },
                                        ),
                                    ),
                                },
                            ),
                        ),
                    },
                ),
            },
        )

        data = {
            "org": {
                "depts": [
                    {
                        "empls": [
                            {"age": "invalid"},
                        ],
                    },
                ],
            },
        }

        validator = Validator()
        result = validator.validate(data, schema)

        assert not result.is_valid
        error = result.errors[0]
        # Path should reflect nesting
        assert "org" in error.path or len(error.path) > 0


class TestLargeDatasetValidation:
    """Test validation performance with large datasets."""

    def test_validate_large_array(self) -> None:
        """Test validating large array of objects."""
        schema = SchemaDefinition(
            type="array",
            items=SchemaDefinition(
                type="object",
                properties={
                    "id": SchemaDefinition(type="integer"),
                    "name": SchemaDefinition(type="string"),
                    "score": SchemaDefinition(type="number"),
                },
                required=["id"],
            ),
        )

        # Create large dataset
        data = [{"id": i, "name": f"Item {i}", "score": 100 - i} for i in range(1000)]

        validator = Validator()
        result = validator.validate(data, schema)

        # Should be valid
        assert result.is_valid

    def test_large_array_with_some_errors(self) -> None:
        """Test error accumulation in large array."""
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

        # Create data with some missing IDs
        data = [{"id": i} if i % 100 != 0 else {"name": "missing_id"} for i in range(100)]

        validator = Validator()
        result = validator.validate(data, schema)

        assert not result.is_valid
        # Should have accumulated errors
        assert len(result.errors) >= 1


class TestConfigurationVariations:
    """Test validation with different configurations."""

    def test_strict_type_checking(self) -> None:
        """Test strict type checking."""
        schema = SchemaDefinition(
            type="object",
            properties={
                "count": SchemaDefinition(type="integer"),
            },
        )

        config = ValidatorConfig(strict_types=True, allow_coercion=False)
        validator = Validator(config)

        result = validator.validate({"count": "123"}, schema)
        # Should fail without coercion
        assert not result.is_valid

    def test_max_depth_limit(self) -> None:
        """Test maximum depth limit."""
        config = ValidatorConfig(max_object_depth=2)
        validator = Validator(config)

        schema = SchemaDefinition(
            type="object",
            properties={
                "level1": SchemaDefinition(
                    type="object",
                    properties={
                        "level2": SchemaDefinition(
                            type="object",
                            properties={
                                "level3": SchemaDefinition(type="string"),
                            },
                        ),
                    },
                ),
            },
        )

        data = {
            "level1": {
                "level2": {
                    "level3": "value",
                },
            },
        }

        result = validator.validate(data, schema)
        # Should fail due to depth limit
        assert not result.is_valid

    def test_max_errors_limit(self) -> None:
        """Test stopping after max errors."""
        config = ValidatorConfig(max_errors=3)
        validator = Validator(config)

        schema = SchemaDefinition(
            type="object",
            properties={
                "a": SchemaDefinition(type="integer"),
                "b": SchemaDefinition(type="integer"),
                "c": SchemaDefinition(type="integer"),
                "d": SchemaDefinition(type="integer"),
                "e": SchemaDefinition(type="integer"),
            },
        )

        result = validator.validate(
            {
                "a": "invalid",
                "b": "invalid",
                "c": "invalid",
                "d": "invalid",
                "e": "invalid",
            },
            schema,
        )

        # Should stop at max_errors
        assert result.error_count() <= 3
