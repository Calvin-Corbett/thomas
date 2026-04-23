"""Tests for GroupBy operations."""

import pytest
from _exceptions import ColumnNotFoundError, DataFrameError
from frame import DataFrame
from groupby import GroupBy


class TestGroupByConstruction:
    """Test GroupBy initialization."""

    def test_groupby_single_column(self) -> None:
        """Test groupby with single column."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        assert len(gb._groups) == 2

    def test_groupby_multiple_columns(self) -> None:
        """Test groupby with multiple columns."""
        df = DataFrame({"group1": ["a", "a", "b", "b"], "group2": ["x", "y", "x", "y"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, ["group1", "group2"])
        assert len(gb._groups) == 4

    def test_groupby_missing_column(self) -> None:
        """Test groupby with non-existent column."""
        df = DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ColumnNotFoundError):
            GroupBy(df, "missing")


class TestGroupByAggregation:
    """Test aggregation functions."""

    def test_count(self) -> None:
        """Test count aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b", "b"], "value": [1, 2, 3, 4, 5]})
        gb = GroupBy(df, "group")
        result = gb.count()
        assert result.shape[0] == 2

    def test_sum(self) -> None:
        """Test sum aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        result = gb.sum()
        assert result.shape[0] == 2

    def test_mean(self) -> None:
        """Test mean aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 3.0, 4.0, 8.0]})
        gb = GroupBy(df, "group")
        result = gb.mean()
        assert result.shape[0] == 2

    def test_min(self) -> None:
        """Test min aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [5, 2, 8, 3]})
        gb = GroupBy(df, "group")
        result = gb.min()
        assert result.shape[0] == 2

    def test_max(self) -> None:
        """Test max aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [5, 2, 8, 3]})
        gb = GroupBy(df, "group")
        result = gb.max()
        assert result.shape[0] == 2

    def test_std(self) -> None:
        """Test std aggregation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1.0, 2.0, 3.0, 4.0]})
        gb = GroupBy(df, "group")
        result = gb.std()
        assert result.shape[0] == 2

    def test_first(self) -> None:
        """Test first value."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [10, 20, 30, 40]})
        gb = GroupBy(df, "group")
        result = gb.first()
        assert result.shape[0] == 2

    def test_last(self) -> None:
        """Test last value."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [10, 20, 30, 40]})
        gb = GroupBy(df, "group")
        result = gb.last()
        assert result.shape[0] == 2


class TestGroupByAggregate:
    """Test aggregate method."""

    def test_aggregate_string(self) -> None:
        """Test aggregate with string function name."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        result = gb.aggregate("sum")
        assert result.shape[0] == 2

    def test_aggregate_dict(self) -> None:
        """Test aggregate with dict."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        result = gb.aggregate({"value": "sum"})
        assert result.shape[0] == 2

    def test_aggregate_unknown_func(self) -> None:
        """Test aggregate with unknown function."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        with pytest.raises(DataFrameError):
            gb.aggregate("unknown")


class TestGroupByTransform:
    """Test transform method."""

    def test_transform(self) -> None:
        """Test transform operation."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        # Transform returns a Series/DataFrame per group
        result = gb.transform(lambda s: s * 2)
        assert result.shape[0] == 4


class TestGroupByFilter:
    """Test filter method."""

    def test_filter(self) -> None:
        """Test filter operation."""
        df = DataFrame({"group": ["a", "a", "a", "b", "b"], "value": [1, 2, 3, 4, 5]})
        gb = GroupBy(df, "group")
        # Filter groups where size > 2
        result = gb.filter(lambda g: len(g._index) > 2)
        assert result.shape[0] == 3  # Only 'a' group


class TestGroupByIteration:
    """Test iteration over groups."""

    def test_iter(self) -> None:
        """Test iteration over groups."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        groups = list(gb)
        assert len(groups) == 2

    def test_iter_group_structure(self) -> None:
        """Test structure of iterated groups."""
        df = DataFrame({"group": ["a", "a", "b"], "value": [1, 2, 3]})
        gb = GroupBy(df, "group")
        for key, group_df in gb:
            assert isinstance(group_df, DataFrame)
            assert "value" in group_df.columns

    def test_get_group(self) -> None:
        """Test get_group method."""
        df = DataFrame({"group": ["a", "a", "b", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        group_a = gb.get_group("a")
        assert group_a.shape[0] == 2

    def test_get_group_missing(self) -> None:
        """Test get_group with missing key."""
        df = DataFrame({"group": ["a", "a", "b"], "value": [1, 2, 3]})
        gb = GroupBy(df, "group")
        with pytest.raises(DataFrameError):
            gb.get_group("c")


class TestGroupBySize:
    """Test size method."""

    def test_size(self) -> None:
        """Test size method."""
        df = DataFrame({"group": ["a", "a", "a", "b", "b"], "value": [1, 2, 3, 4, 5]})
        gb = GroupBy(df, "group")
        sizes = gb.size()
        assert sizes["a"] == 3
        assert sizes["b"] == 2


class TestGroupByMultipleColumns:
    """Test groupby with multiple groupby columns."""

    def test_groupby_two_columns(self) -> None:
        """Test groupby with two columns."""
        df = DataFrame({"g1": ["a", "a", "b", "b"], "g2": ["x", "y", "x", "y"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, ["g1", "g2"])
        result = gb.count()
        assert result.shape[0] == 4

    def test_groupby_aggregate_multikey(self) -> None:
        """Test aggregate with multiple groupby keys."""
        df = DataFrame({"g1": ["a", "a", "b", "b"], "g2": ["x", "y", "x", "y"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, ["g1", "g2"])
        result = gb.aggregate({"value": "sum"})
        assert result.shape[0] == 4


class TestGroupByEdgeCases:
    """Test edge cases."""

    def test_groupby_with_nulls(self) -> None:
        """Test groupby with null values."""
        df = DataFrame({"group": ["a", None, "a", "b"], "value": [1, 2, 3, 4]})
        gb = GroupBy(df, "group")
        result = gb.count()
        assert result.shape[0] >= 2

    def test_groupby_single_group(self) -> None:
        """Test groupby with single group."""
        df = DataFrame({"group": ["a", "a", "a"], "value": [1, 2, 3]})
        gb = GroupBy(df, "group")
        result = gb.sum()
        assert result.shape[0] == 1
