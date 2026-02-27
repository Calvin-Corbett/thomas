"""
Late materialization strategies for columnar query execution.

Implements position-list based execution to delay row materialization
until necessary, improving cache locality and reducing memory usage.
"""

from collections.abc import Callable
from typing import Any

from thomas.columnar._exceptions import QueryError


class PositionList:
    """List of row positions (IDs) that pass a filter."""

    def __init__(self, positions: list[int] | None = None) -> None:
        """Initialize position list.

        Args:
            positions: Optional list of row IDs
        """
        self.positions = positions or []

    def __len__(self) -> int:
        """Get number of positions."""
        return len(self.positions)

    def __getitem__(self, index: int) -> int:
        """Get position at index."""
        return self.positions[index]

    def __iter__(self):
        """Iterate over positions."""
        return iter(self.positions)

    def copy(self) -> "PositionList":
        """Create a copy of position list."""
        return PositionList(self.positions.copy())

    def intersect(self, other: "PositionList") -> "PositionList":
        """Intersect two position lists (AND operation).

        Args:
            other: Other position list

        Returns:
            New position list with common positions
        """
        positions_set = set(self.positions)
        intersected = [p for p in other.positions if p in positions_set]
        return PositionList(intersected)

    def union(self, other: "PositionList") -> "PositionList":
        """Union two position lists (OR operation).

        Args:
            other: Other position list

        Returns:
            New position list with all unique positions
        """
        combined = sorted(set(self.positions) | set(other.positions))
        return PositionList(combined)

    def subtract(self, other: "PositionList") -> "PositionList":
        """Subtract another position list (this - other).

        Args:
            other: Other position list

        Returns:
            New position list with positions in this but not other
        """
        other_set = set(other.positions)
        difference = [p for p in self.positions if p not in other_set]
        return PositionList(difference)

    def from_mask(mask: list[bool]) -> "PositionList":
        """Create position list from boolean mask.

        Args:
            mask: Boolean mask where True indicates positions to keep

        Returns:
            Position list with positions where mask is True
        """
        positions = [i for i, m in enumerate(mask) if m]
        return PositionList(positions)

    def to_mask(self, length: int) -> list[bool]:
        """Convert position list to boolean mask.

        Args:
            length: Length of mask

        Returns:
            Boolean mask where True at positions in list
        """
        mask = [False] * length
        for pos in self.positions:
            if pos < length:
                mask[pos] = True
        return mask

    def reindex(self, mapping: dict[int, int]) -> "PositionList":
        """Reindex positions using mapping.

        Args:
            mapping: Dictionary mapping old_pos -> new_pos

        Returns:
            New position list with reindexed positions
        """
        reindexed = [mapping.get(p, p) for p in self.positions]
        return PositionList(sorted(reindexed))


class LateMatrixExecutor:
    """Executor for late materialization strategy."""

    def __init__(self) -> None:
        """Initialize late materialization executor."""
        self.position_lists: dict[str, PositionList] = {}
        self.column_data: dict[str, list[Any]] = {}

    def load_column(self, column_name: str, values: list[Any]) -> None:
        """Load column data.

        Args:
            column_name: Name of column
            values: Column values
        """
        self.column_data[column_name] = values

    def filter_column(
        self,
        column_name: str,
        predicate: Callable[[Any], bool],
    ) -> PositionList:
        """Apply filter to column and get matching positions.

        Args:
            column_name: Column to filter
            predicate: Filter function

        Returns:
            Position list of matching rows
        """
        if column_name not in self.column_data:
            raise QueryError(f"Column '{column_name}' not loaded")

        values = self.column_data[column_name]
        positions = [i for i, v in enumerate(values) if v is not None and predicate(v)]
        pos_list = PositionList(positions)
        self.position_lists[column_name] = pos_list
        return pos_list

    def combine_filters(
        self,
        filters: dict[str, PositionList],
        operator: str = "AND",
    ) -> PositionList:
        """Combine multiple filter position lists.

        Args:
            filters: Dictionary mapping column_name -> PositionList
            operator: How to combine ("AND", "OR", "NOT")

        Returns:
            Combined position list
        """
        if not filters:
            return PositionList([])

        position_lists = list(filters.values())

        if operator == "AND":
            result = position_lists[0].copy()
            for pos_list in position_lists[1:]:
                result = result.intersect(pos_list)
            return result

        elif operator == "OR":
            result = position_lists[0].copy()
            for pos_list in position_lists[1:]:
                result = result.union(pos_list)
            return result

        else:
            raise QueryError(f"Unknown operator: {operator}")

    def materialize_columns(
        self,
        positions: PositionList,
        column_names: list[str],
    ) -> list[dict[str, Any]]:
        """Materialize rows for specified columns using position list.

        Args:
            positions: Position list of rows to materialize
            column_names: Columns to include in result

        Returns:
            List of dictionaries (one per row)
        """
        results = []

        for pos in positions:
            row = {}
            for col_name in column_names:
                if col_name in self.column_data:
                    values = self.column_data[col_name]
                    if pos < len(values):
                        row[col_name] = values[pos]
                    else:
                        row[col_name] = None
            results.append(row)

        return results

    def aggregate_with_positions(
        self,
        column_name: str,
        positions: PositionList,
        agg_func: Callable[[list[Any]], Any],
    ) -> Any:
        """Compute aggregate on column subset using position list.

        Args:
            column_name: Column to aggregate
            positions: Position list of rows to include
            agg_func: Aggregation function

        Returns:
            Aggregate value
        """
        if column_name not in self.column_data:
            raise QueryError(f"Column '{column_name}' not loaded")

        values = self.column_data[column_name]
        subset = [values[pos] for pos in positions if pos < len(values)]

        return agg_func(subset)


class HybridMateriailizationSelector:
    """Selector for early vs late materialization strategy."""

    @staticmethod
    def should_use_late_materialization(
        num_rows: int,
        num_columns: int,
        selectivity: float,
    ) -> bool:
        """Determine if late materialization should be used.

        Args:
            num_rows: Total number of rows
            num_columns: Number of columns
            selectivity: Fraction of rows matching filter (0.0 to 1.0)

        Returns:
            True if late materialization is better
        """
        # Late materialization is better when:
        # 1. Selectivity is low (few rows match)
        # 2. Many columns but few needed for filtering
        # 3. Large number of rows

        if selectivity > 0.5:
            # High selectivity: early materialization likely better
            return False

        if num_rows < 1000:
            # Small dataset: early materialization fine
            return False

        # Late materialization good for low selectivity, large datasets
        return True

    @staticmethod
    def estimate_memory_early_materialization(
        num_rows: int,
        num_columns: int,
        avg_value_size: int,
    ) -> int:
        """Estimate memory for early materialization.

        Args:
            num_rows: Number of rows
            num_columns: Number of columns
            avg_value_size: Average value size in bytes

        Returns:
            Estimated memory in bytes
        """
        return num_rows * num_columns * avg_value_size

    @staticmethod
    def estimate_memory_late_materialization(
        num_rows: int,
        num_filter_columns: int,
        num_output_columns: int,
        avg_value_size: int,
        selectivity: float,
    ) -> int:
        """Estimate memory for late materialization.

        Args:
            num_rows: Total number of rows
            num_filter_columns: Columns used in filter
            num_output_columns: Columns in result
            avg_value_size: Average value size in bytes
            selectivity: Fraction of rows in result

        Returns:
            Estimated memory in bytes
        """
        # Load filter columns + position list
        filter_mem = num_rows * num_filter_columns * avg_value_size
        position_list_mem = int(num_rows * selectivity * 8)  # 8 bytes per position

        # Materialize output columns for result rows
        result_mem = int(num_rows * selectivity * num_output_columns * avg_value_size)

        return filter_mem + position_list_mem + result_mem


class ColumnAtATimeExecutor:
    """Executor for column-at-a-time execution model."""

    def __init__(self) -> None:
        """Initialize column-at-a-time executor."""
        self.columns: dict[str, list[Any]] = {}

    def load_column(self, column_name: str, values: list[Any]) -> None:
        """Load column data.

        Args:
            column_name: Column name
            values: Column values
        """
        self.columns[column_name] = values

    def process_columns(
        self,
        column_names: list[str],
        processor: Callable[[dict[str, Any]], Any | None],
    ) -> list[Any]:
        """Process all rows column-at-a-time.

        Args:
            column_names: Columns to process
            processor: Function to apply to each row

        Returns:
            List of results
        """
        if not column_names:
            return []

        # Get batch size from first column
        batch_size = len(self.columns[column_names[0]])

        results = []
        for i in range(batch_size):
            row = {}
            for col_name in column_names:
                if col_name in self.columns:
                    values = self.columns[col_name]
                    row[col_name] = values[i] if i < len(values) else None

            result = processor(row)
            if result is not None:
                results.append(result)

        return results

    def batch_process(
        self,
        column_names: list[str],
        batch_size: int,
        processor: Callable[[list[dict[str, Any]]], list[Any]],
    ) -> list[Any]:
        """Process columns in batches.

        Args:
            column_names: Columns to process
            batch_size: Batch size
            processor: Function to apply to each batch

        Returns:
            List of results
        """
        if not column_names:
            return []

        num_rows = len(self.columns[column_names[0]])
        all_results = []

        for start_idx in range(0, num_rows, batch_size):
            end_idx = min(start_idx + batch_size, num_rows)

            batch = []
            for i in range(start_idx, end_idx):
                row = {}
                for col_name in column_names:
                    if col_name in self.columns:
                        values = self.columns[col_name]
                        row[col_name] = values[i] if i < len(values) else None
                batch.append(row)

            results = processor(batch)
            all_results.extend(results)

        return all_results
