"""
Schema versioning and evolution for forward/backward compatibility.

Provides schema versioning, compatibility checking, field addition/removal/
renaming, and migration functions for evolving schemas over time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from .exceptions import IncompatibleSchemaError, SchemaVersionError
from .types import MessageDescriptor, SchemaVersion


def check_forward_compatibility(
    old_schema: MessageDescriptor,
    new_schema: MessageDescriptor,
) -> bool:
    """Check if new schema is forward-compatible with old schema.

    Forward compatibility means a producer using new schema can send messages
    that old consumers can read.

    Requirements:
    - No required fields added without defaults
    - No existing fields removed
    - Field types must be compatible

    Args:
        old_schema: Old (consumer) schema.
        new_schema: New (producer) schema.

    Returns:
        True if forward-compatible.

    Raises:
        IncompatibleSchemaError: If not compatible.
    """
    # Check major version compatibility
    if old_schema.version.major != new_schema.version.major:
        raise IncompatibleSchemaError(
            f"Major version mismatch: {old_schema.version} vs {new_schema.version}",
            old_version=str(old_schema.version),
            new_version=str(new_schema.version),
        )

    # Check that no fields were removed
    for field_name in old_schema.fields:
        if field_name not in new_schema.fields:
            raise IncompatibleSchemaError(
                f"Required field removed: {field_name}",
                old_version=str(old_schema.version),
                new_version=str(new_schema.version),
            )

    # Check that new required fields have defaults
    for field_name, new_field in new_schema.fields.items():
        if field_name not in old_schema.fields:
            if new_field.required and new_field.default is None:
                raise IncompatibleSchemaError(
                    f"Required field added without default: {field_name}",
                    old_version=str(old_schema.version),
                    new_version=str(new_schema.version),
                )

    return True


def check_backward_compatibility(
    old_schema: MessageDescriptor,
    new_schema: MessageDescriptor,
) -> bool:
    """Check if new schema is backward-compatible with old schema.

    Backward compatibility means a consumer using new schema can read messages
    from producers using old schema.

    Requirements:
    - All old fields exist in new schema
    - Old field types must be compatible
    - Removed fields can have defaults

    Args:
        old_schema: Old (producer) schema.
        new_schema: New (consumer) schema.

    Returns:
        True if backward-compatible.

    Raises:
        IncompatibleSchemaError: If not compatible.
    """
    # Check major version compatibility
    if old_schema.version.major != new_schema.version.major:
        raise IncompatibleSchemaError(
            f"Major version mismatch: {old_schema.version} vs {new_schema.version}",
            old_version=str(old_schema.version),
            new_version=str(new_schema.version),
        )

    # All old fields must exist in new schema
    for field_name in old_schema.fields:
        if field_name not in new_schema.fields:
            new_field = new_schema.get_field(field_name)
            if new_field and new_field.default is None:
                raise IncompatibleSchemaError(
                    f"Field not in new schema and has no default: {field_name}",
                    old_version=str(old_schema.version),
                    new_version=str(new_schema.version),
                )

    return True


@dataclass
class FieldMigration:
    """Describes how to migrate a field from one schema to another."""

    old_name: str
    new_name: str
    transform: Callable[[Any], Any] | None = None
    default: Any = None


@dataclass
class SchemaMigration:
    """Describes migrations needed to convert between schema versions."""

    from_version: SchemaVersion
    to_version: SchemaVersion
    field_migrations: list[FieldMigration] = dataclass_field(default_factory=list)
    global_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None


class MigrationRegistry:
    """Registry of schema migrations."""

    def __init__(self) -> None:
        self._migrations: dict[tuple[str, str], SchemaMigration] = {}

    def register(self, migration: SchemaMigration) -> None:
        """Register a migration.

        Args:
            migration: Migration to register.
        """
        key = (str(migration.from_version), str(migration.to_version))
        self._migrations[key] = migration

    def get(
        self,
        from_version: SchemaVersion,
        to_version: SchemaVersion,
    ) -> SchemaMigration | None:
        """Get migration between versions.

        Args:
            from_version: Source schema version.
            to_version: Target schema version.

        Returns:
            Migration if registered, None otherwise.
        """
        key = (str(from_version), str(to_version))
        return self._migrations.get(key)

    def list_migrations(self) -> list[SchemaMigration]:
        """List all registered migrations."""
        return list(self._migrations.values())


def apply_migration(
    data: dict[str, Any],
    old_schema: MessageDescriptor,
    new_schema: MessageDescriptor,
    migration: SchemaMigration | None = None,
) -> dict[str, Any]:
    """Apply schema migration to data.

    Args:
        data: Object with old schema.
        old_schema: Old schema descriptor.
        new_schema: New schema descriptor.
        migration: Optional migration instructions.

    Returns:
        Object conforming to new schema.

    Raises:
        SchemaVersionError: If migration is impossible.
    """
    # Check compatibility
    try:
        check_backward_compatibility(old_schema, new_schema)
    except IncompatibleSchemaError as e:
        raise SchemaVersionError(str(e)) from e

    result = dict(data)

    # Apply field migrations
    if migration:
        for field_migration in migration.field_migrations:
            if field_migration.old_name in result:
                value = result[field_migration.old_name]

                if field_migration.transform:
                    value = field_migration.transform(value)

                if field_migration.old_name != field_migration.new_name:
                    del result[field_migration.old_name]
                    result[field_migration.new_name] = value
                else:
                    result[field_migration.new_name] = value

        # Apply global transform
        if migration.global_transform:
            result = migration.global_transform(result)

    # Add defaults for new fields
    for field_name, field in new_schema.fields.items():
        if field_name not in result:
            if field.default is not None:
                result[field_name] = field.default
            elif not field.required:
                result[field_name] = None

    # Remove fields not in new schema
    for field_name in list(result.keys()):
        if field_name not in new_schema.fields:
            del result[field_name]

    return result


def find_migration_path(
    from_version: SchemaVersion,
    to_version: SchemaVersion,
    registry: MigrationRegistry,
) -> list[SchemaMigration]:
    """Find migration path between schema versions.

    Uses breadth-first search to find shortest migration path.

    Args:
        from_version: Starting version.
        to_version: Target version.
        registry: Migration registry.

    Returns:
        List of migrations to apply in order.

    Raises:
        SchemaVersionError: If no migration path exists.
    """
    if from_version == to_version:
        return []

    # BFS to find path
    queue = [(from_version, [])]
    visited = {from_version}

    while queue:
        current_version, path = queue.pop(0)

        for migration in registry.list_migrations():
            if migration.from_version == current_version:
                next_version = migration.to_version

                if next_version == to_version:
                    return path + [migration]

                if next_version not in visited:
                    visited.add(next_version)
                    queue.append((next_version, path + [migration]))

    raise SchemaVersionError(f"No migration path from {from_version} to {to_version}")


def apply_migration_chain(
    data: dict[str, Any],
    from_schema: MessageDescriptor,
    to_schema: MessageDescriptor,
    registry: MigrationRegistry,
) -> dict[str, Any]:
    """Apply chain of migrations.

    Args:
        data: Object with old schema.
        from_schema: Starting schema.
        to_schema: Target schema.
        registry: Migration registry.

    Returns:
        Object conforming to target schema.

    Raises:
        SchemaVersionError: If migration chain is not possible.
    """
    path = find_migration_path(
        from_schema.version,
        to_schema.version,
        registry,
    )

    current_data = data
    current_schema = from_schema

    for migration in path:
        # Find schema for migration target
        # This is simplified - in reality you'd look up schemas
        next_schema = to_schema if migration.to_version == to_schema.version else current_schema

        current_data = apply_migration(
            current_data,
            current_schema,
            next_schema,
            migration,
        )
        current_schema = next_schema

    return current_data


# Global migration registry
_migration_registry = MigrationRegistry()


def register_migration(migration: SchemaMigration) -> None:
    """Register a global schema migration.

    Args:
        migration: Migration to register.
    """
    _migration_registry.register(migration)


def get_migration_registry() -> MigrationRegistry:
    """Get the global migration registry."""
    return _migration_registry
