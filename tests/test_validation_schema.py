"""
Tests for schema definition and parsing.
"""

import pytest

from thomas.marketplace.validation._exceptions import CircularReferenceError, SchemaError
from thomas.marketplace.validation._types import SchemaDefinition
from thomas.marketplace.validation.schema import Schema, SchemaCompiler, SchemaParser, SchemaRegistry


class TestSchemaParser:
    """Test schema parsing from dict."""

    def test_parse_simple_object(self) -> None:
        """Test parsing simple object schema."""
        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }

        schema = SchemaParser.parse(schema_dict)

        assert schema.type == "object"
        assert "name" in schema.properties
        assert "age" in schema.properties
        assert "name" in schema.required

    def test_parse_array(self) -> None:
        """Test parsing array schema."""
        schema_dict = {
            "type": "array",
            "items": {"type": "string"},
        }

        schema = SchemaParser.parse(schema_dict)

        assert schema.type == "array"
        assert schema.items is not None
        assert schema.items.type == "string"

    def test_parse_with_metadata(self) -> None:
        """Test parsing schema with metadata."""
        schema_dict = {
            "type": "object",
            "title": "User",
            "description": "A user object",
            "properties": {},
            "custom_field": "custom_value",
        }

        schema = SchemaParser.parse(schema_dict)

        assert schema.title == "User"
        assert schema.description == "A user object"
        assert "custom_field" in schema.metadata

    def test_parse_nested_properties(self) -> None:
        """Test parsing nested properties."""
        schema_dict = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
        }

        schema = SchemaParser.parse(schema_dict)

        assert schema.properties["user"].type == "object"
        assert "name" in schema.properties["user"].properties

    def test_parse_invalid_not_dict(self) -> None:
        """Test parsing fails with non-dict input."""
        with pytest.raises(SchemaError):
            SchemaParser.parse("not a dict")  # type: ignore

    def test_parse_anyof_oneof_allof(self) -> None:
        """Test parsing with anyOf, oneOf, allOf."""
        schema_dict = {
            "type": "object",
            "anyOf": [
                {"type": "string"},
                {"type": "integer"},
            ],
        }

        schema = SchemaParser.parse(schema_dict)

        assert len(schema.anyOf) == 2


class TestSchemaFromJson:
    """Test Schema creation from JSON."""

    def test_from_json_string(self) -> None:
        """Test creating schema from JSON string."""
        json_str = '{"type": "object", "properties": {"name": {"type": "string"}}}'
        schema = Schema.from_json(json_str)

        assert schema.definition.type == "object"
        assert "name" in schema.definition.properties

    def test_from_json_invalid(self) -> None:
        """Test from_json with invalid JSON."""
        with pytest.raises(SchemaError):
            Schema.from_json("invalid json {")

    def test_from_dict(self) -> None:
        """Test creating schema from dict."""
        schema_dict = {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
            },
        }

        schema = Schema.from_dict(schema_dict)

        assert schema.definition.type == "object"


class TestSchemaValidation:
    """Test schema validation using Schema class."""

    def test_schema_validate(self) -> None:
        """Test schema validation method."""
        schema = Schema.from_dict(
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            }
        )

        assert schema.validate({"name": "John"})
        assert not schema.validate({})

    def test_schema_compile(self) -> None:
        """Test schema compilation."""
        schema = Schema.from_dict(
            {
                "type": "object",
                "properties": {
                    "age": {"type": "integer"},
                },
            }
        )

        validator = schema.compile()

        assert validator({"age": 30})
        assert not validator({"age": "thirty"})


class TestSchemaCompiler:
    """Test schema compilation and caching."""

    def test_compile_schema(self) -> None:
        """Test compiling a schema."""
        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }

        compiler = SchemaCompiler()
        validator = compiler.compile(schema_dict)

        assert validator({"name": "John"})

    def test_cache_schema(self) -> None:
        """Test caching compiled schemas."""
        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }

        compiler = SchemaCompiler()
        validator1 = compiler.cache("user_schema", schema_dict)
        validator2 = compiler.cache("user_schema", schema_dict)

        # Should return same cached instance
        assert validator1 is validator2

    def test_clear_cache(self) -> None:
        """Test clearing compiler cache."""
        schema_dict = {"type": "object"}

        compiler = SchemaCompiler()
        compiler.cache("schema1", schema_dict)
        compiler.cache("schema2", schema_dict)

        assert len(compiler._cache) >= 2

        compiler.clear_cache()
        assert len(compiler._cache) == 0


class TestSchemaRegistry:
    """Test schema registry for references."""

    def test_register_and_get_schema(self) -> None:
        """Test registering and retrieving schemas."""
        registry = SchemaRegistry()

        schema_dict = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        }

        registry.register("user", schema_dict)
        retrieved = registry.get("user")

        assert retrieved is not None
        assert retrieved.type == "object"

    def test_list_schemas(self) -> None:
        """Test listing registered schemas."""
        registry = SchemaRegistry()

        registry.register("user", {"type": "object"})
        registry.register("post", {"type": "object"})

        schemas = registry.list_schemas()

        assert "user" in schemas
        assert "post" in schemas

    def test_resolve_simple_ref(self) -> None:
        """Test resolving a simple schema reference."""
        registry = SchemaRegistry()

        user_schema = SchemaDefinition(
            type="object",
            properties={"name": SchemaDefinition(type="string")},
        )
        registry.register("user", user_schema)

        ref_schema = SchemaDefinition(ref="user")
        resolved = registry.resolve_refs(ref_schema)

        assert resolved.type == "object"
        assert "name" in resolved.properties

    def test_resolve_nested_refs(self) -> None:
        """Test resolving nested references."""
        registry = SchemaRegistry()

        # Register base schema
        base = SchemaDefinition(
            type="object",
            properties={"id": SchemaDefinition(type="integer")},
        )
        registry.register("base", base)

        # Schema that references base
        user = SchemaDefinition(
            type="object",
            properties={"base": SchemaDefinition(ref="base")},
        )
        registry.register("user", user)

        # Resolve user
        resolved = registry.resolve_refs(user)

        assert resolved.properties["base"].type == "object"
        assert "id" in resolved.properties["base"].properties

    def test_circular_reference_error(self) -> None:
        """Test detection of circular references."""
        registry = SchemaRegistry()

        # Create circular reference
        a = SchemaDefinition(ref="b")
        b = SchemaDefinition(ref="a")

        registry.register("a", a)
        registry.register("b", b)

        with pytest.raises(CircularReferenceError):
            registry.resolve_refs(a)

    def test_missing_reference_error(self) -> None:
        """Test error on missing reference."""
        registry = SchemaRegistry()

        schema = SchemaDefinition(ref="nonexistent")

        with pytest.raises(SchemaError):
            registry.resolve_refs(schema)

    def test_clear_registry(self) -> None:
        """Test clearing registry."""
        registry = SchemaRegistry()

        registry.register("schema1", {"type": "object"})
        registry.register("schema2", {"type": "object"})

        assert len(registry.list_schemas()) >= 2

        registry.clear()

        assert len(registry.list_schemas()) == 0


class TestSchemaNullable:
    """Test schema nullable handling."""

    def test_nullable_true(self) -> None:
        """Test schema with nullable=true."""
        schema_dict = {
            "type": "string",
            "nullable": True,
        }

        schema = Schema.from_dict(schema_dict)
        assert schema.validate(None)
        assert schema.validate("value")

    def test_nullable_false(self) -> None:
        """Test schema with nullable=false."""
        schema_dict = {
            "type": "string",
            "nullable": False,
        }

        schema = Schema.from_dict(schema_dict)
        assert not schema.validate(None)
        assert schema.validate("value")


class TestSchemaDefaults:
    """Test schema default values."""

    def test_schema_default_value(self) -> None:
        """Test schema with default value."""
        schema_dict = {
            "type": "string",
            "default": "default_value",
        }

        schema = SchemaParser.parse(schema_dict)
        assert schema.default == "default_value"
