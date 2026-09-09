"""
Tests for query executor.

Tests cover:
- Sequential scan operator
- Filter operator
- Projection operator
- Join operators (nested loop, hash join)
- Sort operator
- Aggregation operator
- LIMIT/OFFSET operator
- Expression evaluation
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thomas.marketplace.db_internals import (
    BinaryOpNode,
    BufferPool,
    Column,
    ColumnNode,
    DataType,
    LiteralNode,
    Record,
    Table,
)
from thomas.marketplace.db_internals.executor import (
    AggregationOperator,
    ExecutionContext,
    FilterOperator,
    HashJoinOperator,
    LimitOperator,
    NestedLoopJoinOperator,
    ProjectionOperator,
    SeqScanOperator,
    SortOperator,
)


class TestExecutionContext:
    """Tests for execution context."""

    def test_create_context(self) -> None:
        """Test creating execution context."""
        ctx = ExecutionContext(buffer_pool=BufferPool(), tables={}, heap_files={}, indexes={})
        assert ctx.buffer_pool is not None


class TestSeqScanOperator:
    """Tests for sequential scan."""

    def test_seq_scan_empty_table(self) -> None:
        """Test scanning empty table."""
        table = Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        ctx = ExecutionContext(buffer_pool=BufferPool(), tables={"t": table}, heap_files={}, indexes={})

        op = SeqScanOperator(1, "t")
        records = []
        op.open(ctx)
        while True:
            rec = op.next()
            if rec is None:
                break
            records.append(rec)
        op.close()

        assert len(records) == 0

    def test_seq_scan_missing_table(self) -> None:
        """Test scanning non-existent table."""
        ctx = ExecutionContext(buffer_pool=BufferPool(), tables={}, heap_files={}, indexes={})

        op = SeqScanOperator(1, "missing")

        with pytest.raises(Exception):
            op.open(ctx)


class TestFilterOperator:
    """Tests for filter operator."""

    def test_filter_basic(self) -> None:
        """Test basic filtering."""
        # Create predicate: a > 5
        predicate = BinaryOpNode(operator=">", left=ColumnNode(column_name="a"), right=LiteralNode(value=5))

        # Create fake scan that returns records
        table = Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        ExecutionContext(buffer_pool=BufferPool(), tables={"t": table}, heap_files={}, indexes={})

        # Create a mock scan operator
        scan = SeqScanOperator(1, "t")
        filter_op = FilterOperator(2, scan, predicate)

        assert filter_op.child is scan


class TestProjectionOperator:
    """Tests for projection operator."""

    def test_projection_basic(self) -> None:
        """Test basic projection."""
        table = Table(
            table_id=1,
            name="t",
            columns=[Column(name="a", data_type=DataType.INT), Column(name="b", data_type=DataType.VARCHAR)],
        )

        ExecutionContext(buffer_pool=BufferPool(), tables={"t": table}, heap_files={}, indexes={})

        scan = SeqScanOperator(1, "t")
        proj = ProjectionOperator(2, scan, ["a"])

        assert proj.columns == ["a"]

    def test_projection_star(self) -> None:
        """Test SELECT * projection."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        ProjectionOperator(2, scan, ["*"])

        # Should project all columns
        Record(values={"a": 1})


class TestSortOperator:
    """Tests for sort operator."""

    def test_sort_basic(self) -> None:
        """Test basic sorting."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        sort = SortOperator(2, scan, [("a", "ASC")])

        assert sort.sort_keys == [("a", "ASC")]

    def test_sort_multiple_keys(self) -> None:
        """Test sorting with multiple keys."""
        Table(
            table_id=1,
            name="t",
            columns=[Column(name="a", data_type=DataType.INT), Column(name="b", data_type=DataType.INT)],
        )

        scan = SeqScanOperator(1, "t")
        sort = SortOperator(2, scan, [("a", "ASC"), ("b", "DESC")])

        assert len(sort.sort_keys) == 2


class TestLimitOperator:
    """Tests for LIMIT operator."""

    def test_limit_basic(self) -> None:
        """Test basic LIMIT."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        limit = LimitOperator(2, scan, limit=10)

        assert limit.limit == 10
        assert limit.offset == 0

    def test_limit_with_offset(self) -> None:
        """Test LIMIT with OFFSET."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        limit = LimitOperator(2, scan, limit=10, offset=5)

        assert limit.limit == 10
        assert limit.offset == 5


class TestAggregationOperator:
    """Tests for aggregation operator."""

    def test_aggregation_basic(self) -> None:
        """Test basic aggregation."""
        Table(
            table_id=1,
            name="t",
            columns=[Column(name="a", data_type=DataType.INT), Column(name="b", data_type=DataType.INT)],
        )

        scan = SeqScanOperator(1, "t")
        agg = AggregationOperator(2, scan, group_by_cols=["a"], aggregate_funcs={"count": "COUNT"})

        assert agg.group_by_cols == ["a"]

    def test_aggregation_multiple_functions(self) -> None:
        """Test aggregation with multiple functions."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        agg = AggregationOperator(
            2, scan, group_by_cols=[], aggregate_funcs={"count": "COUNT", "sum_a": "SUM", "avg_a": "AVG"}
        )

        assert len(agg.aggregate_funcs) == 3


class TestNestedLoopJoinOperator:
    """Tests for nested loop join."""

    def test_nested_loop_join_basic(self) -> None:
        """Test basic nested loop join."""
        Table(table_id=1, name="t1", columns=[Column(name="a", data_type=DataType.INT)])

        Table(table_id=2, name="t2", columns=[Column(name="b", data_type=DataType.INT)])

        predicate = BinaryOpNode(operator="=", left=ColumnNode(column_name="a"), right=ColumnNode(column_name="b"))

        left = SeqScanOperator(1, "t1")
        right = SeqScanOperator(2, "t2")
        join = NestedLoopJoinOperator(3, left, right, predicate)

        assert join.predicate is predicate


class TestHashJoinOperator:
    """Tests for hash join."""

    def test_hash_join_basic(self) -> None:
        """Test basic hash join."""
        Table(table_id=1, name="t1", columns=[Column(name="a", data_type=DataType.INT)])

        Table(table_id=2, name="t2", columns=[Column(name="b", data_type=DataType.INT)])

        left = SeqScanOperator(1, "t1")
        right = SeqScanOperator(2, "t2")
        join = HashJoinOperator(3, left, right, left_keys=["a"], right_keys=["b"])

        assert join.left_keys == ["a"]
        assert join.right_keys == ["b"]


class TestOperatorChaining:
    """Tests for operator pipeline."""

    def test_operator_pipeline(self) -> None:
        """Test chaining operators together."""
        Table(table_id=1, name="t", columns=[Column(name="a", data_type=DataType.INT)])

        scan = SeqScanOperator(1, "t")
        limit = LimitOperator(2, scan, limit=10)

        # Verify pipeline is set up
        assert limit.child is scan


class TestExpressionEvaluation:
    """Tests for expression evaluation in operators."""

    def test_binary_op_evaluation(self) -> None:
        """Test evaluating binary operations."""
        record = Record(values={"a": 10, "b": 5})

        expr = BinaryOpNode(operator=">", left=ColumnNode(column_name="a"), right=LiteralNode(value=7))

        result = expr.evaluate(record)
        assert result is True

    def test_arithmetic_evaluation(self) -> None:
        """Test evaluating arithmetic."""
        record = Record(values={"a": 10, "b": 5})

        expr = BinaryOpNode(operator="+", left=ColumnNode(column_name="a"), right=ColumnNode(column_name="b"))

        result = expr.evaluate(record)
        assert result == 15

    def test_logical_and(self) -> None:
        """Test logical AND."""
        record = Record(values={"a": 10, "b": 5})

        expr = BinaryOpNode(
            operator="AND",
            left=BinaryOpNode(operator=">", left=ColumnNode(column_name="a"), right=LiteralNode(value=7)),
            right=BinaryOpNode(operator="<", left=ColumnNode(column_name="b"), right=LiteralNode(value=10)),
        )

        result = expr.evaluate(record)
        assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
