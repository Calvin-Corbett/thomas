"""Tests for join/merge operations."""

import pytest
from _exceptions import MergeError
from frame import DataFrame
from joins import JoinOperation


class TestInnerJoin:
    """Test inner join operation."""

    def test_inner_join_single_key(self) -> None:
        """Test inner join on single key."""
        left = DataFrame({"id": [1, 2, 3], "val_left": ["a", "b", "c"]})
        right = DataFrame({"id": [2, 3, 4], "val_right": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "id", "inner")
        assert result.shape[0] == 2  # Only 2 and 3

    def test_inner_join_hash_algorithm(self) -> None:
        """Test inner join with hash algorithm."""
        left = DataFrame({"key": [1, 2, 3], "val": ["a", "b", "c"]})
        right = DataFrame({"key": [2, 3, 4], "val2": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "key", "inner", "hash")
        assert result.shape[0] == 2

    def test_inner_join_sort_algorithm(self) -> None:
        """Test inner join with sort-merge algorithm."""
        left = DataFrame({"key": [1, 2, 3], "val": ["a", "b", "c"]})
        right = DataFrame({"key": [2, 3, 4], "val2": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "key", "inner", "sort")
        assert result.shape[0] == 2


class TestLeftJoin:
    """Test left join operation."""

    def test_left_join(self) -> None:
        """Test left join keeps all left rows."""
        left = DataFrame({"id": [1, 2, 3], "val_left": ["a", "b", "c"]})
        right = DataFrame({"id": [2, 3, 4], "val_right": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "id", "left")
        assert result.shape[0] == 3


class TestRightJoin:
    """Test right join operation."""

    def test_right_join(self) -> None:
        """Test right join keeps all right rows."""
        left = DataFrame({"id": [1, 2, 3], "val_left": ["a", "b", "c"]})
        right = DataFrame({"id": [2, 3, 4], "val_right": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "id", "right")
        assert result.shape[0] == 3


class TestOuterJoin:
    """Test outer join operation."""

    def test_outer_join(self) -> None:
        """Test outer join keeps all rows."""
        left = DataFrame({"id": [1, 2, 3], "val_left": ["a", "b", "c"]})
        right = DataFrame({"id": [2, 3, 4], "val_right": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, "id", "outer")
        assert result.shape[0] == 4


class TestJoinOnMapping:
    """Test join with column mapping."""

    def test_join_dict_mapping(self) -> None:
        """Test join with dict key mapping."""
        left = DataFrame({"left_id": [1, 2, 3], "val": ["a", "b", "c"]})
        right = DataFrame({"right_id": [2, 3, 4], "val2": ["x", "y", "z"]})
        result = JoinOperation.join(left, right, {"left_id": "right_id"}, "inner")
        assert result.shape[0] == 2

    def test_join_list_mapping(self) -> None:
        """Test join with list of columns."""
        left = DataFrame({"key1": [1, 1, 2], "key2": ["a", "b", "a"], "val": [10, 20, 30]})
        right = DataFrame({"key1": [1, 2], "key2": ["a", "a"], "val2": [100, 200]})
        result = JoinOperation.join(left, right, ["key1", "key2"], "inner")
        assert result.shape[0] >= 1


class TestConcat:
    """Test concatenation operations."""

    def test_concat_vertical(self) -> None:
        """Test vertical (row) concatenation."""
        df1 = DataFrame({"a": [1, 2], "b": [3, 4]})
        df2 = DataFrame({"a": [5, 6], "b": [7, 8]})
        result = JoinOperation.concat([df1, df2], axis=0)
        assert result.shape[0] == 4
        assert result.shape[1] == 2

    def test_concat_horizontal(self) -> None:
        """Test horizontal (column) concatenation."""
        df1 = DataFrame({"a": [1, 2, 3]})
        df2 = DataFrame({"b": [4, 5, 6]})
        result = JoinOperation.concat([df1, df2], axis=1)
        assert result.shape[0] == 3
        assert result.shape[1] == 2

    def test_concat_ignore_index(self) -> None:
        """Test concat with ignore_index."""
        df1 = DataFrame({"a": [1, 2]}, index=["x", "y"])
        df2 = DataFrame({"a": [3, 4]}, index=["x", "y"])
        result = JoinOperation.concat([df1, df2], axis=0, ignore_index=True)
        assert result.shape[0] == 4


class TestCrossJoin:
    """Test cross join (Cartesian product)."""

    def test_cross_join(self) -> None:
        """Test cross join."""
        df1 = DataFrame({"a": [1, 2]})
        df2 = DataFrame({"b": [10, 20, 30]})
        result = JoinOperation.cross_join(df1, df2)
        assert result.shape[0] == 6  # 2 * 3
        assert result.shape[1] == 2


class TestJoinErrors:
    """Test error handling."""

    def test_invalid_join_type(self) -> None:
        """Test invalid join type."""
        df1 = DataFrame({"a": [1, 2]})
        df2 = DataFrame({"a": [3, 4]})
        with pytest.raises(ValueError):
            JoinOperation.join(df1, df2, "a", "invalid")

    def test_missing_left_column(self) -> None:
        """Test join with missing left column."""
        left = DataFrame({"x": [1, 2]})
        right = DataFrame({"y": [3, 4]})
        with pytest.raises(MergeError):
            JoinOperation.join(left, right, "missing", "inner")

    def test_missing_right_column(self) -> None:
        """Test join with missing right column."""
        left = DataFrame({"a": [1, 2]})
        right = DataFrame({"b": [3, 4]})
        with pytest.raises(MergeError):
            JoinOperation.join(left, right, {"a": "missing"}, "inner")

    def test_invalid_algorithm(self) -> None:
        """Test invalid join algorithm."""
        left = DataFrame({"a": [1, 2]})
        right = DataFrame({"a": [3, 4]})
        with pytest.raises(ValueError):
            JoinOperation.join(left, right, "a", "inner", "invalid")


class TestJoinDataIntegrity:
    """Test data integrity in joins."""

    def test_inner_join_no_duplicates_simple(self) -> None:
        """Test inner join without duplicate keys."""
        left = DataFrame({"key": [1, 2, 3], "val": ["a", "b", "c"]})
        right = DataFrame({"key": [1, 3], "val2": ["x", "z"]})
        result = JoinOperation.join(left, right, "key", "inner")
        assert result.shape[0] == 2

    def test_join_preserves_values(self) -> None:
        """Test that join preserves values correctly."""
        left = DataFrame({"id": [1, 2], "val": ["hello", "world"]})
        right = DataFrame({"id": [1, 2], "val2": ["foo", "bar"]})
        result = JoinOperation.join(left, right, "id", "inner")
        assert result["val"][0] == "hello"
        assert result["val2"][0] == "foo"

    def test_concat_preserves_order(self) -> None:
        """Test that concat preserves row order."""
        df1 = DataFrame({"a": [1, 2, 3]})
        df2 = DataFrame({"a": [4, 5, 6]})
        result = JoinOperation.concat([df1, df2], axis=0)
        assert result["a"][0] == 1
        assert result["a"][3] == 4


class TestJoinWithNulls:
    """Test join behavior with null values."""

    def test_join_with_nulls(self) -> None:
        """Test join with null values in key."""
        left = DataFrame({"id": [1, None, 3], "val": ["a", "b", "c"]})
        right = DataFrame({"id": [1, 3], "val2": ["x", "z"]})
        result = JoinOperation.join(left, right, "id", "inner")
        assert result.shape[0] == 2


class TestJoinPerformance:
    """Test join with larger datasets."""

    def test_join_large_dataset(self) -> None:
        """Test join with larger datasets."""
        left = DataFrame({"id": list(range(100)), "val": ["x"] * 100})
        right = DataFrame({"id": list(range(50, 150)), "val2": ["y"] * 100})
        result = JoinOperation.join(left, right, "id", "inner")
        assert result.shape[0] == 50  # Overlap from 50-99
