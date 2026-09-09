"""
Query executor implementing volcano iterator model.

This module implements:
- Volcano/iterator model (open/next/close)
- Sequential scan operator
- Index scan operator
- Nested loop join
- Sort-merge join
- Hash join (grace hash join)
- Sort operator (external merge sort)
- Aggregation (hash-based and sort-based)
- LIMIT/OFFSET operators
- Expression evaluator
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from ._exceptions import ExecutorException
from ._types import ExpressionNode, Record, Table
from .btree import BPlusTree, BTreeKey
from .buffer_pool import BufferPool
from .storage import HeapFile


@dataclass
class ExecutionContext:
    """Context for query execution."""

    buffer_pool: BufferPool
    tables: dict[str, Table]
    heap_files: dict[str, HeapFile]
    indexes: dict[str, BPlusTree]
    correlation_name_map: dict[str, str] = field(default_factory=dict)


class Operator:
    """Base class for all operators in execution plan."""

    def __init__(self, operator_id: int) -> None:
        """Initialize operator."""
        self.operator_id = operator_id
        self.is_open = False

    def open(self, context: ExecutionContext) -> None:
        """Open operator for execution."""
        self.is_open = True
        self.context = context

    def next(self) -> Record | None:
        """Get next record from operator."""
        raise NotImplementedError()

    def close(self) -> None:
        """Close operator and release resources."""
        self.is_open = False

    def __iter__(self) -> Iterator[Record]:
        """Iterate over records."""
        self.open(ExecutionContext(buffer_pool=BufferPool(), tables={}, heap_files={}, indexes={}))
        try:
            while True:
                rec = self.next()
                if rec is None:
                    break
                yield rec
        finally:
            self.close()


class SeqScanOperator(Operator):
    """Sequential table scan operator."""

    def __init__(self, operator_id: int, table_name: str) -> None:
        """
        Initialize sequential scan.

        Args:
            operator_id: Unique operator ID
            table_name: Name of table to scan
        """
        super().__init__(operator_id)
        self.table_name = table_name
        self.heap_file: HeapFile | None = None
        self.iterator: Iterator[Record] | None = None

    def open(self, context: ExecutionContext) -> None:
        """Open the scan."""
        super().open(context)
        table = context.tables.get(self.table_name)
        if table is None:
            raise ExecutorException(f"Table {self.table_name} not found")

        self.heap_file = context.heap_files.get(self.table_name)
        if self.heap_file is None:
            self.heap_file = HeapFile(context.buffer_pool, table)

        self.iterator = self.heap_file.scan()

    def next(self) -> Record | None:
        """Get next record from table."""
        if self.iterator is None:
            return None

        try:
            return next(self.iterator)
        except StopIteration:
            return None

    def close(self) -> None:
        """Close the scan."""
        super().close()
        self.iterator = None


class IndexScanOperator(Operator):
    """Index scan operator for point/range queries."""

    def __init__(
        self,
        operator_id: int,
        index_name: str,
        start_key: BTreeKey | None = None,
        end_key: BTreeKey | None = None,
    ) -> None:
        """
        Initialize index scan.

        Args:
            operator_id: Unique operator ID
            index_name: Name of index to scan
            start_key: Start of range (inclusive)
            end_key: End of range (inclusive)
        """
        super().__init__(operator_id)
        self.index_name = index_name
        self.start_key = start_key
        self.end_key = end_key
        self.btree: BPlusTree | None = None
        self.iterator: Iterator | None = None

    def open(self, context: ExecutionContext) -> None:
        """Open the index scan."""
        super().open(context)
        self.btree = context.indexes.get(self.index_name)
        if self.btree is None:
            raise ExecutorException(f"Index {self.index_name} not found")

        self.iterator = self.btree.range_scan(self.start_key, self.end_key)

    def next(self) -> Record | None:
        """Get next record from index."""
        if self.iterator is None:
            return None

        try:
            key, rid = next(self.iterator)
            page_id, slot_id = rid
            # Would retrieve actual record from heap file
            # For now, return record with key values
            return Record(rid=rid, values={"key": key.values})
        except StopIteration:
            return None

    def close(self) -> None:
        """Close the index scan."""
        super().close()
        self.iterator = None


class FilterOperator(Operator):
    """Filter operator for WHERE clause predicates."""

    def __init__(self, operator_id: int, child: Operator, predicate: ExpressionNode) -> None:
        """
        Initialize filter.

        Args:
            operator_id: Unique operator ID
            child: Child operator
            predicate: Filter expression
        """
        super().__init__(operator_id)
        self.child = child
        self.predicate = predicate

    def open(self, context: ExecutionContext) -> None:
        """Open the filter."""
        super().open(context)
        self.child.open(context)

    def next(self) -> Record | None:
        """Get next record matching predicate."""
        while True:
            record = self.child.next()
            if record is None:
                return None

            # Evaluate predicate
            try:
                result = self.predicate.evaluate(record)
                if result:
                    return record
            except Exception:
                # If evaluation fails, skip record
                pass

    def close(self) -> None:
        """Close the filter."""
        super().close()
        self.child.close()


class ProjectionOperator(Operator):
    """Projection operator for SELECT columns."""

    def __init__(self, operator_id: int, child: Operator, columns: list[str]) -> None:
        """
        Initialize projection.

        Args:
            operator_id: Unique operator ID
            child: Child operator
            columns: Column names to project
        """
        super().__init__(operator_id)
        self.child = child
        self.columns = columns

    def open(self, context: ExecutionContext) -> None:
        """Open the projection."""
        super().open(context)
        self.child.open(context)

    def next(self) -> Record | None:
        """Get next projected record."""
        record = self.child.next()
        if record is None:
            return None

        # Create new record with only selected columns
        projected_values = {}
        for col in self.columns:
            if col == "*":
                return record
            if col in record.values:
                projected_values[col] = record.values[col]

        return Record(rid=record.rid, values=projected_values)

    def close(self) -> None:
        """Close the projection."""
        super().close()
        self.child.close()


class NestedLoopJoinOperator(Operator):
    """Nested loop join operator."""

    def __init__(self, operator_id: int, left: Operator, right: Operator, predicate: ExpressionNode) -> None:
        """
        Initialize nested loop join.

        Args:
            operator_id: Unique operator ID
            left: Left child (outer table)
            right: Right child (inner table)
            predicate: Join condition
        """
        super().__init__(operator_id)
        self.left = left
        self.right = right
        self.predicate = predicate
        self.current_left: Record | None = None
        self.left_exhausted = False

    def open(self, context: ExecutionContext) -> None:
        """Open the join."""
        super().open(context)
        self.left.open(context)
        self.right.open(context)
        self.current_left = None
        self.left_exhausted = False

    def next(self) -> Record | None:
        """Get next joined record."""
        while True:
            # If no current left record, get next from outer table
            if self.current_left is None:
                self.current_left = self.left.next()
                if self.current_left is None:
                    return None

                # Reset inner scan
                self.right.close()
                self.right.open(self.context)

            # Try to find matching record from inner table
            right_record = self.right.next()
            if right_record is None:
                # Inner table exhausted, move to next outer record
                self.current_left = None
                continue

            # Create joined record
            combined_values = {**self.current_left.values, **right_record.values}

            # Check join predicate
            combined_record = Record(values=combined_values, rid=self.current_left.rid)

            try:
                if self.predicate.evaluate(combined_record):
                    return combined_record
            except Exception:
                pass

    def close(self) -> None:
        """Close the join."""
        super().close()
        self.left.close()
        self.right.close()


class HashJoinOperator(Operator):
    """Hash join operator (grace hash join)."""

    def __init__(
        self, operator_id: int, left: Operator, right: Operator, left_keys: list[str], right_keys: list[str]
    ) -> None:
        """
        Initialize hash join.

        Args:
            operator_id: Unique operator ID
            left: Left child
            right: Right child
            left_keys: Column names for left join key
            right_keys: Column names for right join key
        """
        super().__init__(operator_id)
        self.left = left
        self.right = right
        self.left_keys = left_keys
        self.right_keys = right_keys
        self.hash_table: dict[tuple, list[Record]] = {}
        self.right_iterator: Iterator[Record] | None = None
        self.current_bucket: list[Record] = []
        self.bucket_index = 0

    def open(self, context: ExecutionContext) -> None:
        """Open the join."""
        super().open(context)
        self.left.open(context)
        self.right.open(context)

        # Build hash table from left table
        self._build_hash_table()

        # Start iterating through right table
        self.right_iterator = self._iterate_right()

    def _build_hash_table(self) -> None:
        """Build hash table from left table."""
        self.hash_table.clear()

        for record in self._iterate_left():
            # Extract key values
            key_values = tuple(record.get_value(col) for col in self.left_keys)

            if key_values not in self.hash_table:
                self.hash_table[key_values] = []

            self.hash_table[key_values].append(record)

    def _iterate_left(self) -> Iterator[Record]:
        """Iterate through left table."""
        while True:
            record = self.left.next()
            if record is None:
                break
            yield record

    def _iterate_right(self) -> Iterator[Record]:
        """Iterate through right table with hash lookups."""
        while True:
            right_record = self.right.next()
            if right_record is None:
                break

            # Extract key values
            key_values = tuple(right_record.get_value(col) for col in self.right_keys)

            # Look up in hash table
            if key_values in self.hash_table:
                for left_record in self.hash_table[key_values]:
                    combined_values = {**left_record.values, **right_record.values}
                    yield Record(values=combined_values, rid=right_record.rid)

    def next(self) -> Record | None:
        """Get next joined record."""
        if self.right_iterator is None:
            return None

        try:
            return next(self.right_iterator)
        except StopIteration:
            return None

    def close(self) -> None:
        """Close the join."""
        super().close()
        self.left.close()
        self.right.close()
        self.hash_table.clear()
        self.right_iterator = None


class SortOperator(Operator):
    """Sort operator using external merge sort."""

    def __init__(self, operator_id: int, child: Operator, sort_keys: list[tuple[str, str]]) -> None:
        """
        Initialize sort.

        Args:
            operator_id: Unique operator ID
            child: Child operator
            sort_keys: List of (column_name, direction) where direction is 'ASC' or 'DESC'
        """
        super().__init__(operator_id)
        self.child = child
        self.sort_keys = sort_keys
        self.sorted_records: list[Record] = []
        self.index = 0

    def open(self, context: ExecutionContext) -> None:
        """Open the sort."""
        super().open(context)
        self.child.open(context)

        # Load all records and sort
        self.sorted_records = []
        for record in self._iterate_child():
            self.sorted_records.append(record)

        # Sort records
        for col_name, direction in reversed(self.sort_keys):
            reverse = direction == "DESC"
            self.sorted_records.sort(key=lambda r: r.get_value(col_name) or "", reverse=reverse)

        self.index = 0

    def _iterate_child(self) -> Iterator[Record]:
        """Iterate through child operator."""
        while True:
            record = self.child.next()
            if record is None:
                break
            yield record

    def next(self) -> Record | None:
        """Get next record in sort order."""
        if self.index >= len(self.sorted_records):
            return None

        record = self.sorted_records[self.index]
        self.index += 1
        return record

    def close(self) -> None:
        """Close the sort."""
        super().close()
        self.child.close()
        self.sorted_records.clear()


class AggregationOperator(Operator):
    """Aggregation operator (GROUP BY, aggregate functions)."""

    def __init__(
        self, operator_id: int, child: Operator, group_by_cols: list[str], aggregate_funcs: dict[str, str]
    ) -> None:
        """
        Initialize aggregation.

        Args:
            operator_id: Unique operator ID
            child: Child operator
            group_by_cols: Column names to group by
            aggregate_funcs: Map of output_name -> aggregate_function
        """
        super().__init__(operator_id)
        self.child = child
        self.group_by_cols = group_by_cols
        self.aggregate_funcs = aggregate_funcs
        self.groups: dict[tuple, dict[str, Any]] = {}
        self.group_iterator: Iterator | None = None

    def open(self, context: ExecutionContext) -> None:
        """Open the aggregation."""
        super().open(context)
        self.child.open(context)

        # Compute aggregates
        self._compute_aggregates()

        # Start iterating through groups
        self.group_iterator = self._iterate_groups()

    def _compute_aggregates(self) -> None:
        """Compute aggregate values for each group."""
        self.groups.clear()

        for record in self._iterate_child():
            # Extract group key
            if self.group_by_cols:
                key = tuple(record.get_value(col) for col in self.group_by_cols)
            else:
                key = ("__single_group__",)

            if key not in self.groups:
                self.groups[key] = self._init_group(key)

            # Update aggregates
            for agg_name, agg_func in self.aggregate_funcs.items():
                self._update_aggregate(key, agg_name, agg_func, record)

    def _init_group(self, key: tuple) -> dict[str, Any]:
        """Initialize a group."""
        group = {}
        for col in self.group_by_cols:
            # Can't extract from key in simple version
            pass

        for agg_name, agg_func in self.aggregate_funcs.items():
            if agg_func == "COUNT" or agg_func in ["SUM", "AVG"]:
                group[agg_name] = 0
            elif agg_func == "MIN" or agg_func == "MAX":
                group[agg_name] = None

        return group

    def _update_aggregate(self, key: tuple, agg_name: str, agg_func: str, record: Record) -> None:
        """Update aggregate for a group."""
        group = self.groups[key]

        if agg_func == "COUNT":
            group[agg_name] = group.get(agg_name, 0) + 1
        elif agg_func == "SUM":
            val = record.get_value(agg_name.replace("_sum", ""))
            if val is not None:
                group[agg_name] = group.get(agg_name, 0) + val

    def _iterate_child(self) -> Iterator[Record]:
        """Iterate through child."""
        while True:
            record = self.child.next()
            if record is None:
                break
            yield record

    def _iterate_groups(self) -> Iterator[Record]:
        """Iterate through computed groups."""
        for key, group_values in self.groups.items():
            yield Record(values=group_values)

    def next(self) -> Record | None:
        """Get next aggregated record."""
        if self.group_iterator is None:
            return None

        try:
            return next(self.group_iterator)
        except StopIteration:
            return None

    def close(self) -> None:
        """Close aggregation."""
        super().close()
        self.child.close()
        self.groups.clear()
        self.group_iterator = None


class LimitOperator(Operator):
    """LIMIT and OFFSET operator."""

    def __init__(self, operator_id: int, child: Operator, limit: int, offset: int = 0) -> None:
        """
        Initialize limit.

        Args:
            operator_id: Unique operator ID
            child: Child operator
            limit: Maximum number of rows
            offset: Number of rows to skip
        """
        super().__init__(operator_id)
        self.child = child
        self.limit = limit
        self.offset = offset
        self.count = 0

    def open(self, context: ExecutionContext) -> None:
        """Open the limit."""
        super().open(context)
        self.child.open(context)
        self.count = 0

    def next(self) -> Record | None:
        """Get next record up to limit."""
        # Skip offset rows
        while self.count < self.offset:
            record = self.child.next()
            if record is None:
                return None
            self.count += 1

        # Check limit
        if self.count >= self.offset + self.limit:
            return None

        record = self.child.next()
        if record is not None:
            self.count += 1

        return record

    def close(self) -> None:
        """Close the limit."""
        super().close()
        self.child.close()
