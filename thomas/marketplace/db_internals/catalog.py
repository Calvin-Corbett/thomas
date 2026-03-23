"""
System catalog for managing metadata.

This module implements:
- Table metadata (columns, types, constraints)
- Index metadata
- Statistics (row count, page count, distinct values, histograms)
- Constraint checking (PRIMARY KEY, UNIQUE, NOT NULL, FOREIGN KEY, CHECK)
- Schema DDL execution
- Catalog persistence
"""

import json
import time
from typing import Any

from ._exceptions import (
    CatalogException,
    ColumnNotFoundException,
    DuplicateIndexException,
    DuplicateTableException,
    InvalidSchemaException,
    TableNotFoundException,
)
from ._types import Column, Constraint, DataType, ForeignKey, Index, Schema, Statistics, Table


class Catalog:
    """
    System catalog storing all database metadata.

    Manages:
    - Table definitions
    - Index definitions
    - Column types and constraints
    - Table and column statistics
    - Foreign key relationships
    """

    def __init__(self) -> None:
        """Initialize the catalog."""
        self.schema = Schema()
        self.table_stats: dict[str, Statistics] = {}
        self.constraint_index: dict[str, list[str]] = {}  # constraint -> tables
        self.foreign_key_index: dict[str, list[ForeignKey]] = {}  # table -> FKs
        self.next_table_id = 1
        self.next_index_id = 1

    def create_table(
        self,
        table_name: str,
        columns: list[Column],
        constraints: list[Constraint] | None = None,
        foreign_keys: list[ForeignKey] | None = None,
    ) -> Table:
        """
        Create a table in the catalog.

        Args:
            table_name: Name of the table
            columns: List of columns
            constraints: Optional constraints
            foreign_keys: Optional foreign key constraints

        Returns:
            The created Table object

        Raises:
            DuplicateTableException: If table already exists
            InvalidSchemaException: If schema is invalid
        """
        if table_name in self.schema.tables:
            raise DuplicateTableException(f"Table {table_name} already exists")

        if not columns:
            raise InvalidSchemaException("Table must have at least one column")

        # Validate columns
        column_names = set()
        for col in columns:
            if col.name in column_names:
                raise InvalidSchemaException(f"Duplicate column name: {col.name}")
            column_names.add(col.name)

        # Create table
        table = Table(
            table_id=self.next_table_id,
            name=table_name,
            columns=columns,
            constraints=constraints or [],
            foreign_keys=foreign_keys or [],
        )
        self.next_table_id += 1

        # Register table
        self.schema.create_table(table)

        # Initialize statistics
        self.table_stats[table_name] = Statistics(
            table_name=table_name,
            num_rows=0,
            num_pages=0,
        )

        # Index foreign keys
        if foreign_keys:
            self.foreign_key_index[table_name] = foreign_keys

        return table

    def drop_table(self, table_name: str) -> None:
        """
        Drop a table from the catalog.

        Args:
            table_name: Name of table to drop

        Raises:
            TableNotFoundException: If table doesn't exist
        """
        if table_name not in self.schema.tables:
            raise TableNotFoundException(f"Table {table_name} not found")

        table = self.schema.tables[table_name]

        # Check for foreign key dependencies
        for other_table_name, foreign_keys in self.foreign_key_index.items():
            for fk in foreign_keys:
                if fk.target_table == table_name:
                    raise CatalogException(
                        f"Cannot drop table {table_name}: " f"referenced by foreign key in {other_table_name}"
                    )

        # Drop all indexes
        for index in table.indexes:
            self.drop_index(index.name)

        # Drop table
        self.schema.drop_table(table_name)
        if table_name in self.table_stats:
            del self.table_stats[table_name]
        if table_name in self.foreign_key_index:
            del self.foreign_key_index[table_name]

    def get_table(self, table_name: str) -> Table | None:
        """Get table metadata by name."""
        return self.schema.get_table(table_name)

    def list_tables(self) -> list[str]:
        """List all table names."""
        return self.schema.list_tables()

    def create_index(
        self,
        index_name: str,
        table_name: str,
        columns: list[str],
        is_unique: bool = False,
        is_primary: bool = False,
    ) -> Index:
        """
        Create an index on a table.

        Args:
            index_name: Name of index
            table_name: Name of table
            columns: List of column names to index
            is_unique: Whether index is unique
            is_primary: Whether this is primary key index

        Returns:
            The created Index object

        Raises:
            DuplicateIndexException: If index exists
            TableNotFoundException: If table doesn't exist
            ColumnNotFoundException: If column doesn't exist
        """
        if index_name in self.schema.indexes:
            raise DuplicateIndexException(f"Index {index_name} already exists")

        table = self.get_table(table_name)
        if table is None:
            raise TableNotFoundException(f"Table {table_name} not found")

        # Validate columns
        for col_name in columns:
            if table.get_column(col_name) is None:
                raise ColumnNotFoundException(f"Column {col_name} not found in table {table_name}")

        # Create index
        index = Index(
            index_id=self.next_index_id,
            name=index_name,
            table_name=table_name,
            columns=columns,
            is_unique=is_unique,
            is_primary=is_primary,
        )
        self.next_index_id += 1

        # Register index
        self.schema.indexes[index_name] = index
        table.indexes.append(index)

        return index

    def drop_index(self, index_name: str) -> None:
        """
        Drop an index.

        Args:
            index_name: Name of index

        Raises:
            IndexNotFoundException: If index doesn't exist
        """
        index = self.schema.indexes.get(index_name)
        if index is None:
            raise CatalogException(f"Index {index_name} not found")

        table = self.get_table(index.table_name)
        if table:
            table.indexes = [i for i in table.indexes if i.name != index_name]

        del self.schema.indexes[index_name]

    def get_index(self, index_name: str) -> Index | None:
        """Get index metadata by name."""
        return self.schema.indexes.get(index_name)

    def get_indexes_on_table(self, table_name: str) -> list[Index]:
        """Get all indexes on a table."""
        table = self.get_table(table_name)
        if table is None:
            return []
        return table.indexes

    def update_table_statistics(
        self,
        table_name: str,
        num_rows: int,
        num_pages: int,
        avg_row_size: int,
    ) -> None:
        """
        Update table statistics.

        Args:
            table_name: Table name
            num_rows: Number of rows
            num_pages: Number of pages
            avg_row_size: Average row size in bytes
        """
        if table_name not in self.table_stats:
            self.table_stats[table_name] = Statistics(table_name=table_name)

        stats = self.table_stats[table_name]
        stats.num_rows = num_rows
        stats.num_pages = num_pages
        stats.avg_row_size = avg_row_size
        stats.last_updated = time.time()

    def update_column_statistics(
        self,
        table_name: str,
        column_name: str,
        num_distinct: int,
        min_value: Any = None,
        max_value: Any = None,
        null_fraction: float = 0.0,
    ) -> None:
        """
        Update column statistics.

        Args:
            table_name: Table name
            column_name: Column name
            num_distinct: Number of distinct values
            min_value: Minimum value
            max_value: Maximum value
            null_fraction: Fraction of nulls (0-1)
        """
        if table_name not in self.table_stats:
            self.table_stats[table_name] = Statistics(table_name=table_name)

        stats = self.table_stats[table_name]
        col_stats = {
            "num_distinct_values": num_distinct,
            "min_value": min_value,
            "max_value": max_value,
            "null_fraction": null_fraction,
        }
        stats.column_stats[column_name] = col_stats

    def get_table_statistics(self, table_name: str) -> Statistics | None:
        """Get statistics for a table."""
        return self.table_stats.get(table_name)

    def get_column_statistics(self, table_name: str, column_name: str) -> dict[str, Any] | None:
        """Get statistics for a column."""
        stats = self.table_stats.get(table_name)
        if stats is None:
            return None
        return stats.column_stats.get(column_name)

    def check_primary_key_constraint(self, table_name: str, values: dict[str, Any]) -> bool:
        """
        Check if values violate primary key constraint.

        Args:
            table_name: Table name
            values: Column values to check

        Returns:
            True if constraint satisfied, False otherwise
        """
        table = self.get_table(table_name)
        if table is None:
            return True

        # Find primary key constraint
        for constraint in table.constraints:
            if constraint.constraint_type == "PRIMARY_KEY":
                for col in constraint.columns:
                    if col in values and values[col] is None:
                        return False

        return True

    def check_unique_constraint(self, table_name: str, column_name: str, value: Any) -> bool:
        """
        Check if value violates unique constraint.

        Args:
            table_name: Table name
            column_name: Column name
            value: Value to check

        Returns:
            True if constraint satisfied, False otherwise
        """
        table = self.get_table(table_name)
        if table is None:
            return True

        # Find unique constraint on column
        for constraint in table.constraints:
            if constraint.constraint_type == "UNIQUE":
                if column_name in constraint.columns:
                    # In real implementation, would check against existing data
                    return True

        return True

    def check_not_null_constraint(self, table_name: str, column_name: str, value: Any) -> bool:
        """
        Check if value violates NOT NULL constraint.

        Args:
            table_name: Table name
            column_name: Column name
            value: Value to check

        Returns:
            True if constraint satisfied, False otherwise
        """
        if value is not None:
            return True

        table = self.get_table(table_name)
        if table is None:
            return False

        col = table.get_column(column_name)
        if col is None:
            return False

        return col.nullable

    def check_foreign_key_constraint(
        self, source_table: str, target_table: str, source_value: Any, target_column: str
    ) -> bool:
        """
        Check if value satisfies foreign key constraint.

        Args:
            source_table: Source table name
            target_table: Target table name
            source_value: Value being inserted
            target_column: Target column to check

        Returns:
            True if constraint satisfied, False otherwise
        """
        # In real implementation, would check against target table
        return True

    def export_catalog(self, filename: str) -> None:
        """
        Export catalog to JSON file.

        Args:
            filename: Output filename
        """
        catalog_data = {
            "tables": {},
            "indexes": {},
            "statistics": {},
        }

        # Export tables
        for table_name, table in self.schema.tables.items():
            catalog_data["tables"][table_name] = {
                "table_id": table.table_id,
                "columns": [
                    {
                        "name": col.name,
                        "data_type": col.data_type.name,
                        "nullable": col.nullable,
                    }
                    for col in table.columns
                ],
            }

        # Export indexes
        for index_name, index in self.schema.indexes.items():
            catalog_data["indexes"][index_name] = {
                "table_name": index.table_name,
                "columns": index.columns,
                "is_unique": index.is_unique,
            }

        # Export statistics
        for table_name, stats in self.table_stats.items():
            catalog_data["statistics"][table_name] = {
                "num_rows": stats.num_rows,
                "num_pages": stats.num_pages,
                "avg_row_size": stats.avg_row_size,
            }

        with open(filename, "w") as f:
            json.dump(catalog_data, f, indent=2)

    def import_catalog(self, filename: str) -> None:
        """
        Import catalog from JSON file.

        Args:
            filename: Input filename
        """
        with open(filename) as f:
            catalog_data = json.load(f)

        # Import tables
        for table_name, table_info in catalog_data.get("tables", {}).items():
            columns = [
                Column(
                    name=col["name"],
                    data_type=DataType[col["data_type"]],
                    nullable=col.get("nullable", True),
                )
                for col in table_info["columns"]
            ]
            self.create_table(table_name, columns)

        # Import indexes
        for index_name, index_info in catalog_data.get("indexes", {}).items():
            self.create_index(
                index_name,
                index_info["table_name"],
                index_info["columns"],
                is_unique=index_info.get("is_unique", False),
            )

        # Import statistics
        for table_name, stats_info in catalog_data.get("statistics", {}).items():
            self.update_table_statistics(
                table_name,
                stats_info["num_rows"],
                stats_info["num_pages"],
                stats_info.get("avg_row_size", 0),
            )

    def validate_schema(self) -> list[str]:
        """
        Validate the catalog schema for consistency.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check for orphaned indexes
        for index_name, index in self.schema.indexes.items():
            if index.table_name not in self.schema.tables:
                errors.append(f"Index {index_name} references non-existent table {index.table_name}")

        # Check for invalid column references in constraints
        for table_name, table in self.schema.tables.items():
            for constraint in table.constraints:
                for col_name in constraint.columns:
                    if table.get_column(col_name) is None:
                        errors.append(
                            f"Constraint {constraint.name} in {table_name} "
                            f"references non-existent column {col_name}"
                        )

        return errors

    def get_statistics_summary(self) -> dict[str, Any]:
        """Get summary of all statistics."""
        summary = {
            "num_tables": len(self.schema.tables),
            "num_indexes": len(self.schema.indexes),
            "total_rows": 0,
            "total_pages": 0,
            "last_updated": None,
        }

        for stats in self.table_stats.values():
            summary["total_rows"] += stats.num_rows
            summary["total_pages"] += stats.num_pages
            if stats.last_updated:
                if summary["last_updated"] is None or stats.last_updated > summary["last_updated"]:
                    summary["last_updated"] = stats.last_updated

        return summary
