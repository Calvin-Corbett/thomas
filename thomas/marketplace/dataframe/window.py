"""Window functions for DataFrames."""

from collections.abc import Callable

try:
    from ._exceptions import DataFrameError
    from ._types import DType
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from _types import DType
    from frame import DataFrame
    from series import Series


class WindowFunctions:
    """Window/rolling operations."""

    @staticmethod
    def rolling(series: Series, window_size: int, func: str | Callable[[Series], float] = "mean") -> Series:
        """Apply a rolling window function.

        Args:
            series: The Series to apply to
            window_size: Size of the rolling window
            func: Function to apply ('mean', 'sum', 'std', 'min', 'max') or callable

        Returns:
            Series with rolling result
        """
        if window_size < 1:
            raise ValueError("window_size must be >= 1")

        result = []
        for i in range(len(series)):
            start = max(0, i - window_size + 1)
            window_data = [series[j] for j in range(start, i + 1) if series[j] is not None]

            if not window_data:
                result.append(None)
            else:
                window_series = Series(window_data)
                if callable(func):
                    result.append(func(window_series))
                elif func == "mean":
                    result.append(window_series.mean())
                elif func == "sum":
                    result.append(window_series.sum())
                elif func == "std":
                    result.append(window_series.std())
                elif func == "min":
                    result.append(window_series.min())
                elif func == "max":
                    result.append(window_series.max())
                else:
                    raise ValueError(f"Unknown func: {func}")

        return Series(result, name=series.name)

    @staticmethod
    def expanding(series: Series, func: str | Callable[[Series], float] = "mean") -> Series:
        """Apply an expanding window function.

        Args:
            series: The Series to apply to
            func: Function to apply

        Returns:
            Series with expanding result
        """
        result = []
        for i in range(len(series)):
            window_data = [series[j] for j in range(i + 1) if series[j] is not None]

            if not window_data:
                result.append(None)
            else:
                window_series = Series(window_data)
                if callable(func):
                    result.append(func(window_series))
                elif func == "mean":
                    result.append(window_series.mean())
                elif func == "sum":
                    result.append(window_series.sum())
                elif func == "std":
                    result.append(window_series.std())
                elif func == "min":
                    result.append(window_series.min())
                elif func == "max":
                    result.append(window_series.max())
                else:
                    raise ValueError(f"Unknown func: {func}")

        return Series(result, name=series.name)

    @staticmethod
    def ewma(series: Series, span: int = 10, adjust: bool = True) -> Series:
        """Exponentially weighted moving average.

        Args:
            series: The Series to apply to
            span: Span parameter
            adjust: Whether to adjust by weight sum

        Returns:
            Series with EWMA result
        """
        if span < 1:
            raise ValueError("span must be >= 1")

        alpha = 2.0 / (span + 1)
        result = []
        weights_sum = 0.0
        weighted_sum = 0.0

        for i in range(len(series)):
            val = series[i]
            if val is None:
                result.append(None)
            else:
                weight = (1 - alpha) ** (i - i)  # Current weight = 1
                weighted_sum += val * weight
                weights_sum += weight

                # Accumulate with decay
                if i > 0 and result[i - 1] is not None:
                    weighted_sum = weighted_sum * (1 - alpha) + val
                    weights_sum = weights_sum * (1 - alpha) + 1

                if adjust:
                    result.append(weighted_sum / weights_sum if weights_sum > 0 else None)
                else:
                    result.append(weighted_sum)

        return Series(result, name=series.name)

    @staticmethod
    def rank(series: Series, method: str = "average") -> Series:
        """Rank values in Series.

        Args:
            series: The Series to rank
            method: 'average', 'first', 'dense', 'min', 'max'

        Returns:
            Series with ranks
        """
        # Get non-null values with indices
        indexed_values = [(i, series[i]) for i in range(len(series)) if series[i] is not None]

        # Sort by value
        indexed_values.sort(key=lambda x: x[1])

        # Assign ranks
        ranks = [None] * len(series)
        i = 0
        while i < len(indexed_values):
            j = i
            while j < len(indexed_values) and indexed_values[j][1] == indexed_values[i][1]:
                j += 1

            # Handle ties
            if method == "average":
                rank_val = (i + j) / 2.0 + 1
            elif method == "first" or method == "dense" or method == "min":
                rank_val = i + 1
            elif method == "max":
                rank_val = j
            else:
                raise ValueError(f"Unknown method: {method}")

            for k in range(i, j):
                ranks[indexed_values[k][0]] = rank_val

            i = j

        return Series(ranks, name=series.name, dtype=DType.FLOAT)

    @staticmethod
    def shift(series: Series, periods: int = 1) -> Series:
        """Shift values by periods.

        Args:
            series: The Series to shift
            periods: Number of periods to shift (positive = forward)

        Returns:
            Shifted Series
        """
        result = [None] * len(series)
        if periods > 0:
            for i in range(len(series) - periods):
                result[i + periods] = series[i]
        else:
            for i in range(-periods, len(series)):
                result[i + periods] = series[i]
        return Series(result, name=series.name, dtype=series.dtype)

    @staticmethod
    def lag(series: Series, periods: int = 1) -> Series:
        """Lag values (previous values).

        Args:
            series: The Series
            periods: Number of periods

        Returns:
            Lagged Series
        """
        return WindowFunctions.shift(series, periods)

    @staticmethod
    def lead(series: Series, periods: int = 1) -> Series:
        """Lead values (future values).

        Args:
            series: The Series
            periods: Number of periods

        Returns:
            Lead Series
        """
        return WindowFunctions.shift(series, -periods)

    @staticmethod
    def cumsum(series: Series) -> Series:
        """Cumulative sum."""
        result = []
        total = 0
        for val in series:
            if val is None:
                result.append(None)
            else:
                total += val
                result.append(total)
        return Series(result, name=series.name)

    @staticmethod
    def cumprod(series: Series) -> Series:
        """Cumulative product."""
        result = []
        prod = 1
        for val in series:
            if val is None:
                result.append(None)
            else:
                prod *= val
                result.append(prod)
        return Series(result, name=series.name)

    @staticmethod
    def cummax(series: Series) -> Series:
        """Cumulative maximum."""
        result = []
        max_val = None
        for val in series:
            if val is None:
                result.append(max_val)
            else:
                if max_val is None:
                    max_val = val
                else:
                    max_val = max(max_val, val)
                result.append(max_val)
        return Series(result, name=series.name)

    @staticmethod
    def cummin(series: Series) -> Series:
        """Cumulative minimum."""
        result = []
        min_val = None
        for val in series:
            if val is None:
                result.append(min_val)
            else:
                if min_val is None:
                    min_val = val
                else:
                    min_val = min(min_val, val)
                result.append(min_val)
        return Series(result, name=series.name)

    @staticmethod
    def rolling_apply(
        df: DataFrame, window_size: int, func: Callable[[DataFrame], float], min_periods: int = 1
    ) -> DataFrame:
        """Apply rolling window function to entire DataFrame.

        Args:
            df: DataFrame
            window_size: Window size
            func: Function to apply to each window
            min_periods: Minimum rows in window

        Returns:
            DataFrame with results
        """
        result_data = {}
        for col_name in df.columns:
            result_data[col_name] = []

        for i in range(len(df._index)):
            start = max(0, i - window_size + 1)
            window_indices = list(range(start, i + 1))

            if len(window_indices) < min_periods:
                for col_name in df.columns:
                    result_data[col_name].append(None)
            else:
                window_data = {}
                for col_name in df.columns:
                    window_data[col_name] = [df[col_name][j] for j in window_indices]

                window_df = DataFrame(window_data)
                window_result = func(window_df)

                for col_name in df.columns:
                    if col_name in window_result:
                        result_data[col_name].append(window_result[col_name])
                    else:
                        result_data[col_name].append(None)

        return DataFrame(result_data, index=df._index)
