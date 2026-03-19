"""
Data transformations for the pipeline framework.

Implements various transformations including map, filter, field operations,
type casting, date handling, joins, pivoting, and deduplication.
"""

import math
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from thomas.core.safe_expression import SafeExpressionError, evaluate_safe_expression
from thomas.data_pipeline._exceptions import TransformationError
from thomas.data_pipeline._types import (
    DataType,
    Field,
    JoinSpec,
    JoinType,
    Record,
    Schema,
    Transform,
)


class MapTransform(Transform):
    """Maps a function over each record."""

    def __init__(self, func: Callable[[Record], Record]) -> None:
        """
        Initialize map transform.

        Args:
            func: Function that transforms a record
        """
        self.func = func

    def transform(self, record: Record) -> Record:
        """Apply function to record."""
        try:
            return self.func(record)
        except Exception as e:
            raise TransformationError(f"Map function failed: {e}", transform_name="MapTransform")

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Map preserves schema."""
        return input_schema


class FlatMapTransform(Transform):
    """Flat maps a function over each record, producing zero or more outputs."""

    def __init__(self, func: Callable[[Record], list[Record]]) -> None:
        """
        Initialize flat map transform.

        Args:
            func: Function that transforms a record to list of records
        """
        self.func = func

    def transform(self, record: Record) -> list[Record]:
        """Apply function to record."""
        try:
            result = self.func(record)
            return result if isinstance(result, list) else [result]
        except Exception as e:
            raise TransformationError(f"FlatMap function failed: {e}", transform_name="FlatMapTransform")

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """FlatMap preserves schema."""
        return input_schema


class FilterTransform(Transform):
    """Filters records based on a predicate."""

    def __init__(self, predicate: Callable[[Record], bool]) -> None:
        """
        Initialize filter transform.

        Args:
            predicate: Function that returns True for records to keep
        """
        self.predicate = predicate

    def transform(self, record: Record) -> Record | None:
        """Apply filter to record."""
        try:
            if self.predicate(record):
                return record
            return None
        except Exception as e:
            raise TransformationError(f"Filter predicate failed: {e}", transform_name="FilterTransform")

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Filter preserves schema."""
        return input_schema


class FieldRenameTransform(Transform):
    """Renames fields in records."""

    def __init__(self, rename_map: dict[str, str]) -> None:
        """
        Initialize field rename transform.

        Args:
            rename_map: Mapping of old field names to new field names
        """
        self.rename_map = rename_map

    def transform(self, record: Record) -> Record:
        """Rename fields in record."""
        new_data = {}
        for key, value in record.data.items():
            new_key = self.rename_map.get(key, key)
            new_data[new_key] = value

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Rename fields in output schema."""
        new_fields = []
        for field in input_schema.fields:
            new_name = self.rename_map.get(field.name, field.name)
            new_fields.append(
                Field(
                    name=new_name,
                    data_type=field.data_type,
                    nullable=field.nullable,
                    default=field.default,
                    metadata=field.metadata,
                )
            )

        return Schema(fields=new_fields, metadata=input_schema.metadata)


class TypeCastTransform(Transform):
    """Casts field types."""

    def __init__(self, cast_map: dict[str, DataType]) -> None:
        """
        Initialize type cast transform.

        Args:
            cast_map: Mapping of field names to target data types
        """
        self.cast_map = cast_map

    def transform(self, record: Record) -> Record:
        """Cast field types in record."""
        new_data = dict(record.data)

        for field_name, target_type in self.cast_map.items():
            if field_name in new_data:
                try:
                    new_data[field_name] = self._cast_value(new_data[field_name], target_type)
                except Exception as e:
                    raise TransformationError(
                        f"Failed to cast {field_name} to {target_type.value}: {e}", transform_name="TypeCastTransform"
                    )

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    @staticmethod
    def _cast_value(value: Any, target_type: DataType) -> Any:
        """Cast a value to target type."""
        if value is None:
            return None

        if target_type == DataType.STRING:
            return str(value)
        elif target_type == DataType.INTEGER:
            return int(float(value))
        elif target_type == DataType.FLOAT:
            return float(value)
        elif target_type == DataType.BOOLEAN:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        elif target_type == DataType.DATE:
            if isinstance(value, date):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value).date()
            return value
        elif target_type == DataType.TIMESTAMP:
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value)
            return value
        else:
            return value

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Update schema with cast types."""
        new_fields = []
        for field in input_schema.fields:
            if field.name in self.cast_map:
                new_fields.append(
                    Field(
                        name=field.name,
                        data_type=self.cast_map[field.name],
                        nullable=field.nullable,
                        default=field.default,
                        metadata=field.metadata,
                    )
                )
            else:
                new_fields.append(field)

        return Schema(fields=new_fields, metadata=input_schema.metadata)


class NullHandlerTransform(Transform):
    """Handles null values in records."""

    def __init__(
        self,
        mode: str = "drop",  # "drop", "fill", "coalesce"
        fill_value: Any | None = None,
        coalesce_fields: dict[str, list[str]] | None = None,
    ) -> None:
        """
        Initialize null handler transform.

        Args:
            mode: How to handle nulls (drop, fill, coalesce)
            fill_value: Value to fill nulls with
            coalesce_fields: Fields to use for coalesce (use first non-null)
        """
        self.mode = mode
        self.fill_value = fill_value
        self.coalesce_fields = coalesce_fields or {}

    def transform(self, record: Record) -> Record | None:
        """Handle null values in record."""
        new_data = dict(record.data)

        if self.mode == "drop":
            if any(v is None for v in new_data.values()):
                return None

        elif self.mode == "fill":
            for key, value in new_data.items():
                if value is None:
                    new_data[key] = self.fill_value

        elif self.mode == "coalesce":
            for target_field, source_fields in self.coalesce_fields.items():
                if target_field in new_data:
                    if new_data[target_field] is None:
                        for source in source_fields:
                            if source in new_data and new_data[source] is not None:
                                new_data[target_field] = new_data[source]
                                break

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Update nullability in output schema."""
        if self.mode == "drop":
            new_fields = [
                Field(name=f.name, data_type=f.data_type, nullable=False, default=f.default, metadata=f.metadata)
                for f in input_schema.fields
            ]
            return Schema(fields=new_fields, metadata=input_schema.metadata)

        return input_schema


class StringTransform(Transform):
    """Performs string operations on fields."""

    def __init__(
        self,
        operations: dict[str, dict[str, Any]],
    ) -> None:
        """
        Initialize string transform.

        Args:
            operations: Dict of field -> {op, params}
                       op can be: trim, uppercase, lowercase, split, regex_extract
        """
        self.operations = operations

    def transform(self, record: Record) -> Record | list[Record]:
        """Apply string operations to record."""
        new_data = dict(record.data)

        for field_name, op_config in self.operations.items():
            if field_name not in new_data:
                continue

            value = new_data[field_name]
            if value is None:
                continue

            op = op_config.get("op")
            try:
                if op == "trim":
                    new_data[field_name] = str(value).strip()
                elif op == "uppercase":
                    new_data[field_name] = str(value).upper()
                elif op == "lowercase":
                    new_data[field_name] = str(value).lower()
                elif op == "split":
                    delimiter = op_config.get("delimiter", ",")
                    new_data[field_name] = str(value).split(delimiter)
                elif op == "regex_extract":
                    pattern = op_config.get("pattern", "")
                    match = re.search(pattern, str(value))
                    new_data[field_name] = match.group(0) if match else None
            except Exception as e:
                raise TransformationError(f"String operation failed: {e}", transform_name="StringTransform")

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Update schema for string operations."""
        return input_schema


class DateTransform(Transform):
    """Handles date/time parsing and formatting."""

    def __init__(
        self,
        parse_fields: dict[str, str] | None = None,
        format_fields: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize date transform.

        Args:
            parse_fields: Fields to parse as dates with format strings
            format_fields: Fields to format with format strings
        """
        self.parse_fields = parse_fields or {}
        self.format_fields = format_fields or {}

    def transform(self, record: Record) -> Record:
        """Parse and format date fields."""
        new_data = dict(record.data)

        for field_name, fmt in self.parse_fields.items():
            if field_name in new_data and new_data[field_name] is not None:
                try:
                    new_data[field_name] = datetime.strptime(str(new_data[field_name]), fmt)
                except Exception as e:
                    raise TransformationError(f"Date parsing failed: {e}", transform_name="DateTransform")

        for field_name, fmt in self.format_fields.items():
            if field_name in new_data and isinstance(new_data[field_name], (datetime, date)):
                try:
                    new_data[field_name] = new_data[field_name].strftime(fmt)
                except Exception as e:
                    raise TransformationError(f"Date formatting failed: {e}", transform_name="DateTransform")

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Update schema for parsed/formatted dates."""
        return input_schema


class ExpressionEvaluatorTransform(Transform):
    """Evaluates arithmetic expressions on fields."""

    def __init__(
        self,
        expressions: dict[str, str],
    ) -> None:
        """
        Initialize expression evaluator.

        Args:
            expressions: Dict of output_field -> expression (e.g., "amount * tax_rate")
        """
        self.expressions = expressions

    def transform(self, record: Record) -> Record:
        """Evaluate expressions and add results to record."""
        new_data = dict(record.data)

        for output_field, expr in self.expressions.items():
            try:
                result = self._evaluate_expression(expr, new_data)
                new_data[output_field] = result
            except Exception as e:
                raise TransformationError(
                    f"Expression evaluation failed: {e}", transform_name="ExpressionEvaluatorTransform"
                )

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    @staticmethod
    def _evaluate_expression(expr: str, data: dict[str, Any]) -> Any:
        """Safely evaluate expression with field values."""
        namespace = {k: v for k, v in data.items() if isinstance(v, (int, float))}

        try:
            return evaluate_safe_expression(
                expr,
                names=namespace,
                functions={
                    "abs": abs,
                    "round": round,
                    "min": min,
                    "max": max,
                    "sqrt": math.sqrt,
                },
            )
        except SafeExpressionError as e:
            raise ValueError(f"Expression error: {e}")

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Add new fields to schema for expression results."""
        new_fields = list(input_schema.fields)

        for output_field in self.expressions.keys():
            if not any(f.name == output_field for f in new_fields):
                new_fields.append(Field(name=output_field, data_type=DataType.FLOAT))

        return Schema(fields=new_fields, metadata=input_schema.metadata)


class LookupJoinTransform(Transform):
    """Performs hash-based lookup join (enrichment)."""

    def __init__(
        self,
        lookup_data: dict[Any, Record],
        lookup_key: str,
        join_key: str,
        join_spec: JoinSpec | None = None,
    ) -> None:
        """
        Initialize lookup join transform.

        Args:
            lookup_data: Dictionary of lookup values by key
            lookup_key: Field name in lookup data
            join_key: Field name in input record
            join_spec: Optional join specification
        """
        self.lookup_data = lookup_data
        self.lookup_key = lookup_key
        self.join_key = join_key
        self.join_spec = join_spec or JoinSpec(join_key, lookup_key)

    def transform(self, record: Record) -> Record | None:
        """Perform lookup join on record."""
        key_value = record.get(self.join_key)
        if key_value is None:
            return record if self.join_spec.join_type == JoinType.LEFT else None

        lookup_record = self.lookup_data.get(key_value)
        if lookup_record is None:
            return record if self.join_spec.join_type == JoinType.LEFT else None

        # Merge records
        new_data = dict(record.data)
        for k, v in lookup_record.data.items():
            if k != self.lookup_key:
                suffix = self.join_spec.right_suffix
                new_key = f"{k}{suffix}" if k in new_data else k
                new_data[new_key] = v

        result = Record(data=new_data, metadata=record.metadata)
        result.timestamp = record.timestamp
        result.lineage = record.lineage
        return result

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Determine output schema including joined fields."""
        new_fields = list(input_schema.fields)

        if self.lookup_data:
            sample_lookup = next(iter(self.lookup_data.values()))
            for field_name in sample_lookup.data.keys():
                if field_name != self.lookup_key:
                    new_name = f"{field_name}{self.join_spec.right_suffix}"
                    new_fields.append(Field(name=new_name, data_type=DataType.ANY))

        return Schema(fields=new_fields, metadata=input_schema.metadata)


class PivotTransform(Transform):
    """Pivots data from rows to columns."""

    def __init__(
        self,
        index_columns: list[str],
        pivot_column: str,
        value_column: str,
        aggregation: str = "first",  # "first", "last", "count", "sum", "avg"
    ) -> None:
        """
        Initialize pivot transform.

        Args:
            index_columns: Columns to keep as rows
            pivot_column: Column whose values become new columns
            value_column: Column with values to aggregate
            aggregation: How to aggregate multiple values
        """
        self.index_columns = index_columns
        self.pivot_column = pivot_column
        self.value_column = value_column
        self.aggregation = aggregation
        self._pivot_table: dict[tuple, dict[str, Any]] = {}

    def add_record(self, record: Record) -> None:
        """Accumulate records for pivoting."""
        index_key = tuple(record.get(col) for col in self.index_columns)
        pivot_val = record.get(self.pivot_column)
        value_val = record.get(self.value_column)

        if index_key not in self._pivot_table:
            self._pivot_table[index_key] = {}

        if pivot_val not in self._pivot_table[index_key]:
            self._pivot_table[index_key][pivot_val] = []

        self._pivot_table[index_key][pivot_val].append(value_val)

    def get_pivoted_records(self) -> list[Record]:
        """Get pivoted records."""
        records = []
        for index_key, pivot_dict in self._pivot_table.items():
            data = dict(zip(self.index_columns, index_key))
            for pivot_val, values in pivot_dict.items():
                col_name = str(pivot_val)
                data[col_name] = self._aggregate(values)
            records.append(Record(data=data))

        return records

    def _aggregate(self, values: list[Any]) -> Any:
        """Aggregate values based on aggregation type."""
        if not values:
            return None
        if self.aggregation == "first":
            return values[0]
        elif self.aggregation == "last":
            return values[-1]
        elif self.aggregation == "count":
            return len(values)
        elif self.aggregation == "sum":
            return sum(v for v in values if isinstance(v, (int, float)))
        elif self.aggregation == "avg":
            nums = [v for v in values if isinstance(v, (int, float))]
            return sum(nums) / len(nums) if nums else None
        return values[0]

    def transform(self, record: Record) -> Record | None:
        """Not used for pivot, use add_record and get_pivoted_records instead."""
        self.add_record(record)
        return None

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Schema includes index columns plus pivot columns."""
        fields = [f for f in input_schema.fields if f.name in self.index_columns]

        # Add pivot value columns (would need to scan data to know all values)
        fields.append(Field(name="*pivot_columns", data_type=DataType.ANY))

        return Schema(fields=fields, metadata=input_schema.metadata)


class UnpivotTransform(Transform):
    """Unpivots data from columns to rows."""

    def __init__(
        self,
        id_vars: list[str],
        value_vars: list[str],
        var_name: str = "variable",
        value_name: str = "value",
    ) -> None:
        """
        Initialize unpivot transform.

        Args:
            id_vars: Columns to keep as identifiers
            value_vars: Columns to unpivot
            var_name: Name of variable column
            value_name: Name of value column
        """
        self.id_vars = id_vars
        self.value_vars = value_vars
        self.var_name = var_name
        self.value_name = value_name

    def transform(self, record: Record) -> list[Record]:
        """Unpivot record into multiple records."""
        records = []
        id_data = {col: record.get(col) for col in self.id_vars}

        for var_col in self.value_vars:
            value = record.get(var_col)
            new_data = dict(id_data)
            new_data[self.var_name] = var_col
            new_data[self.value_name] = value
            records.append(Record(data=new_data))

        return records

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Output schema with variable and value columns."""
        fields = [f for f in input_schema.fields if f.name in self.id_vars]
        fields.append(Field(name=self.var_name, data_type=DataType.STRING))
        fields.append(Field(name=self.value_name, data_type=DataType.ANY))

        return Schema(fields=fields, metadata=input_schema.metadata)


class DeduplicationTransform(Transform):
    """Removes duplicate records."""

    def __init__(
        self,
        subset: list[str] | None = None,
        keep: str = "first",  # "first", "last", "none"
        fuzzy: bool = False,
        distance_threshold: float = 0.1,
    ) -> None:
        """
        Initialize deduplication transform.

        Args:
            subset: Columns to consider for deduplication (None = all columns)
            keep: Which duplicates to keep
            fuzzy: Use fuzzy matching (edit distance)
            distance_threshold: Threshold for fuzzy matching
        """
        self.subset = subset
        self.keep = keep
        self.fuzzy = fuzzy
        self.distance_threshold = distance_threshold
        self._seen: set[str] = set()
        self._records: list[Record] = []

    def add_record(self, record: Record) -> None:
        """Add record for deduplication."""
        self._records.append(record)

    def get_deduplicated(self) -> list[Record]:
        """Get deduplicated records."""
        result = []
        self._seen = set()

        for record in self._records:
            key = self._get_record_key(record)

            if key not in self._seen:
                self._seen.add(key)
                result.append(record)

        return result

    def _get_record_key(self, record: Record) -> str:
        """Get deduplication key for record."""
        if self.subset:
            values = [str(record.get(col)) for col in self.subset]
        else:
            values = [str(v) for v in record.data.values()]

        return "|".join(values)

    def transform(self, record: Record) -> Record | None:
        """Not used directly, use add_record and get_deduplicated instead."""
        self.add_record(record)
        return None

    def get_output_schema(self, input_schema: Schema) -> Schema:
        """Deduplication preserves schema."""
        return input_schema
