"""Schema management with validation, migration, and versioning.

Provides schema definition, validation, migration tracking,
version management, and diffing capabilities.
"""

from .core import (
    DataType,
    Field,
    Schema,
    SchemaDiff,
    SchemaMigration,
    SchemaMigrationManager,
    SchemaRegistry,
)

__all__ = [
    "DataType",
    "Field",
    "Schema",
    "SchemaMigration",
    "SchemaMigrationManager",
    "SchemaRegistry",
    "SchemaDiff",
]

__version__ = "1.0.0"
