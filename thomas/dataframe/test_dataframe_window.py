"""Tests for window/rolling operations."""

import pytest
from _types import DType
from frame import DataFrame
from series import Series
from window import WindowFunctions


class TestRollingMean:
    """Test rolling mean."""

    def test_rolling_mean_basic(self) -> None:
        """Test basic rolling mean."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.rolling(s, 2, "mean")
        assert result[0] == 1
        assert result[1] == 1.5
        assert result[2] == 2.5

    def test_rolling_mean_window_size_3(self) -> None:
        """Test rolling mean with window size 3."""
        s = Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = WindowFunctions.rolling(s, 3, "mean")
        assert result[0] == 1.0
        assert result[2] == 2.0  # (1+2+3)/3
        assert result[3] == 3.0  # (2+3+4)/3


class TestRollingSum:
    """Test rolling sum."""

    def test_rolling_sum(self) -> None:
        """Test rolling sum."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.rolling(s, 2, "sum")
        assert result[0] == 1
        assert result[1] == 3
        assert result[2] == 5


class TestRollingStd:
    """Test rolling standard deviation."""

    def test_rolling_std(self) -> None:
        """Test rolling std."""
        s = Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = WindowFunctions.rolling(s, 2, "std")
        assert result[1] is not None


class TestRollingMinMax:
    """Test rolling min/max."""

    def test_rolling_min(self) -> None:
        """Test rolling min."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.rolling(s, 2, "min")
        assert result[1] == 1  # min(3,1)
        assert result[2] == 1  # min(1,4)

    def test_rolling_max(self) -> None:
        """Test rolling max."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.rolling(s, 2, "max")
        assert result[1] == 3  # max(3,1)
        assert result[2] == 4  # max(1,4)


class TestRollingWithNulls:
    """Test rolling with null values."""

    def test_rolling_with_nulls(self) -> None:
        """Test rolling ignores nulls."""
        s = Series([1, None, 3, 4, 5])
        result = WindowFunctions.rolling(s, 2, "mean")
        assert result[0] == 1
        assert result[2] == 3.0


class TestExpandingMean:
    """Test expanding mean."""

    def test_expanding_mean(self) -> None:
        """Test expanding mean."""
        s = Series([1.0, 2.0, 3.0, 4.0])
        result = WindowFunctions.expanding(s, "mean")
        assert result[0] == 1.0
        assert result[1] == 1.5
        assert result[2] == 2.0
        assert result[3] == 2.5


class TestExpandingSum:
    """Test expanding sum."""

    def test_expanding_sum(self) -> None:
        """Test expanding sum."""
        s = Series([1, 2, 3, 4])
        result = WindowFunctions.expanding(s, "sum")
        assert result[0] == 1
        assert result[1] == 3
        assert result[2] == 6
        assert result[3] == 10


class TestEWMA:
    """Test exponentially weighted moving average."""

    def test_ewma_basic(self) -> None:
        """Test basic EWMA."""
        s = Series([1.0, 2.0, 3.0, 4.0])
        result = WindowFunctions.ewma(s, span=2)
        assert result[0] is not None
        assert len(result) == 4


class TestRank:
    """Test ranking."""

    def test_rank_average(self) -> None:
        """Test rank with average method."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.rank(s, "average")
        assert result.dtype == DType.FLOAT

    def test_rank_first(self) -> None:
        """Test rank with first method."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.rank(s, "first")
        assert result[0] is not None

    def test_rank_with_ties(self) -> None:
        """Test rank handles ties."""
        s = Series([1, 1, 2, 2, 3])
        result = WindowFunctions.rank(s, "average")
        assert result[0] is not None
        assert result[1] is not None


class TestShift:
    """Test shift operation."""

    def test_shift_positive(self) -> None:
        """Test shift forward."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.shift(s, 1)
        assert result[0] is None
        assert result[1] == 1
        assert result[2] == 2

    def test_shift_negative(self) -> None:
        """Test shift backward."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.shift(s, -1)
        assert result[0] == 2
        assert result[3] == 5
        assert result[4] is None


class TestLagLead:
    """Test lag and lead."""

    def test_lag(self) -> None:
        """Test lag (previous values)."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.lag(s, 1)
        assert result[0] is None
        assert result[1] == 1

    def test_lead(self) -> None:
        """Test lead (future values)."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.lead(s, 1)
        assert result[0] == 2
        assert result[4] is None


class TestCumulative:
    """Test cumulative operations."""

    def test_cumsum(self) -> None:
        """Test cumulative sum."""
        s = Series([1, 2, 3, 4, 5])
        result = WindowFunctions.cumsum(s)
        assert result[0] == 1
        assert result[1] == 3
        assert result[2] == 6
        assert result[4] == 15

    def test_cumprod(self) -> None:
        """Test cumulative product."""
        s = Series([1, 2, 3, 4])
        result = WindowFunctions.cumprod(s)
        assert result[0] == 1
        assert result[1] == 2
        assert result[2] == 6
        assert result[3] == 24

    def test_cummax(self) -> None:
        """Test cumulative max."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.cummax(s)
        assert result[0] == 3
        assert result[1] == 3
        assert result[2] == 4
        assert result[4] == 5

    def test_cummin(self) -> None:
        """Test cumulative min."""
        s = Series([3, 1, 4, 1, 5])
        result = WindowFunctions.cummin(s)
        assert result[0] == 3
        assert result[1] == 1
        assert result[2] == 1
        assert result[4] == 1


class TestCumulativeWithNulls:
    """Test cumulative with nulls."""

    def test_cumsum_with_nulls(self) -> None:
        """Test cumsum handles nulls."""
        s = Series([1, None, 3, 4])
        result = WindowFunctions.cumsum(s)
        assert result[0] == 1
        assert result[1] is None
        assert result[2] == 4  # 1+3

    def test_cummax_with_nulls(self) -> None:
        """Test cummax handles nulls."""
        s = Series([1, None, 3])
        result = WindowFunctions.cummax(s)
        assert result[1] == 1


class TestRollingApply:
    """Test rolling apply to DataFrame."""

    def test_rolling_apply_dataframe(self) -> None:
        """Test rolling apply on DataFrame."""
        df = DataFrame({"a": [1, 2, 3, 4, 5]})
        result = WindowFunctions.rolling_apply(df, 2, lambda g: {"a": g["a"].sum()})
        assert result.shape == df.shape


class TestWindowErrors:
    """Test error handling."""

    def test_invalid_window_size(self) -> None:
        """Test invalid window size."""
        s = Series([1, 2, 3])
        with pytest.raises(ValueError):
            WindowFunctions.rolling(s, 0)

    def test_invalid_rank_method(self) -> None:
        """Test invalid rank method."""
        s = Series([1, 2, 3])
        with pytest.raises(ValueError):
            WindowFunctions.rank(s, "invalid")


class TestWindowEdgeCases:
    """Test edge cases."""

    def test_rolling_single_element(self) -> None:
        """Test rolling on single element."""
        s = Series([1])
        result = WindowFunctions.rolling(s, 1, "mean")
        assert result[0] == 1

    def test_expanding_empty(self) -> None:
        """Test expanding on empty."""
        s = Series([])
        result = WindowFunctions.expanding(s, "mean")
        assert len(result) == 0

    def test_shift_larger_than_length(self) -> None:
        """Test shift larger than Series length."""
        s = Series([1, 2, 3])
        result = WindowFunctions.shift(s, 10)
        assert result[0] is None

    def test_rank_all_same_value(self) -> None:
        """Test rank when all values are the same."""
        s = Series([5, 5, 5, 5])
        result = WindowFunctions.rank(s, "average")
        assert all(r == 2.5 for r in result if r is not None)
