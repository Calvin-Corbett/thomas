"""
Tests for vectorized query execution engine.
"""

import pytest

from thomas.marketplace.columnar._types import ColumnType
from thomas.marketplace.columnar.query import (
    ColumnBatch,
    HashAggregator,
    QueryExecutor,
    VectorizedAggregation,
    VectorizedArithmetic,
    VectorizedFilter,
)


class TestColumnBatch:
    """Tests for column batch operations."""

    def test_create_batch(self) -> None:
        """Test creating column batch."""
        values = [1, 2, 3, 4, 5]
        batch = ColumnBatch("id", ColumnType.INT32, values)

        assert batch.column_name == "id"
        assert batch.column_type == ColumnType.INT32
        assert batch.length == 5

    def test_apply_filter(self) -> None:
        """Test applying filter mask to batch."""
        values = [1, 2, 3, 4, 5]
        batch = ColumnBatch("id", ColumnType.INT32, values)

        mask = [True, False, True, False, True]
        filtered = batch.apply_filter(mask)

        assert filtered.length == 3
        assert filtered.values == [1, 3, 5]

    def test_map_values(self) -> None:
        """Test mapping function over batch."""
        values = [1, 2, 3, 4, 5]
        batch = ColumnBatch("id", ColumnType.INT32, values)

        mapped = batch.map_values(lambda x: x * 2)

        assert mapped.values == [2, 4, 6, 8, 10]


class TestVectorizedFilter:
    """Tests for vectorized filter operations."""

    def test_equal_filter(self) -> None:
        """Test equality filter."""
        values = [1, 2, 3, 2, 1]
        batch = ColumnBatch("id", ColumnType.INT32, values)

        mask = VectorizedFilter.equal(batch, 2)

        assert mask == [False, True, False, True, False]

    def test_less_than_filter(self) -> None:
        """Test less-than filter."""
        values = [1, 5, 3, 2, 4]
        batch = ColumnBatch("id", ColumnType.INT32, values)

        mask = VectorizedFilter.less_than(batch, 3)

        assert mask == [True, False, False, True, False]

    def test_in_list_filter(self) -> None:
        """Test in-list filter."""
        values = ["apple", "banana", "cherry", "apple"]
        batch = ColumnBatch("fruit", ColumnType.STRING, values)

        mask = VectorizedFilter.in_list(batch, ["apple", "cherry"])

        assert mask == [True, False, True, True]

    def test_is_null_filter(self) -> None:
        """Test null filter."""
        values = [1, None, 3, None, 5]
        batch = ColumnBatch("value", ColumnType.INT32, values)

        mask = VectorizedFilter.is_null(batch)

        assert mask == [False, True, False, True, False]

    def test_combine_filters_and(self) -> None:
        """Test combining filters with AND."""
        mask1 = [True, False, True, False]
        mask2 = [True, True, False, False]

        combined = VectorizedFilter.and_mask(mask1, mask2)

        assert combined == [True, False, False, False]

    def test_combine_filters_or(self) -> None:
        """Test combining filters with OR."""
        mask1 = [True, False, True, False]
        mask2 = [False, True, False, False]

        combined = VectorizedFilter.or_mask(mask1, mask2)

        assert combined == [True, True, True, False]

    def test_count_true(self) -> None:
        """Test counting true values in mask."""
        mask = [True, False, True, True, False]

        count = VectorizedFilter.count_true(mask)

        assert count == 3


class TestVectorizedArithmetic:
    """Tests for vectorized arithmetic operations."""

    def test_add_batches(self) -> None:
        """Test adding two batches."""
        batch1 = ColumnBatch("a", ColumnType.INT32, [1, 2, 3])
        batch2 = ColumnBatch("b", ColumnType.INT32, [4, 5, 6])

        result = VectorizedArithmetic.add(batch1, batch2)

        assert result.values == [5, 7, 9]

    def test_subtract_batches(self) -> None:
        """Test subtracting two batches."""
        batch1 = ColumnBatch("a", ColumnType.INT32, [10, 20, 30])
        batch2 = ColumnBatch("b", ColumnType.INT32, [3, 5, 7])

        result = VectorizedArithmetic.subtract(batch1, batch2)

        assert result.values == [7, 15, 23]

    def test_multiply_batches(self) -> None:
        """Test multiplying two batches."""
        batch1 = ColumnBatch("a", ColumnType.INT32, [2, 3, 4])
        batch2 = ColumnBatch("b", ColumnType.INT32, [5, 6, 7])

        result = VectorizedArithmetic.multiply(batch1, batch2)

        assert result.values == [10, 18, 28]

    def test_divide_batches(self) -> None:
        """Test dividing two batches."""
        batch1 = ColumnBatch("a", ColumnType.FLOAT64, [10.0, 20.0, 30.0])
        batch2 = ColumnBatch("b", ColumnType.FLOAT64, [2.0, 4.0, 5.0])

        result = VectorizedArithmetic.divide(batch1, batch2)

        assert len(result.values) == 3
        assert result.values[0] == pytest.approx(5.0)

    def test_arithmetic_with_nulls(self) -> None:
        """Test arithmetic with null values."""
        batch1 = ColumnBatch("a", ColumnType.INT32, [1, None, 3])
        batch2 = ColumnBatch("b", ColumnType.INT32, [4, 5, None])

        result = VectorizedArithmetic.add(batch1, batch2)

        assert result.values[0] == 5
        assert result.values[1] is None
        assert result.values[2] is None


class TestVectorizedAggregation:
    """Tests for vectorized aggregation operations."""

    def test_sum_aggregation(self) -> None:
        """Test sum aggregation."""
        batch = ColumnBatch("value", ColumnType.INT32, [1, 2, 3, 4, 5])

        total = VectorizedAggregation.sum(batch)

        assert total == 15

    def test_count_aggregation(self) -> None:
        """Test count aggregation."""
        batch = ColumnBatch("value", ColumnType.INT32, [1, None, 3, None, 5])

        count = VectorizedAggregation.count(batch)

        assert count == 3

    def test_min_aggregation(self) -> None:
        """Test min aggregation."""
        batch = ColumnBatch("value", ColumnType.INT32, [5, 2, 8, 1, 9])

        min_val = VectorizedAggregation.min(batch)

        assert min_val == 1

    def test_max_aggregation(self) -> None:
        """Test max aggregation."""
        batch = ColumnBatch("value", ColumnType.INT32, [5, 2, 8, 1, 9])

        max_val = VectorizedAggregation.max(batch)

        assert max_val == 9

    def test_avg_aggregation(self) -> None:
        """Test average aggregation."""
        batch = ColumnBatch("value", ColumnType.FLOAT64, [1.0, 2.0, 3.0, 4.0, 5.0])

        avg = VectorizedAggregation.avg(batch)

        assert avg == pytest.approx(3.0)

    def test_count_distinct(self) -> None:
        """Test count distinct."""
        batch = ColumnBatch("value", ColumnType.INT32, [1, 2, 1, 3, 2, 1])

        distinct = VectorizedAggregation.count_distinct(batch)

        assert distinct == 3

    def test_stddev_aggregation(self) -> None:
        """Test standard deviation."""
        batch = ColumnBatch("value", ColumnType.FLOAT64, [1.0, 2.0, 3.0, 4.0, 5.0])

        stddev = VectorizedAggregation.stddev(batch)

        assert stddev is not None
        assert stddev > 0

    def test_group_by_aggregation(self) -> None:
        """Test group-by aggregation."""
        batch = ColumnBatch("value", ColumnType.INT32, [10, 20, 10, 30])
        groups = [1, 1, 2, 2]

        result = VectorizedAggregation.group_by(batch, groups)

        assert len(result) == 2
        assert 1 in result
        assert 2 in result


class TestHashAggregator:
    """Tests for hash aggregation."""

    def test_add_values(self) -> None:
        """Test adding values to groups."""
        agg = HashAggregator()

        agg.add("group_a", {"value": 10})
        agg.add("group_a", {"value": 20})
        agg.add("group_b", {"value": 30})

        results = agg.get_results()
        assert len(results) == 2

    def test_get_aggregate(self) -> None:
        """Test getting aggregate for group."""
        agg = HashAggregator()

        agg.add("group_a", {"value": 10})
        agg.add("group_a", {"value": 20})
        agg.add("group_b", {"value": 30})

        sum_a = agg.get_aggregate("group_a", "value", "sum")
        assert sum_a == 30

        sum_b = agg.get_aggregate("group_b", "value", "sum")
        assert sum_b == 30

    def test_count_aggregate(self) -> None:
        """Test count aggregate."""
        agg = HashAggregator()

        agg.add("group_a", {"value": 10})
        agg.add("group_a", {"value": 20})
        agg.add("group_b", {"value": 30})

        count_a = agg.get_aggregate("group_a", "value", "count")
        assert count_a == 2

        count_b = agg.get_aggregate("group_b", "value", "count")
        assert count_b == 1


class TestQueryExecutor:
    """Tests for query executor."""

    def test_filter_query(self) -> None:
        """Test simple filter query."""
        executor = QueryExecutor()
        executor.batches["id"] = ColumnBatch("id", ColumnType.INT32, [1, 2, 3, 4, 5])

        mask = executor.filter("id", ">", 2)

        assert mask == [False, False, True, True, True]

    def test_aggregate_query(self) -> None:
        """Test aggregate query."""
        executor = QueryExecutor()
        executor.batches["value"] = ColumnBatch("value", ColumnType.INT32, [1, 2, 3, 4, 5])

        total = executor.aggregate("value", "sum")

        assert total == 15

    def test_project_query(self) -> None:
        """Test projection query."""
        executor = QueryExecutor()
        executor.batches["id"] = ColumnBatch("id", ColumnType.INT32, [1, 2, 3])
        executor.batches["name"] = ColumnBatch("name", ColumnType.STRING, ["a", "b", "c"])

        results = executor.project(["id", "name"])

        assert len(results) == 3
        assert results[0] == {"id": 1, "name": "a"}

    def test_filtered_projection(self) -> None:
        """Test filtered projection."""
        executor = QueryExecutor()
        executor.batches["id"] = ColumnBatch("id", ColumnType.INT32, [1, 2, 3, 4, 5])
        executor.batches["value"] = ColumnBatch("value", ColumnType.INT32, [10, 20, 30, 40, 50])

        mask = executor.filter("id", ">", 2)
        executor.apply_mask(mask)

        results = executor.project(["id", "value"])

        assert len(results) == 3
