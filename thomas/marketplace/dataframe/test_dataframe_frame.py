"""Tests for DataFrame operations."""

import pytest
from _exceptions import ColumnNotFoundError, ShapeError
from _types import DType
from frame import DataFrame
from series import Series


class TestDataFrameConstruction:
    """Test DataFrame initialization."""

    def test_empty_dataframe(self) -> None:
        """Test creating empty DataFrame."""
        df = DataFrame()
        assert df.shape == (0, 0)
        assert df.columns == []

    def test_from_dict(self) -> None:
        """Test creating from dictionary."""
        data = {"a": [1, 2, 3], "b": [4, 5, 6]}
        df = DataFrame(data)
        assert df.shape == (3, 2)
        assert df.columns == ["a", "b"]

    def test_from_list_of_dicts(self) -> None:
        """Test creating from list of dicts."""
        data = [{"a": 1, "b": 4}, {"a": 2, "b": 5}, {"a": 3, "b": 6}]
        df = DataFrame(data)
        assert df.shape == (3, 2)
        assert df["a"][0] == 1

    def test_with_index(self) -> None:
        """Test with custom index."""
        data = {"a": [1, 2, 3]}
        index = ["x", "y", "z"]
        df = DataFrame(data, index=index)
        assert df.index == index

    def test_shape_mismatch(self) -> None:
        """Test shape mismatch detection."""
        data = {"a": [1, 2, 3], "b": [4, 5]}
        with pytest.raises(ShapeError):
            DataFrame(data)


class TestDataFrameColumnAccess:
    """Test column access and manipulation."""

    def test_getitem_single_column(self) -> None:
        """Test getting single column."""
        df = DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        col = df["a"]
        assert isinstance(col, Series)
        assert col[0] == 1

    def test_getitem_multiple_columns(self) -> None:
        """Test getting multiple columns."""
        df = DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
        sub_df = df[["a", "c"]]
        assert sub_df.shape == (3, 2)
        assert sub_df.columns == ["a", "c"]

    def test_setitem_new_column(self) -> None:
        """Test adding new column."""
        df = DataFrame({"a": [1, 2, 3]})
        df["b"] = [4, 5, 6]
        assert "b" in df.columns
        assert df["b"][0] == 4

    def test_setitem_series(self) -> None:
        """Test setting column from Series."""
        df = DataFrame({"a": [1, 2, 3]})
        s = Series([4, 5, 6], name="b")
        df["b"] = s
        assert df["b"][0] == 4

    def test_missing_column(self) -> None:
        """Test accessing non-existent column."""
        df = DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ColumnNotFoundError):
            _ = df["missing"]

    def test_add_column(self) -> None:
        """Test add_column method."""
        df = DataFrame({"a": [1, 2, 3]})
        df.add_column("b", [4, 5, 6])
        assert "b" in df.columns

    def test_drop_columns(self) -> None:
        """Test dropping columns."""
        df = DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})
        result = df.drop(["b"])
        assert "b" not in result.columns
        assert result.shape == (2, 2)

    def test_rename_columns(self) -> None:
        """Test renaming columns."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        result = df.rename({"a": "x", "b": "y"})
        assert "x" in result.columns
        assert "y" in result.columns


class TestDataFrameInfo:
    """Test informational methods."""

    def test_shape(self) -> None:
        """Test shape property."""
        df = DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        assert df.shape == (3, 2)

    def test_columns(self) -> None:
        """Test columns property."""
        df = DataFrame({"x": [1, 2], "y": [3, 4], "z": [5, 6]})
        assert df.columns == ["x", "y", "z"]

    def test_dtypes(self) -> None:
        """Test dtypes method."""
        df = DataFrame({"int_col": [1, 2], "float_col": [1.5, 2.5]})
        types = df.dtypes()
        assert types["int_col"] == DType.INT
        assert types["float_col"] == DType.FLOAT

    def test_info(self) -> None:
        """Test info method."""
        df = DataFrame({"a": [1, None, 3]})
        info = df.info()
        assert "a" in info
        assert "nulls" in info


class TestDataFrameSlicing:
    """Test head, tail, and sample."""

    def test_head(self) -> None:
        """Test head method."""
        df = DataFrame({"a": range(10)})
        result = df.head(3)
        assert result.shape == (3, 1)
        assert result["a"][0] == 0

    def test_tail(self) -> None:
        """Test tail method."""
        df = DataFrame({"a": range(10)})
        result = df.tail(3)
        assert result.shape == (3, 1)
        assert result["a"][0] == 7

    def test_sample(self) -> None:
        """Test sample method."""
        df = DataFrame({"a": range(100)})
        result = df.sample(10, seed=42)
        assert result.shape == (10, 1)


class TestDataFrameIteration:
    """Test iteration methods."""

    def test_iterrows(self) -> None:
        """Test iterrows."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        rows = list(df.iterrows())
        assert len(rows) == 2
        idx, row = rows[0]
        assert isinstance(row, dict)
        assert row["a"] == 1

    def test_itertuples(self) -> None:
        """Test itertuples."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        tuples = list(df.itertuples())
        assert len(tuples) == 2
        row = tuples[0]
        assert hasattr(row, "a")
        assert row.a == 1


class TestDataFrameCopy:
    """Test copy operations."""

    def test_copy(self) -> None:
        """Test shallow copy."""
        df = DataFrame({"a": [1, 2, 3]})
        copy_df = df.copy()
        copy_df["a"][0] = 999
        assert df["a"][0] == 1  # Original unchanged

    def test_deepcopy(self) -> None:
        """Test deep copy."""
        df = DataFrame({"a": [1, 2, 3]})
        copy_df = df.deepcopy()
        copy_df["a"][0] = 999
        assert df["a"][0] == 1


class TestDataFrameConversion:
    """Test conversion methods."""

    def test_to_dict_dict_orient(self) -> None:
        """Test to_dict with dict orient."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        result = df.to_dict("dict")
        assert result["a"] == [1, 2]
        assert result["b"] == [3, 4]

    def test_to_dict_records_orient(self) -> None:
        """Test to_dict with records orient."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        result = df.to_dict("records")
        assert "records" in result
        assert len(result["records"]) == 2

    def test_to_list(self) -> None:
        """Test to_list."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        result = df.to_list()
        assert len(result) == 2
        assert result[0] == [1, 3]

    def test_astype(self) -> None:
        """Test astype conversion."""
        df = DataFrame({"a": ["1", "2", "3"]})
        result = df.astype({"a": DType.INT})
        assert result["a"][0] == 1


class TestDataFrameDisplay:
    """Test string representation."""

    def test_repr(self) -> None:
        """Test __repr__ method."""
        df = DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        repr_str = repr(df)
        assert "a" in repr_str
        assert "b" in repr_str

    def test_empty_repr(self) -> None:
        """Test repr of empty DataFrame."""
        df = DataFrame()
        repr_str = repr(df)
        assert "Empty" in repr_str


class TestDataFrameStatistics:
    """Test statistical methods."""

    def test_describe(self) -> None:
        """Test describe method."""
        df = DataFrame({"a": [1, 2, 3, 4, 5]})
        result = df.describe()
        assert "count" in result.index
        assert "mean" in result.index
        assert "min" in result.index
        assert "max" in result.index


class TestDataFrameErrors:
    """Test error handling."""

    def test_invalid_data_type(self) -> None:
        """Test invalid data type."""
        with pytest.raises(TypeError):
            DataFrame("invalid")

    def test_shape_mismatch_setitem(self) -> None:
        """Test shape mismatch in setitem."""
        df = DataFrame({"a": [1, 2, 3]})
        with pytest.raises(ShapeError):
            df["b"] = [1, 2]  # Wrong length

    def test_invalid_orient(self) -> None:
        """Test invalid orient in to_dict."""
        df = DataFrame({"a": [1, 2]})
        with pytest.raises(ValueError):
            df.to_dict("invalid")
