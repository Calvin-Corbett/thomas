"""Tests for Series operations."""

import pytest
from _exceptions import DataFrameError, ShapeError
from _types import DType
from series import Series


class TestSeriesConstruction:
    """Test Series initialization."""

    def test_empty_series(self) -> None:
        """Test creating empty Series."""
        s = Series()
        assert len(s) == 0
        assert s.dtype == DType.NULL

    def test_series_from_list(self) -> None:
        """Test creating Series from list."""
        s = Series([1, 2, 3], name="test")
        assert len(s) == 3
        assert s.name == "test"
        assert s.dtype == DType.INT

    def test_series_with_explicit_dtype(self) -> None:
        """Test Series with explicit dtype."""
        s = Series(["1", "2", "3"], dtype=DType.FLOAT)
        assert s.dtype == DType.FLOAT
        assert s[0] == 1.0

    def test_series_with_nulls(self) -> None:
        """Test Series with None values."""
        s = Series([1, None, 3])
        assert len(s) == 3
        assert s[1] is None
        assert s[0] == 1

    def test_series_type_inference(self) -> None:
        """Test automatic type inference."""
        s_int = Series([1, 2, 3])
        assert s_int.dtype == DType.INT

        s_float = Series([1.0, 2.5, 3.0])
        assert s_float.dtype == DType.FLOAT

        s_str = Series(["a", "b", "c"])
        assert s_str.dtype == DType.STRING

        s_bool = Series([True, False, True])
        assert s_bool.dtype == DType.BOOL


class TestSeriesIndexing:
    """Test Series element access and slicing."""

    def test_getitem_single(self) -> None:
        """Test single element access."""
        s = Series([10, 20, 30])
        assert s[0] == 10
        assert s[1] == 20
        assert s[-1] == 30

    def test_getitem_slice(self) -> None:
        """Test slicing."""
        s = Series([10, 20, 30, 40, 50])
        sliced = s[1:4]
        assert len(sliced) == 3
        assert sliced[0] == 20
        assert sliced[1] == 30

    def test_setitem(self) -> None:
        """Test setting elements."""
        s = Series([1, 2, 3])
        s[1] = 99
        assert s[1] == 99

    def test_out_of_bounds(self) -> None:
        """Test out of bounds access."""
        s = Series([1, 2, 3])
        with pytest.raises(IndexError):
            _ = s[10]


class TestSeriesArithmetic:
    """Test arithmetic operations."""

    def test_add_scalar(self) -> None:
        """Test scalar addition."""
        s = Series([1, 2, 3])
        result = s + 5
        assert result[0] == 6
        assert result[1] == 7

    def test_add_series(self) -> None:
        """Test Series addition."""
        s1 = Series([1, 2, 3])
        s2 = Series([10, 20, 30])
        result = s1 + s2
        assert result[0] == 11
        assert result[1] == 22

    def test_subtract(self) -> None:
        """Test subtraction."""
        s = Series([10, 20, 30])
        result = s - 5
        assert result[0] == 5
        assert result[2] == 25

    def test_multiply(self) -> None:
        """Test multiplication."""
        s = Series([2, 3, 4])
        result = s * 3
        assert result[0] == 6
        assert result[2] == 12

    def test_divide(self) -> None:
        """Test division."""
        s = Series([10.0, 20.0, 30.0])
        result = s / 2
        assert result[0] == 5.0
        assert result[1] == 10.0

    def test_arithmetic_with_nulls(self) -> None:
        """Test arithmetic with nulls."""
        s1 = Series([1, None, 3])
        s2 = Series([10, 20, 30])
        result = s1 + s2
        assert result[0] == 11
        assert result[1] is None
        assert result[2] == 33


class TestSeriesComparison:
    """Test comparison operations."""

    def test_equality(self) -> None:
        """Test equality operator."""
        s = Series([1, 2, 3])
        result = s == 2
        assert result[0] is False
        assert result[1] is True
        assert result.dtype == DType.BOOL

    def test_inequality(self) -> None:
        """Test inequality operator."""
        s = Series([1, 2, 3])
        result = s != 2
        assert result[0] is True
        assert result[1] is False

    def test_less_than(self) -> None:
        """Test less than."""
        s = Series([1, 2, 3])
        result = s < 2
        assert result[0] is True
        assert result[1] is False

    def test_greater_than(self) -> None:
        """Test greater than."""
        s = Series([1, 2, 3])
        result = s > 2
        assert result[0] is False
        assert result[2] is True


class TestSeriesStringMethods:
    """Test string operations."""

    def test_lower(self) -> None:
        """Test lowercase conversion."""
        s = Series(["HELLO", "WORLD"])
        result = s.lower()
        assert result[0] == "hello"
        assert result[1] == "world"

    def test_upper(self) -> None:
        """Test uppercase conversion."""
        s = Series(["hello", "world"])
        result = s.upper()
        assert result[0] == "HELLO"
        assert result[1] == "WORLD"

    def test_contains(self) -> None:
        """Test string contains."""
        s = Series(["hello", "world", "help"])
        result = s.contains("el")
        assert result[0] is True
        assert result[1] is False
        assert result[2] is True

    def test_replace(self) -> None:
        """Test string replace."""
        s = Series(["hello", "world"])
        result = s.replace("l", "L")
        assert result[0] == "heLLo"
        assert result[1] == "worLd"

    def test_split(self) -> None:
        """Test string split."""
        s = Series(["a,b,c", "x,y,z"])
        result = s.split(",")
        assert result[0] == ["a", "b", "c"]
        assert result[1] == ["x", "y", "z"]


class TestSeriesNullHandling:
    """Test null value operations."""

    def test_isna(self) -> None:
        """Test isna method."""
        s = Series([1, None, 3])
        result = s.isna()
        assert result[0] is False
        assert result[1] is True
        assert result[2] is False

    def test_fillna(self) -> None:
        """Test fillna method."""
        s = Series([1, None, 3])
        result = s.fillna(0)
        assert result[1] == 0
        assert len(result) == 3

    def test_dropna(self) -> None:
        """Test dropna method."""
        s = Series([1, None, 3])
        result = s.dropna()
        assert len(result) == 2
        assert result[0] == 1
        assert result[1] == 3


class TestSeriesAggregations:
    """Test aggregation functions."""

    def test_sum(self) -> None:
        """Test sum aggregation."""
        s = Series([1, 2, 3])
        assert s.sum() == 6

    def test_sum_with_nulls(self) -> None:
        """Test sum with nulls."""
        s = Series([1, None, 3])
        assert s.sum() == 4

    def test_mean(self) -> None:
        """Test mean aggregation."""
        s = Series([1.0, 2.0, 3.0])
        assert s.mean() == 2.0

    def test_std(self) -> None:
        """Test standard deviation."""
        s = Series([1.0, 2.0, 3.0])
        std = s.std()
        assert std is not None
        assert abs(std - 1.0) < 0.01

    def test_min(self) -> None:
        """Test minimum value."""
        s = Series([3, 1, 2])
        assert s.min() == 1

    def test_max(self) -> None:
        """Test maximum value."""
        s = Series([3, 1, 2])
        assert s.max() == 3

    def test_count(self) -> None:
        """Test count (non-null values)."""
        s = Series([1, None, 3, None, 5])
        assert s.count() == 3

    def test_nunique(self) -> None:
        """Test count of unique values."""
        s = Series([1, 2, 1, 3, 2])
        assert s.nunique() == 3

    def test_value_counts(self) -> None:
        """Test value frequency."""
        s = Series([1, 2, 1, 3, 2, 2])
        counts = s.value_counts()
        assert counts[1] == 2
        assert counts[2] == 3
        assert counts[3] == 1


class TestSeriesApply:
    """Test apply and map operations."""

    def test_apply(self) -> None:
        """Test apply function."""
        s = Series([1, 2, 3])
        result = s.apply(lambda x: x**2)
        assert result[0] == 1
        assert result[1] == 4
        assert result[2] == 9

    def test_apply_with_nulls(self) -> None:
        """Test apply with nulls."""
        s = Series([1, None, 3])
        result = s.apply(lambda x: x * 2)
        assert result[0] == 2
        assert result[1] is None

    def test_map(self) -> None:
        """Test map with dictionary."""
        s = Series(["a", "b", "c"])
        mapping = {"a": 1, "b": 2, "c": 3}
        result = s.map(mapping)
        assert result[0] == 1
        assert result[1] == 2

    def test_map_missing_key(self) -> None:
        """Test map with missing key."""
        s = Series(["a", "b", "x"])
        mapping = {"a": 1, "b": 2}
        result = s.map(mapping)
        assert result[0] == 1
        assert result[2] is None


class TestSeriesShape:
    """Test Series shape and properties."""

    def test_len(self) -> None:
        """Test len()."""
        s = Series([1, 2, 3, 4, 5])
        assert len(s) == 5

    def test_shape(self) -> None:
        """Test shape property."""
        s = Series([1, 2, 3])
        assert s.shape == (3,)

    def test_dtype(self) -> None:
        """Test dtype property."""
        s_int = Series([1, 2, 3])
        assert s_int.dtype == DType.INT

        s_str = Series(["a", "b"])
        assert s_str.dtype == DType.STRING


class TestSeriesErrors:
    """Test error handling."""

    def test_shape_mismatch_construction(self) -> None:
        """Test shape mismatch in construction."""
        with pytest.raises(ShapeError):
            Series(not_a_list=True)

    def test_string_method_on_numeric(self) -> None:
        """Test string method on non-string."""
        s = Series([1, 2, 3])
        with pytest.raises(DataFrameError):
            s.lower()
