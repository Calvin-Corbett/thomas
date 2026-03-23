"""GroupBy operations for DataFrames."""

from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any

try:
    from ._exceptions import ColumnNotFoundError, DataFrameError
    from ._types import AggFunc, DType
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from _exceptions import ColumnNotFoundError, DataFrameError
    from frame import DataFrame
    from series import Series


class GroupBy:
    """GroupBy object for grouped operations.

    Attributes:
        _df: The underlying DataFrame
        _groupby_cols: Column names to group by
        _groups: Cached group mapping
    """

    def __init__(self, df: DataFrame, by: str | list[str]) -> None:
        """Initialize GroupBy.

        Args:
            df: The DataFrame to group
            by: Column name(s) to group by
        """
        self._df = df
        self._groupby_cols = [by] if isinstance(by, str) else by
        self._groups: dict[Any, list[int]] = {}
        self._compute_groups()

    def _compute_groups(self) -> None:
        """Compute group indices."""
        for col in self._groupby_cols:
            if col not in self._df.columns:
                raise ColumnNotFoundError(col, self._df.columns)

        for idx, _ in self._df.iterrows():
            row_idx = self._df._index.index(idx)
            if len(self._groupby_cols) == 1:
                key = self._df[self._groupby_cols[0]][row_idx]
            else:
                key = tuple(self._df[col][row_idx] for col in self._groupby_cols)

            if key not in self._groups:
                self._groups[key] = []
            self._groups[key].append(row_idx)

    def count(self) -> DataFrame:
        """Count rows in each group."""
        return self._aggregate_single("count", lambda s: s.count())

    def sum(self) -> DataFrame:
        """Sum values in each group."""
        return self._aggregate_single("sum", lambda s: s.sum())

    def mean(self) -> DataFrame:
        """Mean of values in each group."""
        return self._aggregate_single("mean", lambda s: s.mean())

    def min(self) -> DataFrame:
        """Min value in each group."""
        return self._aggregate_single("min", lambda s: s.min())

    def max(self) -> DataFrame:
        """Max value in each group."""
        return self._aggregate_single("max", lambda s: s.max())

    def std(self) -> DataFrame:
        """Standard deviation in each group."""
        return self._aggregate_single("std", lambda s: s.std())

    def var(self) -> DataFrame:
        """Variance in each group."""
        return self._aggregate_single("var", lambda s: self._variance(s))

    def first(self) -> DataFrame:
        """First value in each group."""
        return self._aggregate_single("first", lambda s: s[0] if len(s) > 0 else None)

    def last(self) -> DataFrame:
        """Last value in each group."""
        return self._aggregate_single("last", lambda s: s[-1] if len(s) > 0 else None)

    def _variance(self, series: Series) -> float | None:
        """Compute variance."""
        mean = series.mean()
        if mean is None:
            return None
        count = series.count()
        if count <= 1:
            return None
        sum_sq_diff = 0.0
        for val, is_null in zip(series._data, series._null_mask):
            if not is_null:
                sum_sq_diff += (val - mean) ** 2
        return sum_sq_diff / (count - 1)

    def _aggregate_single(self, agg_name: str, agg_func: Callable[[Series], Any]) -> DataFrame:
        """Aggregate each column in each group."""
        result_data: dict[str, list[Any]] = defaultdict(list)
        group_keys = []

        for key in sorted(self._groups.keys(), key=str):
            indices = self._groups[key]
            group_keys.append(key)

            for col_name, series in self._df._columns.items():
                if col_name not in self._groupby_cols:
                    group_series = Series([series[i] for i in indices], name=col_name)
                    result_data[col_name].append(agg_func(group_series))

        # Add groupby columns
        for i, key in enumerate(group_keys):
            if len(self._groupby_cols) == 1:
                result_data[self._groupby_cols[0]].insert(i, key)
            else:
                for j, col in enumerate(self._groupby_cols):
                    result_data[col].insert(j, key[j])

        return DataFrame(result_data)

    def aggregate(self, func: str | dict[str, str]) -> DataFrame:
        """Aggregate using function(s).

        Args:
            func: Function name or dict of col->func mappings

        Returns:
            Aggregated DataFrame
        """
        if isinstance(func, str):
            if func == "sum":
                return self.sum()
            elif func == "mean":
                return self.mean()
            elif func == "count":
                return self.count()
            elif func == "min":
                return self.min()
            elif func == "max":
                return self.max()
            elif func == "std":
                return self.std()
            else:
                raise DataFrameError(f"Unknown aggregation: {func}")
        elif isinstance(func, dict):
            result_data: dict[str, list[Any]] = defaultdict(list)
            group_keys = []

            for key in sorted(self._groups.keys(), key=str):
                indices = self._groups[key]
                group_keys.append(key)

                for col_name, agg_func in func.items():
                    if col_name not in self._df.columns:
                        raise ColumnNotFoundError(col_name, self._df.columns)

                    group_series = Series([self._df[col_name][i] for i in indices])
                    if agg_func == "sum":
                        result = group_series.sum()
                    elif agg_func == "mean":
                        result = group_series.mean()
                    elif agg_func == "count":
                        result = group_series.count()
                    elif agg_func == "min":
                        result = group_series.min()
                    elif agg_func == "max":
                        result = group_series.max()
                    elif agg_func == "std":
                        result = group_series.std()
                    else:
                        raise DataFrameError(f"Unknown aggregation: {agg_func}")

                    result_data[col_name].append(result)

            for i, key in enumerate(group_keys):
                if len(self._groupby_cols) == 1:
                    result_data[self._groupby_cols[0]].insert(i, key)
                else:
                    for j, col in enumerate(self._groupby_cols):
                        result_data[col].insert(j, key[j])

            return DataFrame(result_data)
        else:
            raise TypeError(f"Invalid func type: {type(func)}")

    def transform(self, func: Callable[[Series], Series]) -> DataFrame:
        """Transform each group."""
        result_data: dict[str, list[Any]] = defaultdict(list)
        index_mapping = defaultdict(list)

        for key in self._groups.keys():
            indices = self._groups[key]

            for col_name, series in self._df._columns.items():
                if col_name not in self._groupby_cols:
                    group_series = Series([series[i] for i in indices])
                    transformed = func(group_series)
                    for i, idx in enumerate(indices):
                        result_data[col_name].append(transformed[i])
                        if col_name == list(self._df._columns.keys())[0]:
                            index_mapping[idx].append(None)

        # Reconstruct in original order
        final_data = defaultdict(list)
        for orig_idx in range(len(self._df._index)):
            for col_name in result_data:
                if col_name not in self._groupby_cols:
                    final_data[col_name].append(None)

        return DataFrame(dict(final_data), index=self._df._index)

    def filter(self, func: Callable[["DataFrame"], bool]) -> DataFrame:
        """Filter groups based on a function."""
        keep_indices = []

        for key in self._groups.keys():
            indices = self._groups[key]
            group_data = {}
            for col_name in self._df.columns:
                group_data[col_name] = [self._df[col_name][i] for i in indices]
            group_df = DataFrame(group_data)

            if func(group_df):
                keep_indices.extend(indices)

        keep_indices.sort()
        new_data = {}
        for col_name in self._df.columns:
            new_data[col_name] = [self._df[col_name][i] for i in keep_indices]

        return DataFrame(new_data, index=[self._df._index[i] for i in keep_indices])

    def __iter__(self) -> Iterator[tuple[Any, DataFrame]]:
        """Iterate over groups."""
        for key in sorted(self._groups.keys(), key=str):
            indices = self._groups[key]
            group_data = {}
            for col_name in self._df.columns:
                group_data[col_name] = [self._df[col_name][i] for i in indices]
            group_df = DataFrame(group_data, index=[self._df._index[i] for i in indices])
            yield key, group_df

    def size(self) -> dict[Any, int]:
        """Get size of each group."""
        return {key: len(indices) for key, indices in self._groups.items()}

    def get_group(self, name: Any) -> DataFrame:
        """Get a specific group by key."""
        if name not in self._groups:
            raise DataFrameError(f"Group {name} not found")

        indices = self._groups[name]
        group_data = {}
        for col_name in self._df.columns:
            group_data[col_name] = [self._df[col_name][i] for i in indices]

        return DataFrame(group_data, index=[self._df._index[i] for i in indices])
