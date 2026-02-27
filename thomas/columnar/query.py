"""
Vectorized query execution engine for columnar data.

Implements column-at-a-time execution model with batch operations,
vectorized filters, aggregations, and joins on columnar data.
"""

from collections.abc import Callable
from typing import Any

from thomas.columnar._exceptions import QueryError
from thomas.columnar._types import ColumnType, RowGroup


class ColumnBatch:
    """Batch of column data for vectorized processing."""

    def __init__(self, column_name: str, column_type: ColumnType, values: list[Any]) -> None:
        """Initialize column batch.

        Args:
            column_name: Name of column
            column_type: Data type of column
            values: Column values
        """
        self.column_name = column_name
        self.column_type = column_type
        self.values = values
        self.length = len(values)

    def apply_filter(self, mask: list[bool]) -> "ColumnBatch":
        """Apply boolean mask to filter batch.

        Args:
            mask: List of boolean flags (True = keep, False = filter out)

        Returns:
            New batch with filtered values
        """
        if len(mask) != self.length:
            raise QueryError(f"Mask length {len(mask)} != batch length {self.length}")

        filtered = [v for v, keep in zip(self.values, mask) if keep]
        return ColumnBatch(self.column_name, self.column_type, filtered)

    def map_values(self, func: Callable[[Any], Any]) -> "ColumnBatch":
        """Apply function to each value in batch.

        Args:
            func: Function to apply

        Returns:
            New batch with transformed values
        """
        transformed = [func(v) for v in self.values]
        return ColumnBatch(self.column_name, self.column_type, transformed)

    def __len__(self) -> int:
        """Get batch length."""
        return self.length


class VectorizedFilter:
    """Vectorized filter operations on column batches."""

    @staticmethod
    def equal(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate equality filter mask.

        Args:
            batch: Input column batch
            value: Value to compare against

        Returns:
            Boolean mask (True where column == value)
        """
        return [v == value if v is not None else False for v in batch.values]

    @staticmethod
    def not_equal(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate inequality filter mask."""
        return [v != value if v is not None else False for v in batch.values]

    @staticmethod
    def less_than(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate less-than filter mask."""
        return [v < value if v is not None else False for v in batch.values]

    @staticmethod
    def less_equal(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate less-than-or-equal filter mask."""
        return [v <= value if v is not None else False for v in batch.values]

    @staticmethod
    def greater_than(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate greater-than filter mask."""
        return [v > value if v is not None else False for v in batch.values]

    @staticmethod
    def greater_equal(batch: ColumnBatch, value: Any) -> list[bool]:
        """Generate greater-than-or-equal filter mask."""
        return [v >= value if v is not None else False for v in batch.values]

    @staticmethod
    def in_list(batch: ColumnBatch, values: list[Any]) -> list[bool]:
        """Generate in-list filter mask."""
        value_set = set(values)
        return [v in value_set if v is not None else False for v in batch.values]

    @staticmethod
    def is_null(batch: ColumnBatch) -> list[bool]:
        """Generate null filter mask."""
        return [v is None for v in batch.values]

    @staticmethod
    def is_not_null(batch: ColumnBatch) -> list[bool]:
        """Generate not-null filter mask."""
        return [v is not None for v in batch.values]

    @staticmethod
    def and_mask(mask1: list[bool], mask2: list[bool]) -> list[bool]:
        """Combine two masks with AND logic."""
        if len(mask1) != len(mask2):
            raise QueryError("Mask lengths do not match")
        return [a and b for a, b in zip(mask1, mask2)]

    @staticmethod
    def or_mask(mask1: list[bool], mask2: list[bool]) -> list[bool]:
        """Combine two masks with OR logic."""
        if len(mask1) != len(mask2):
            raise QueryError("Mask lengths do not match")
        return [a or b for a, b in zip(mask1, mask2)]

    @staticmethod
    def not_mask(mask: list[bool]) -> list[bool]:
        """Negate a mask."""
        return [not m for m in mask]

    @staticmethod
    def count_true(mask: list[bool]) -> int:
        """Count true values in mask."""
        return sum(1 for m in mask if m)


class VectorizedArithmetic:
    """Vectorized arithmetic operations on column batches."""

    @staticmethod
    def add(batch1: ColumnBatch, batch2: ColumnBatch) -> ColumnBatch:
        """Add two numeric batches element-wise."""
        if batch1.length != batch2.length:
            raise QueryError("Batch lengths do not match")

        if not batch1.column_type.is_numeric():
            raise QueryError(f"Type {batch1.column_type} is not numeric")

        result = [(a + b) if (a is not None and b is not None) else None for a, b in zip(batch1.values, batch2.values)]
        return ColumnBatch(f"{batch1.column_name}+{batch2.column_name}", batch1.column_type, result)

    @staticmethod
    def subtract(batch1: ColumnBatch, batch2: ColumnBatch) -> ColumnBatch:
        """Subtract two numeric batches element-wise."""
        if batch1.length != batch2.length:
            raise QueryError("Batch lengths do not match")

        if not batch1.column_type.is_numeric():
            raise QueryError(f"Type {batch1.column_type} is not numeric")

        result = [(a - b) if (a is not None and b is not None) else None for a, b in zip(batch1.values, batch2.values)]
        return ColumnBatch(f"{batch1.column_name}-{batch2.column_name}", batch1.column_type, result)

    @staticmethod
    def multiply(batch1: ColumnBatch, batch2: ColumnBatch) -> ColumnBatch:
        """Multiply two numeric batches element-wise."""
        if batch1.length != batch2.length:
            raise QueryError("Batch lengths do not match")

        if not batch1.column_type.is_numeric():
            raise QueryError(f"Type {batch1.column_type} is not numeric")

        result = [(a * b) if (a is not None and b is not None) else None for a, b in zip(batch1.values, batch2.values)]
        return ColumnBatch(f"{batch1.column_name}*{batch2.column_name}", batch1.column_type, result)

    @staticmethod
    def divide(batch1: ColumnBatch, batch2: ColumnBatch) -> ColumnBatch:
        """Divide two numeric batches element-wise."""
        if batch1.length != batch2.length:
            raise QueryError("Batch lengths do not match")

        if not batch1.column_type.is_numeric():
            raise QueryError(f"Type {batch1.column_type} is not numeric")

        result = []
        for a, b in zip(batch1.values, batch2.values):
            if a is not None and b is not None and b != 0:
                result.append(a / b)
            else:
                result.append(None)

        return ColumnBatch(f"{batch1.column_name}/{batch2.column_name}", batch1.column_type, result)


class VectorizedAggregation:
    """Vectorized aggregation operations on column batches."""

    @staticmethod
    def sum(batch: ColumnBatch) -> Any:
        """Sum numeric batch values."""
        if not batch.column_type.is_numeric():
            raise QueryError(f"Cannot sum non-numeric type {batch.column_type}")

        total = 0
        count = 0
        for v in batch.values:
            if v is not None:
                total += v
                count += 1

        return total if count > 0 else None

    @staticmethod
    def count(batch: ColumnBatch) -> int:
        """Count non-null values."""
        return sum(1 for v in batch.values if v is not None)

    @staticmethod
    def count_distinct(batch: ColumnBatch) -> int:
        """Count distinct non-null values."""
        return len(set(v for v in batch.values if v is not None))

    @staticmethod
    def min(batch: ColumnBatch) -> Any:
        """Get minimum value."""
        non_null = [v for v in batch.values if v is not None]
        return min(non_null) if non_null else None

    @staticmethod
    def max(batch: ColumnBatch) -> Any:
        """Get maximum value."""
        non_null = [v for v in batch.values if v is not None]
        return max(non_null) if non_null else None

    @staticmethod
    def avg(batch: ColumnBatch) -> float | None:
        """Get average of numeric batch."""
        if not batch.column_type.is_numeric():
            raise QueryError(f"Cannot average non-numeric type {batch.column_type}")

        non_null = [v for v in batch.values if v is not None]
        if not non_null:
            return None
        return sum(non_null) / len(non_null)

    @staticmethod
    def stddev(batch: ColumnBatch) -> float | None:
        """Get standard deviation of numeric batch."""
        if not batch.column_type.is_numeric():
            raise QueryError(f"Cannot calculate stddev of non-numeric type {batch.column_type}")

        non_null = [v for v in batch.values if v is not None]
        if len(non_null) < 2:
            return None

        mean = sum(non_null) / len(non_null)
        variance = sum((v - mean) ** 2 for v in non_null) / len(non_null)
        return variance**0.5

    @staticmethod
    def group_by(batch: ColumnBatch, values: list[Any]) -> dict[Any, tuple[int, int]]:
        """Group values and return (group_key -> (count, sum)) for numeric batches.

        Args:
            batch: Column batch to aggregate
            values: Values to group by

        Returns:
            Dictionary mapping group keys to (count, sum) tuples
        """
        if len(batch.values) != len(values):
            raise QueryError("Batch length != values length")

        groups: dict[Any, tuple[int, float]] = {}

        for group_key, value in zip(values, batch.values):
            if group_key not in groups:
                groups[group_key] = (0, 0)

            if value is not None:
                count, total = groups[group_key]
                groups[group_key] = (count + 1, total + (value if batch.column_type.is_numeric() else 0))

        return groups


class HashAggregator:
    """Hash-based aggregation for group-by operations."""

    def __init__(self) -> None:
        """Initialize aggregator."""
        self.groups: dict[Any, dict[str, Any]] = {}

    def add(
        self,
        group_key: Any,
        values: dict[str, Any],
    ) -> None:
        """Add value to group.

        Args:
            group_key: Group key
            values: Dictionary of column_name -> value
        """
        if group_key not in self.groups:
            self.groups[group_key] = {k: [] for k in values}

        for col_name, value in values.items():
            if col_name in self.groups[group_key]:
                self.groups[group_key][col_name].append(value)

    def get_aggregate(self, group_key: Any, column_name: str, agg_type: str) -> Any:
        """Get aggregate for group.

        Args:
            group_key: Group key
            column_name: Column name
            agg_type: Aggregation type (sum, count, min, max, avg)

        Returns:
            Aggregate value
        """
        if group_key not in self.groups or column_name not in self.groups[group_key]:
            return None

        values = self.groups[group_key][column_name]
        non_null = [v for v in values if v is not None]

        if agg_type == "count":
            return len(non_null)
        elif agg_type == "sum":
            return sum(non_null) if non_null else None
        elif agg_type == "min":
            return min(non_null) if non_null else None
        elif agg_type == "max":
            return max(non_null) if non_null else None
        elif agg_type == "avg":
            return sum(non_null) / len(non_null) if non_null else None
        else:
            raise QueryError(f"Unknown aggregation type: {agg_type}")

    def get_results(self) -> list[tuple[Any, dict[str, Any]]]:
        """Get all aggregation results."""
        results = []
        for group_key, columns in self.groups.items():
            row = {"_group_key": group_key}
            for col_name, values in columns.items():
                row[col_name] = values
            results.append((group_key, row))
        return results


class QueryExecutor:
    """Query executor for vectorized query processing."""

    def __init__(self) -> None:
        """Initialize query executor."""
        self.batches: dict[str, ColumnBatch] = {}

    def load_row_group(self, row_group: RowGroup, schema: Any) -> None:
        """Load column data from row group into batches.

        Args:
            row_group: Row group to load
            schema: Schema defining columns
        """
        from thomas.columnar.storage import RowGroupReader

        reader = RowGroupReader(row_group)

        for col_idx, field in enumerate(schema.fields):
            values = reader.read_column(col_idx)
            self.batches[field.name] = ColumnBatch(field.name, field.column_type, values)

    def filter(self, column_name: str, operator: str, value: Any) -> list[bool]:
        """Apply filter predicate to column.

        Args:
            column_name: Name of column to filter
            operator: Comparison operator (==, !=, <, <=, >, >=, in, is_null, is_not_null)
            value: Value to compare against

        Returns:
            Boolean mask
        """
        if column_name not in self.batches:
            raise QueryError(f"Column '{column_name}' not found")

        batch = self.batches[column_name]

        if operator == "==":
            return VectorizedFilter.equal(batch, value)
        elif operator == "!=":
            return VectorizedFilter.not_equal(batch, value)
        elif operator == "<":
            return VectorizedFilter.less_than(batch, value)
        elif operator == "<=":
            return VectorizedFilter.less_equal(batch, value)
        elif operator == ">":
            return VectorizedFilter.greater_than(batch, value)
        elif operator == ">=":
            return VectorizedFilter.greater_equal(batch, value)
        elif operator == "in":
            return VectorizedFilter.in_list(batch, value)
        elif operator == "is_null":
            return VectorizedFilter.is_null(batch)
        elif operator == "is_not_null":
            return VectorizedFilter.is_not_null(batch)
        else:
            raise QueryError(f"Unknown operator: {operator}")

    def apply_mask(self, mask: list[bool]) -> None:
        """Apply filter mask to all loaded batches.

        Args:
            mask: Boolean mask to apply
        """
        for col_name in self.batches:
            self.batches[col_name] = self.batches[col_name].apply_filter(mask)

    def aggregate(self, column_name: str, agg_type: str) -> Any:
        """Compute aggregation on column.

        Args:
            column_name: Column to aggregate
            agg_type: Aggregation type (sum, count, min, max, avg, stddev, count_distinct)

        Returns:
            Aggregate value
        """
        if column_name not in self.batches:
            raise QueryError(f"Column '{column_name}' not found")

        batch = self.batches[column_name]

        if agg_type == "sum":
            return VectorizedAggregation.sum(batch)
        elif agg_type == "count":
            return VectorizedAggregation.count(batch)
        elif agg_type == "min":
            return VectorizedAggregation.min(batch)
        elif agg_type == "max":
            return VectorizedAggregation.max(batch)
        elif agg_type == "avg":
            return VectorizedAggregation.avg(batch)
        elif agg_type == "stddev":
            return VectorizedAggregation.stddev(batch)
        elif agg_type == "count_distinct":
            return VectorizedAggregation.count_distinct(batch)
        else:
            raise QueryError(f"Unknown aggregation type: {agg_type}")

    def project(self, column_names: list[str]) -> list[dict[str, Any]]:
        """Project columns and return as list of dicts.

        Args:
            column_names: Columns to project

        Returns:
            List of dictionaries with projected columns
        """
        for name in column_names:
            if name not in self.batches:
                raise QueryError(f"Column '{name}' not found")

        # Get batch length from first column
        batch_length = len(self.batches[column_names[0]])

        results = []
        for i in range(batch_length):
            row = {}
            for col_name in column_names:
                row[col_name] = self.batches[col_name].values[i]
            results.append(row)

        return results

    def get_batch(self, column_name: str) -> ColumnBatch:
        """Get column batch by name.

        Args:
            column_name: Column name

        Returns:
            Column batch
        """
        if column_name not in self.batches:
            raise QueryError(f"Column '{column_name}' not found")
        return self.batches[column_name]
