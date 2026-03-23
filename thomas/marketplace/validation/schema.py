"""
Schema definition, parsing, and compilation.
"""

from collections.abc import Callable
from typing import Any

from thomas.marketplace.validation._exceptions import CircularReferenceError, SchemaError
from thomas.marketplace.validation._types import SchemaDefinition


class Schema:
    """Schema wrapper and parser."""

    def __init__(self, definition: SchemaDefinition) -> None:
        """Initialize schema.

        Args:
            definition: SchemaDefinition instance.
        """
        self.definition = definition
        self._compiled: Callable | None = None

    @staticmethod
    def from_dict(schema_dict: dict[str, Any]) -> "Schema":
        """Parse schema from dictionary (JSON-Schema subset).

        Args:
            schema_dict: Dictionary with schema definition.

        Returns:
            Schema instance.

        Raises:
            SchemaError: If schema is invalid.
        """
        definition = SchemaParser.parse(schema_dict)
        return Schema(definition)

    @staticmethod
    def from_json(json_str: str) -> "Schema":
        """Parse schema from JSON string.

        Args:
            json_str: JSON string.

        Returns:
            Schema instance.

        Raises:
            SchemaError: If JSON or schema is invalid.
        """
        import json

        try:
            schema_dict = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise SchemaError(f"Invalid JSON: {str(e)}")
        return Schema.from_dict(schema_dict)

    def compile(self) -> Callable:
        """Compile schema for repeated validation.

        Returns:
            Compiled validator function.
        """
        if self._compiled is not None:
            return self._compiled

        from thomas.marketplace.validation.core import Validator

        validator = Validator()

        def compiled_validator(data: Any) -> bool:
            result = validator.validate(data, self.definition)
            return result.is_valid

        self._compiled = compiled_validator
        return self._compiled

    def validate(self, data: Any) -> Any:
        """Quick validation returning just validity.

        Args:
            data: Data to validate.

        Returns:
            True if valid, False otherwise.
        """
        from thomas.marketplace.validation.core import Validator

        validator = Validator()
        result = validator.validate(data, self.definition)
        return result.is_valid


class SchemaParser:
    """Parse JSON-Schema subset to SchemaDefinition."""

    @staticmethod
    def parse(schema_dict: dict[str, Any]) -> SchemaDefinition:
        """Parse schema dictionary.

        Args:
            schema_dict: Schema dictionary.

        Returns:
            SchemaDefinition.

        Raises:
            SchemaError: If schema is invalid.
        """
        if not isinstance(schema_dict, dict):
            raise SchemaError("Schema must be a dictionary")

        schema_type = schema_dict.get("type", "object")

        # Handle $ref
        if "$ref" in schema_dict:
            return SchemaDefinition(
                ref=schema_dict["$ref"],
                type=schema_type,
            )

        definition = SchemaDefinition(
            type=schema_type,
            title=schema_dict.get("title", ""),
            description=schema_dict.get("description", ""),
            nullable=schema_dict.get("nullable", False),
            default=schema_dict.get("default"),
        )

        # Parse properties (for objects)
        if "properties" in schema_dict:
            if not isinstance(schema_dict["properties"], dict):
                raise SchemaError("'properties' must be a dictionary")
            for prop_name, prop_schema in schema_dict["properties"].items():
                definition.properties[prop_name] = SchemaParser.parse(prop_schema)

        # Parse required
        if "required" in schema_dict:
            if not isinstance(schema_dict["required"], list):
                raise SchemaError("'required' must be a list")
            definition.required = schema_dict["required"]

        # Parse items (for arrays)
        if "items" in schema_dict:
            definition.items = SchemaParser.parse(schema_dict["items"])

        # Parse anyOf
        if "anyOf" in schema_dict:
            if not isinstance(schema_dict["anyOf"], list):
                raise SchemaError("'anyOf' must be a list")
            definition.anyOf = [SchemaParser.parse(s) for s in schema_dict["anyOf"]]

        # Parse oneOf
        if "oneOf" in schema_dict:
            if not isinstance(schema_dict["oneOf"], list):
                raise SchemaError("'oneOf' must be a list")
            definition.oneOf = [SchemaParser.parse(s) for s in schema_dict["oneOf"]]

        # Parse allOf
        if "allOf" in schema_dict:
            if not isinstance(schema_dict["allOf"], list):
                raise SchemaError("'allOf' must be a list")
            definition.allOf = [SchemaParser.parse(s) for s in schema_dict["allOf"]]

        # Store metadata
        definition.metadata = {
            k: v
            for k, v in schema_dict.items()
            if k
            not in (
                "type",
                "properties",
                "required",
                "items",
                "anyOf",
                "oneOf",
                "allOf",
                "title",
                "description",
                "nullable",
                "default",
                "$ref",
            )
        }

        return definition


class SchemaCompiler:
    """Compile schemas for efficient repeated validation."""

    def __init__(self) -> None:
        """Initialize compiler."""
        self._cache: dict[str, Callable] = {}

    def compile(self, schema: SchemaDefinition | dict[str, Any]) -> Callable:
        """Compile schema to validator function.

        Args:
            schema: SchemaDefinition or dict.

        Returns:
            Validator function: data -> bool.
        """
        from thomas.marketplace.validation.core import Validator

        if isinstance(schema, dict):
            schema = Schema.from_dict(schema).definition

        validator = Validator()

        def compiled(data: Any) -> bool:
            result = validator.validate(data, schema)
            return result.is_valid

        return compiled

    def cache(self, schema_id: str, schema: SchemaDefinition | dict[str, Any]) -> Callable:
        """Compile and cache schema.

        Args:
            schema_id: Unique schema identifier.
            schema: SchemaDefinition or dict.

        Returns:
            Cached validator function.
        """
        if schema_id not in self._cache:
            self._cache[schema_id] = self.compile(schema)
        return self._cache[schema_id]

    def clear_cache(self) -> None:
        """Clear the schema cache."""
        self._cache.clear()


class SchemaRegistry:
    """Registry for named schemas with reference resolution."""

    def __init__(self) -> None:
        """Initialize registry."""
        self._schemas: dict[str, SchemaDefinition] = {}
        self._compiled: dict[str, Callable] = {}

    def register(self, name: str, schema: SchemaDefinition | dict[str, Any]) -> None:
        """Register a named schema.

        Args:
            name: Schema name for referencing.
            schema: SchemaDefinition or dict.

        Raises:
            SchemaError: If schema is invalid.
        """
        if isinstance(schema, dict):
            schema = Schema.from_dict(schema).definition
        self._schemas[name] = schema

    def get(self, name: str) -> SchemaDefinition | None:
        """Retrieve a registered schema.

        Args:
            name: Schema name.

        Returns:
            SchemaDefinition or None if not found.
        """
        return self._schemas.get(name)

    def resolve_refs(self, schema: SchemaDefinition) -> SchemaDefinition:
        """Resolve all $ref references in a schema.

        Args:
            schema: Schema with possible $ref entries.

        Returns:
            Schema with references resolved.

        Raises:
            SchemaError: If reference not found.
            CircularReferenceError: If circular reference detected.
        """
        return self._resolve_refs_impl(schema, set())

    def _resolve_refs_impl(
        self,
        schema: SchemaDefinition,
        visited: set,
    ) -> SchemaDefinition:
        """Recursive reference resolution.

        Args:
            schema: Schema to resolve.
            visited: Set of visited reference names (for cycle detection).

        Returns:
            Resolved schema.

        Raises:
            SchemaError: If reference not found.
            CircularReferenceError: If circular reference detected.
        """
        if schema.ref:
            if schema.ref in visited:
                raise CircularReferenceError(list(visited) + [schema.ref])

            resolved = self.get(schema.ref)
            if resolved is None:
                raise SchemaError(f"Schema reference '{schema.ref}' not found in registry")

            new_visited = visited | {schema.ref}
            return self._resolve_refs_impl(resolved, new_visited)

        # Recursively resolve nested schemas
        resolved = SchemaDefinition(
            type=schema.type,
            title=schema.title,
            description=schema.description,
            nullable=schema.nullable,
            default=schema.default,
            required=schema.required.copy(),
            metadata=schema.metadata.copy(),
        )

        # Resolve properties
        for name, prop_schema in schema.properties.items():
            resolved.properties[name] = self._resolve_refs_impl(prop_schema, visited)

        # Resolve items
        if schema.items:
            resolved.items = self._resolve_refs_impl(schema.items, visited)

        # Resolve anyOf, oneOf, allOf
        resolved.anyOf = [self._resolve_refs_impl(s, visited) for s in schema.anyOf]
        resolved.oneOf = [self._resolve_refs_impl(s, visited) for s in schema.oneOf]
        resolved.allOf = [self._resolve_refs_impl(s, visited) for s in schema.allOf]

        # Copy rules
        resolved.rules = schema.rules.copy()

        return resolved

    def list_schemas(self) -> list[str]:
        """List all registered schema names.

        Returns:
            List of schema names.
        """
        return list(self._schemas.keys())

    def clear(self) -> None:
        """Clear all registered schemas and cache."""
        self._schemas.clear()
        self._compiled.clear()
