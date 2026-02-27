"""
Tests for schema evolution and versioning.

Tests schema compatibility checking, field addition/removal/renaming,
migration functions, and version negotiation.
"""

import pytest

from thomas.serialization import (
    FieldDescriptor,
    MessageDescriptor,
    SchemaVersion,
)
from thomas.serialization.schema_evolution import (
    FieldMigration,
    IncompatibleSchemaError,
    MigrationRegistry,
    SchemaMigration,
    SchemaVersionError,
    apply_migration,
    check_backward_compatibility,
    check_forward_compatibility,
    find_migration_path,
)


class TestSchemaVersioning:
    """Tests for schema versioning."""

    def test_schema_version_comparison(self):
        """Test schema version comparison."""
        v1 = SchemaVersion(1, 0, 0)
        v2 = SchemaVersion(1, 1, 0)
        v3 = SchemaVersion(2, 0, 0)

        assert v1 < v2
        assert v2 < v3
        assert v1 <= v1
        assert v3 > v1
        assert v1 == SchemaVersion(1, 0, 0)

    def test_schema_version_string(self):
        """Test schema version string representation."""
        v = SchemaVersion(1, 2, 3)
        assert str(v) == "1.2.3"

    def test_version_compatibility(self):
        """Test major version compatibility check."""
        v1_0 = SchemaVersion(1, 0, 0)
        v1_1 = SchemaVersion(1, 1, 0)
        v2_0 = SchemaVersion(2, 0, 0)

        assert v1_0.is_compatible_with(v1_1)
        assert not v1_0.is_compatible_with(v2_0)


class TestForwardCompatibility:
    """Tests for forward compatibility checking."""

    def test_compatible_field_addition(self):
        """Test that adding optional field is forward-compatible."""
        old_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        new_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                    required=False,
                    default=0,
                ),
            },
        )

        assert check_forward_compatibility(old_schema, new_schema) is True

    def test_incompatible_required_field_addition(self):
        """Test that adding required field without default is incompatible."""
        old_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        new_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                    required=True,
                ),
            },
        )

        with pytest.raises(IncompatibleSchemaError):
            check_forward_compatibility(old_schema, new_schema)

    def test_incompatible_field_removal(self):
        """Test that removing field is incompatible."""
        old_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                ),
            },
        )

        new_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        with pytest.raises(IncompatibleSchemaError):
            check_forward_compatibility(old_schema, new_schema)


class TestBackwardCompatibility:
    """Tests for backward compatibility checking."""

    def test_compatible_field_removal(self):
        """Test that removing field with default is backward-compatible."""
        old_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                ),
            },
        )

        new_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                    default=0,
                ),
            },
        )

        assert check_backward_compatibility(old_schema, new_schema) is True

    def test_incompatible_major_version(self):
        """Test that major version change is incompatible."""
        old_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(1, 0, 0),
            fields={},
        )

        new_schema = MessageDescriptor(
            name="Test",
            version=SchemaVersion(2, 0, 0),
            fields={},
        )

        with pytest.raises(IncompatibleSchemaError):
            check_backward_compatibility(old_schema, new_schema)


class TestSchemaMigration:
    """Tests for schema migration."""

    def test_simple_field_addition(self):
        """Test migrating data with field addition."""
        old_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        new_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "age": FieldDescriptor(
                    name="age",
                    field_type="int32",
                    tag=2,
                    default=0,
                ),
            },
        )

        old_data = {"name": "Alice"}
        new_data = apply_migration(old_data, old_schema, new_schema)

        assert new_data["name"] == "Alice"
        assert new_data["age"] == 0

    def test_field_removal_with_default(self):
        """Test migrating data with field removal."""
        old_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 0, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                ),
                "deprecated_field": FieldDescriptor(
                    name="deprecated_field",
                    field_type="string",
                    tag=2,
                ),
            },
        )

        new_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        old_data = {"name": "Alice", "deprecated_field": "old"}
        new_data = apply_migration(old_data, old_schema, new_schema)

        assert new_data["name"] == "Alice"
        assert "deprecated_field" not in new_data

    def test_field_renaming(self):
        """Test migrating data with field renaming."""
        old_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 0, 0),
            fields={
                "full_name": FieldDescriptor(
                    name="full_name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        new_schema = MessageDescriptor(
            name="Person",
            version=SchemaVersion(1, 1, 0),
            fields={
                "name": FieldDescriptor(
                    name="name",
                    field_type="string",
                    tag=1,
                )
            },
        )

        migration = SchemaMigration(
            from_version=old_schema.version,
            to_version=new_schema.version,
            field_migrations=[
                FieldMigration(
                    old_name="full_name",
                    new_name="name",
                )
            ],
        )

        old_data = {"full_name": "Alice Smith"}
        new_data = apply_migration(old_data, old_schema, new_schema, migration)

        assert new_data["name"] == "Alice Smith"
        assert "full_name" not in new_data

    def test_field_transformation(self):
        """Test migrating data with field value transformation."""
        old_schema = MessageDescriptor(
            name="Record",
            version=SchemaVersion(1, 0, 0),
            fields={
                "price_cents": FieldDescriptor(
                    name="price_cents",
                    field_type="int32",
                    tag=1,
                )
            },
        )

        new_schema = MessageDescriptor(
            name="Record",
            version=SchemaVersion(1, 1, 0),
            fields={
                "price_dollars": FieldDescriptor(
                    name="price_dollars",
                    field_type="float",
                    tag=1,
                )
            },
        )

        migration = SchemaMigration(
            from_version=old_schema.version,
            to_version=new_schema.version,
            field_migrations=[
                FieldMigration(
                    old_name="price_cents",
                    new_name="price_dollars",
                    transform=lambda x: x / 100.0,
                )
            ],
        )

        old_data = {"price_cents": 1599}
        new_data = apply_migration(old_data, old_schema, new_schema, migration)

        assert new_data["price_dollars"] == 15.99


class TestMigrationRegistry:
    """Tests for migration registry."""

    def test_register_and_get_migration(self):
        """Test registering and retrieving migrations."""
        registry = MigrationRegistry()

        migration = SchemaMigration(
            from_version=SchemaVersion(1, 0, 0),
            to_version=SchemaVersion(1, 1, 0),
        )

        registry.register(migration)

        retrieved = registry.get(
            SchemaVersion(1, 0, 0),
            SchemaVersion(1, 1, 0),
        )

        assert retrieved is migration

    def test_migration_not_found(self):
        """Test getting non-existent migration."""
        registry = MigrationRegistry()

        result = registry.get(
            SchemaVersion(1, 0, 0),
            SchemaVersion(2, 0, 0),
        )

        assert result is None

    def test_list_migrations(self):
        """Test listing all migrations."""
        registry = MigrationRegistry()

        m1 = SchemaMigration(
            from_version=SchemaVersion(1, 0, 0),
            to_version=SchemaVersion(1, 1, 0),
        )
        m2 = SchemaMigration(
            from_version=SchemaVersion(1, 1, 0),
            to_version=SchemaVersion(1, 2, 0),
        )

        registry.register(m1)
        registry.register(m2)

        migrations = registry.list_migrations()
        assert len(migrations) == 2


class TestMigrationPath:
    """Tests for finding migration paths."""

    def test_find_direct_path(self):
        """Test finding direct migration path."""
        registry = MigrationRegistry()

        migration = SchemaMigration(
            from_version=SchemaVersion(1, 0, 0),
            to_version=SchemaVersion(1, 1, 0),
        )
        registry.register(migration)

        path = find_migration_path(
            SchemaVersion(1, 0, 0),
            SchemaVersion(1, 1, 0),
            registry,
        )

        assert len(path) == 1
        assert path[0] is migration

    def test_find_chained_path(self):
        """Test finding chained migration path."""
        registry = MigrationRegistry()

        m1 = SchemaMigration(
            from_version=SchemaVersion(1, 0, 0),
            to_version=SchemaVersion(1, 1, 0),
        )
        m2 = SchemaMigration(
            from_version=SchemaVersion(1, 1, 0),
            to_version=SchemaVersion(1, 2, 0),
        )

        registry.register(m1)
        registry.register(m2)

        path = find_migration_path(
            SchemaVersion(1, 0, 0),
            SchemaVersion(1, 2, 0),
            registry,
        )

        assert len(path) == 2

    def test_no_migration_path(self):
        """Test error when no migration path exists."""
        registry = MigrationRegistry()

        with pytest.raises(SchemaVersionError):
            find_migration_path(
                SchemaVersion(1, 0, 0),
                SchemaVersion(2, 0, 0),
                registry,
            )

    def test_same_version_path(self):
        """Test path when source and target are same."""
        registry = MigrationRegistry()

        path = find_migration_path(
            SchemaVersion(1, 0, 0),
            SchemaVersion(1, 0, 0),
            registry,
        )

        assert len(path) == 0
