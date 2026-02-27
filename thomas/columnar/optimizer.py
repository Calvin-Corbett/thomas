"""
Query optimization: predicate pushdown, column pruning, filter reordering, and join optimization.

Implements query rewriting strategies to improve columnar query execution performance.
"""

from collections.abc import Callable
from typing import Any

from thomas.columnar._exceptions import QueryError
from thomas.columnar._types import ColumnType, Schema, Statistics


class FilterExpr:
    """Represents a filter expression in a query."""

    def __init__(
        self,
        column: str,
        operator: str,
        value: Any,
        selectivity: float | None = None,
    ) -> None:
        """Initialize filter expression.

        Args:
            column: Column name
            operator: Comparison operator
            value: Value to compare against
            selectivity: Estimated fraction of rows passing filter
        """
        self.column = column
        self.operator = operator
        self.value = value
        self.selectivity = selectivity or 0.5

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.column} {self.operator} {self.value}"


class PredicatePushdownOptimizer:
    """Optimizer for pushing predicates to storage layer."""

    @staticmethod
    def optimize(
        filters: list[FilterExpr],
        schema: Schema,
    ) -> tuple[list[FilterExpr], list[FilterExpr]]:
        """Separate filters into storage-pushdown and execution-time filters.

        Args:
            filters: List of filter expressions
            schema: Table schema

        Returns:
            Tuple of (pushdown_filters, execution_filters)
        """
        pushdown = []
        execution = []

        for f in filters:
            # Check if column exists and is indexed
            try:
                schema.get_field_index(f.column)
                # Column exists - can be pushed down
                pushdown.append(f)
            except ValueError:
                # Column doesn't exist or can't be pushed down
                execution.append(f)

        return pushdown, execution


class ColumnPruner:
    """Optimizer for column pruning (reading only required columns)."""

    @staticmethod
    def prune_columns(
        required_columns: set[str],
        filter_columns: set[str],
        schema: Schema,
    ) -> list[int]:
        """Determine which columns to read from storage.

        Args:
            required_columns: Columns needed in result
            filter_columns: Columns used in filters
            schema: Table schema

        Returns:
            List of column indices to read
        """
        to_read = required_columns.union(filter_columns)
        column_indices = []

        for i, field in enumerate(schema.fields):
            if field.name in to_read:
                column_indices.append(i)

        return column_indices

    @staticmethod
    def estimate_io_savings(
        total_columns: int,
        pruned_columns: int,
    ) -> float:
        """Estimate I/O savings from column pruning.

        Args:
            total_columns: Total number of columns
            pruned_columns: Number of columns after pruning

        Returns:
            Estimated fraction of I/O reduced (0.0 to 1.0)
        """
        if total_columns == 0:
            return 0.0

        return (total_columns - pruned_columns) / total_columns


class FilterReorderer:
    """Optimizer for filter execution order."""

    @staticmethod
    def reorder_filters(filters: list[FilterExpr]) -> list[FilterExpr]:
        """Reorder filters by selectivity (most selective first).

        Args:
            filters: List of filter expressions

        Returns:
            Reordered filters with most selective first
        """
        # Sort by selectivity (ascending)
        return sorted(filters, key=lambda f: f.selectivity)

    @staticmethod
    def compute_selectivity(
        operator: str,
        column_stats: Statistics | None,
    ) -> float:
        """Estimate selectivity of single filter predicate.

        Args:
            operator: Filter operator
            column_stats: Column statistics

        Returns:
            Estimated selectivity (0.0 to 1.0)
        """
        if not column_stats:
            return 0.5

        if operator in {"==", "!="}:
            if column_stats.distinct_count > 0:
                return 1.0 / column_stats.distinct_count
            return 0.1

        elif operator in {"<", ">", "<=", ">="}:
            return 0.3

        elif operator == "is_null":
            return column_stats.get_null_fraction()

        elif operator == "is_not_null":
            return 1.0 - column_stats.get_null_fraction()

        return 0.5

    @staticmethod
    def compute_combined_selectivity(filters: list[FilterExpr]) -> float:
        """Estimate combined selectivity of multiple AND-ed filters.

        Args:
            filters: List of filter expressions

        Returns:
            Estimated combined selectivity
        """
        selectivity = 1.0
        for f in filters:
            selectivity *= f.selectivity

        return selectivity


class JoinOptimizer:
    """Optimizer for columnar joins."""

    @staticmethod
    def optimize_join_order(
        tables: dict[str, int],
        join_conditions: list[tuple[str, str]],
        table_stats: dict[str, int],
    ) -> list[tuple[str, str]]:
        """Optimize join order for columnar execution.

        Args:
            tables: Dictionary mapping table_name -> num_rows
            join_conditions: List of (left_table, right_table) join pairs
            table_stats: Statistics for each table

        Returns:
            Reordered join pairs
        """
        # Sort joins by smaller-to-larger table principle
        return sorted(join_conditions, key=lambda j: table_stats.get(j[0], 0))

    @staticmethod
    def estimate_join_cost(
        left_rows: int,
        right_rows: int,
        join_type: str,
    ) -> float:
        """Estimate cost of join operation.

        Args:
            left_rows: Rows in left table
            right_rows: Rows in right table
            join_type: Type of join (inner, left, right, outer)

        Returns:
            Estimated cost
        """
        if join_type == "inner":
            return min(left_rows, right_rows)

        elif join_type in {"left", "right"}:
            return max(left_rows, right_rows)

        elif join_type == "outer":
            return left_rows + right_rows

        return left_rows * right_rows

    @staticmethod
    def recommend_join_algorithm(
        left_rows: int,
        right_rows: int,
        join_cardinality: int | None = None,
    ) -> str:
        """Recommend join algorithm based on table sizes.

        Args:
            left_rows: Rows in left table
            right_rows: Rows in right table
            join_cardinality: Expected result cardinality

        Returns:
            Recommended join algorithm (hash_join, sort_merge, nested_loop)
        """
        # Hash join good for reasonable sizes
        if left_rows > 1000 and right_rows > 100:
            return "hash_join"

        # Sort-merge for pre-sorted data
        if left_rows > 10000 and right_rows > 10000:
            return "sort_merge"

        # Nested loop for small tables
        if left_rows < 100 or right_rows < 100:
            return "nested_loop"

        return "hash_join"


class AggregationOptimizer:
    """Optimizer for aggregation operations."""

    @staticmethod
    def can_pushdown_aggregation(
        agg_func: str,
        column_type: ColumnType,
    ) -> bool:
        """Check if aggregation can be pushed to storage layer.

        Args:
            agg_func: Aggregation function (sum, count, min, max, avg)
            column_type: Column data type

        Returns:
            True if aggregation can be pushed down
        """
        if agg_func == "count":
            return True

        if agg_func in {"min", "max"}:
            return True

        if agg_func == "sum" and column_type.is_numeric():
            return True

        if agg_func == "avg" and column_type.is_numeric():
            return True

        return False

    @staticmethod
    def estimate_aggregation_selectivity(
        num_groups: int,
        total_rows: int,
    ) -> float:
        """Estimate selectivity of group-by aggregation.

        Args:
            num_groups: Number of groups
            total_rows: Total input rows

        Returns:
            Estimated selectivity (rows_out / rows_in)
        """
        if total_rows == 0:
            return 0.0

        return num_groups / total_rows


class ExpressionCompiler:
    """Compiler for optimized expression evaluation."""

    @staticmethod
    def compile_filter(filter_expr: FilterExpr) -> Callable[[Any], bool]:
        """Compile filter expression to optimized function.

        Args:
            filter_expr: Filter expression

        Returns:
            Compiled filter function
        """
        op = filter_expr.operator
        value = filter_expr.value

        if op == "==":
            return lambda x: x == value if x is not None else False

        elif op == "!=":
            return lambda x: x != value if x is not None else False

        elif op == "<":
            return lambda x: x < value if x is not None else False

        elif op == "<=":
            return lambda x: x <= value if x is not None else False

        elif op == ">":
            return lambda x: x > value if x is not None else False

        elif op == ">=":
            return lambda x: x >= value if x is not None else False

        elif op == "in":
            value_set = set(value)
            return lambda x: x in value_set if x is not None else False

        elif op == "is_null":
            return lambda x: x is None

        elif op == "is_not_null":
            return lambda x: x is not None

        else:
            raise QueryError(f"Unknown operator: {op}")

    @staticmethod
    def compile_aggregation(agg_func: str) -> Callable[[list[Any]], Any]:
        """Compile aggregation function to optimized function.

        Args:
            agg_func: Aggregation function name

        Returns:
            Compiled aggregation function
        """
        if agg_func == "count":
            return lambda values: sum(1 for v in values if v is not None)

        elif agg_func == "sum":
            return lambda values: sum(v for v in values if v is not None)

        elif agg_func == "min":
            return lambda values: min((v for v in values if v is not None), default=None)

        elif agg_func == "max":
            return lambda values: max((v for v in values if v is not None), default=None)

        elif agg_func == "avg":
            non_null = [v for v in values if v is not None]
            if not non_null:
                return None
            return sum(non_null) / len(non_null)

        elif agg_func == "count_distinct":
            return lambda values: len(set(v for v in values if v is not None))

        else:
            raise QueryError(f"Unknown aggregation: {agg_func}")


class QueryOptimizer:
    """Main query optimizer orchestrating all optimizations."""

    def __init__(self, schema: Schema) -> None:
        """Initialize optimizer.

        Args:
            schema: Query schema
        """
        self.schema = schema

    def optimize(
        self,
        columns: list[str],
        filters: list[FilterExpr],
        aggregations: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Optimize query execution plan.

        Args:
            columns: Required columns
            filters: Filter predicates
            aggregations: Optional aggregation functions

        Returns:
            Optimized query plan
        """
        # Step 1: Predicate pushdown
        pushdown_filters, execution_filters = PredicatePushdownOptimizer.optimize(filters, self.schema)

        # Step 2: Reorder filters by selectivity
        optimized_filters = FilterReorderer.reorder_filters(execution_filters)

        # Step 3: Column pruning
        required = set(columns)
        filter_cols = set(f.column for f in filters)
        column_indices = ColumnPruner.prune_columns(required, filter_cols, self.schema)

        # Step 4: Estimate combined selectivity
        combined_selectivity = FilterReorderer.compute_combined_selectivity(optimized_filters)

        return {
            "pushdown_filters": pushdown_filters,
            "execution_filters": optimized_filters,
            "column_indices": column_indices,
            "selectivity": combined_selectivity,
            "aggregations": aggregations or {},
        }
