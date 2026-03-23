"""Schema management with definitions, validation, migration, and versioning.

Provides schema definition, validation, migration, versioning, and diffing.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DataType(Enum):
    """Schema data types."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    TIMESTAMP = "timestamp"
    BINARY = "binary"


@dataclass
class Field:
    """Schema field definition."""

    name: str
    data_type: DataType
    required: bool = True
    default: Any = None
    description: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)

    def validate(self, value: Any) -> tuple[bool, str | None]:
        """Validate value."""
        if value is None:
            if self.required:
                return False, f"Field {self.name} is required"
            return True, None

        if self.data_type == DataType.STRING and not isinstance(value, str):
            return False, f"Field {self.name} must be string"
        elif self.data_type == DataType.INTEGER and not isinstance(value, int):
            return False, f"Field {self.name} must be integer"
        elif self.data_type == DataType.FLOAT and not isinstance(value, (int, float)):
            return False, f"Field {self.name} must be float"

        # Check constraints
        if "min_length" in self.constraints and len(str(value)) < self.constraints["min_length"]:
            return False, f"Field {self.name} min length constraint failed"

        return True, None


@dataclass
class Schema:
    """Data schema definition."""

    name: str
    version: str
    fields: list[Field] = field(default_factory=list)
    description: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_field(self, field: Field) -> None:
        """Add field to schema."""
        self.fields.append(field)

    def get_field(self, name: str) -> Field | None:
        """Get field by name."""
        for field in self.fields:
            if field.name == name:
                return field
        return None

    def validate_object(self, obj: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate object against schema."""
        errors = []

        for field in self.fields:
            if field.name not in obj:
                if field.required:
                    errors.append(f"Missing required field: {field.name}")
            else:
                valid, error = field.validate(obj[field.name])
                if not valid:
                    errors.append(error)

        return len(errors) == 0, errors

    def to_dict(self) -> dict[str, Any]:
        """Convert schema to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "fields": [
                {"name": f.name, "type": f.data_type.value, "required": f.required, "description": f.description}
                for f in self.fields
            ],
        }


class SchemaMigration:
    """Schema migration."""

    def __init__(self, from_version: str, to_version: str, migration_func: Callable):
        self.from_version = from_version
        self.to_version = to_version
        self.migration_func = migration_func
        self.created_at = datetime.utcnow()

    async def execute(self, data: dict[str, Any]) -> dict[str, Any]:
        """Execute migration."""
        return await self.migration_func(data)


class SchemaMigrationManager:
    """Manage schema migrations."""

    def __init__(self):
        self.migrations: dict[tuple[str, str], SchemaMigration] = {}
        self.migration_history: list[dict[str, Any]] = []

    def register_migration(self, migration: SchemaMigration) -> None:
        """Register migration."""
        key = (migration.from_version, migration.to_version)
        self.migrations[key] = migration

    async def migrate(self, data: dict[str, Any], from_version: str, to_version: str) -> dict[str, Any] | None:
        """Execute migration chain."""
        key = (from_version, to_version)
        migration = self.migrations.get(key)

        if not migration:
            return None

        try:
            result = await migration.execute(data)
            self.migration_history.append({"from": from_version, "to": to_version, "timestamp": datetime.utcnow()})
            return result
        except Exception:
            return None

    def get_migration_history(self) -> list[dict[str, Any]]:
        """Get migration history."""
        return self.migration_history.copy()


class SchemaRegistry:
    """Registry of schemas."""

    def __init__(self):
        self.schemas: dict[str, Schema] = {}
        self.versions: dict[str, list[str]] = {}

    def register_schema(self, schema: Schema) -> None:
        """Register schema."""
        self.schemas[schema.name] = schema

        if schema.name not in self.versions:
            self.versions[schema.name] = []
        self.versions[schema.name].append(schema.version)

    def get_schema(self, name: str, version: str | None = None) -> Schema | None:
        """Get schema by name and version."""
        schema = self.schemas.get(name)
        if schema and (version is None or schema.version == version):
            return schema
        return None

    def get_versions(self, name: str) -> list[str]:
        """Get available versions for schema."""
        return self.versions.get(name, [])

    def list_schemas(self) -> list[str]:
        """List all schemas."""
        return list(self.schemas.keys())


class SchemaDiff:
    """Compare schemas for differences."""

    @staticmethod
    def diff(schema1: Schema, schema2: Schema) -> dict[str, Any]:
        """Get differences between schemas."""
        added_fields = []
        removed_fields = []
        modified_fields = []

        names1 = {f.name: f for f in schema1.fields}
        names2 = {f.name: f for f in schema2.fields}

        for name in names2:
            if name not in names1:
                added_fields.append(name)

        for name in names1:
            if name not in names2:
                removed_fields.append(name)

        for name in names1:
            if name in names2:
                if names1[name].data_type != names2[name].data_type:
                    modified_fields.append(
                        {
                            "field": name,
                            "from_type": names1[name].data_type.value,
                            "to_type": names2[name].data_type.value,
                        }
                    )

        return {"added": added_fields, "removed": removed_fields, "modified": modified_fields}
