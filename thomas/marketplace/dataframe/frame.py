"""DataFrame class: two-dimensional tabular data structure."""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any, Union

try:
    from ._exceptions import ColumnNotFoundError, DataFrameError, ShapeError
    from ._types import ColumnInfo, DType
    from .series import Series
except ImportError:
    from _exceptions import ColumnNotFoundError, ShapeError
    from _types import DType
    from series import Series


class DataFrame:
    """A two-dimensional labeled data structure (table).

    Columns are stored as Series objects internally.

    Attributes:
        _columns: Dictionary mapping column names to Series
        _index: Optional index labels
    """

    def __init__(
        self,
        data: dict[str, list[Any]] | list[dict[str, Any]] | None = None,
        index: list[Any] | None = None,
        columns: list[str] | None = None,
    ) -> None:
        """Initialize a DataFrame.

        Args:
            data: Dictionary of column_name -> list, or list of dicts
            index: Optional index labels
            columns: Column names (for list of dicts data)

        Raises:
            ShapeError: If data shapes are inconsistent
        """
        self._columns: dict[str, Series] = {}
        self._index: list[Any] = []

        if data is None:
            data = {}

        if isinstance(data, dict):
            # Dictionary of column_name -> list
            if not data:
                self._index = index or []
            else:
                length = len(next(iter(data.values())))
                for col_name, col_data in data.items():
                    if len(col_data) != length:
                        raise ShapeError((length,), (len(col_data),))
                    self._columns[col_name] = Series(col_data, name=col_name)
                self._index = index or list(range(length))

        elif isinstance(data, list):
            # List of dicts
            if data:
                col_names = columns or sorted(set(k for row in data for k in row.keys()))
                length = len(data)

                for col_name in col_names:
                    col_data = [row.get(col_name, None) for row in data]
                    self._columns[col_name] = Series(col_data, name=col_name)

                self._index = index or list(range(length))
            else:
                self._columns = {}
                self._index = index or []
        else:
            raise TypeError(f"Invalid data type: {type(data)}")

    @property
    def shape(self) -> tuple[int, int]:
        """Get the shape (rows, columns)."""
        n_rows = len(self._index)
        n_cols = len(self._columns)
        return (n_rows, n_cols)

    @property
    def columns(self) -> list[str]:
        """Get column names."""
        return list(self._columns.keys())

    @property
    def index(self) -> list[Any]:
        """Get index."""
        return self._index

    def dtypes(self) -> dict[str, DType]:
        """Get data types of all columns."""
        return {name: series.dtype for name, series in self._columns.items()}

    def info(self) -> str:
        """Get information about the DataFrame."""
        lines = [f"DataFrame: {self.shape[0]} rows, {self.shape[1]} columns", ""]
        for col_name, series in self._columns.items():
            null_count = sum(series._null_mask)
            lines.append(f"{col_name:20} {series.dtype!s:10} {null_count} nulls")
        return "\n".join(lines)

    def describe(self) -> "DataFrame":
        """Get statistical description of numeric columns."""
        descriptions: dict[str, list[Any]] = {"count": [], "mean": [], "std": [], "min": [], "max": []}
        col_names = []

        for col_name, series in self._columns.items():
            if series.dtype in (DType.INT, DType.FLOAT):
                col_names.append(col_name)
                descriptions["count"].append(series.count())
                descriptions["mean"].append(series.mean())
                descriptions["std"].append(series.std())
                descriptions["min"].append(series.min())
                descriptions["max"].append(series.max())

        data = {k: v for k, v in descriptions.items()}
        df = DataFrame(data)
        df._index = ["count", "mean", "std", "min", "max"]
        return df

    def head(self, n: int = 5) -> "DataFrame":
        """Return first n rows."""
        n = min(n, len(self._index))
        new_data = {}
        for col_name, series in self._columns.items():
            new_data[col_name] = [series[i] for i in range(n)]
        return DataFrame(new_data, index=self._index[:n])

    def tail(self, n: int = 5) -> "DataFrame":
        """Return last n rows."""
        n = min(n, len(self._index))
        start = len(self._index) - n
        new_data = {}
        for col_name, series in self._columns.items():
            new_data[col_name] = [series[i] for i in range(start, len(self._index))]
        return DataFrame(new_data, index=self._index[start:])

    def sample(self, n: int = 5, seed: int | None = None) -> "DataFrame":
        """Return random sample of rows."""
        import random

        if seed is not None:
            random.seed(seed)
        indices = random.sample(range(len(self._index)), min(n, len(self._index)))
        indices.sort()
        new_data = {}
        for col_name, series in self._columns.items():
            new_data[col_name] = [series[i] for i in indices]
        return DataFrame(new_data, index=[self._index[i] for i in indices])

    def __getitem__(self, key: str | list[str]) -> Union[Series, "DataFrame"]:
        """Get column(s) by name."""
        if isinstance(key, str):
            if key not in self._columns:
                raise ColumnNotFoundError(key, self.columns)
            return self._columns[key]
        elif isinstance(key, list):
            new_data = {}
            for col_name in key:
                if col_name not in self._columns:
                    raise ColumnNotFoundError(col_name, self.columns)
                new_data[col_name] = [self._columns[col_name][i] for i in range(len(self._index))]
            return DataFrame(new_data, index=self._index)
        raise TypeError(f"Invalid key type: {type(key)}")

    def __setitem__(self, key: str, value: Series | list[Any]) -> None:
        """Set a column."""
        if isinstance(value, Series):
            if len(value) != len(self._index):
                raise ShapeError((len(self._index),), (len(value),))
            self._columns[key] = Series([value[i] for i in range(len(value))], name=key)
        elif isinstance(value, list):
            if len(value) != len(self._index):
                raise ShapeError((len(self._index),), (len(value),))
            self._columns[key] = Series(value, name=key)
        else:
            raise TypeError(f"Invalid value type: {type(value)}")

    def add_column(self, name: str, data: Series | list[Any]) -> None:
        """Add a new column."""
        self[name] = data

    def drop(self, columns: str | list[str]) -> "DataFrame":
        """Drop columns."""
        if isinstance(columns, str):
            columns = [columns]
        new_data = {}
        for col_name, series in self._columns.items():
            if col_name not in columns:
                new_data[col_name] = [series[i] for i in range(len(self._index))]
        return DataFrame(new_data, index=self._index)

    def rename(self, mapping: dict[str, str]) -> "DataFrame":
        """Rename columns."""
        new_data = {}
        for col_name, series in self._columns.items():
            new_name = mapping.get(col_name, col_name)
            new_data[new_name] = [series[i] for i in range(len(self._index))]
        return DataFrame(new_data, index=self._index)

    def copy(self) -> "DataFrame":
        """Make a shallow copy."""
        new_data = {}
        for col_name, series in self._columns.items():
            new_data[col_name] = [series[i] for i in range(len(self._index))]
        return DataFrame(new_data, index=list(self._index))

    def deepcopy(self) -> "DataFrame":
        """Make a deep copy."""
        return deepcopy(self)

    def iterrows(self) -> Iterator[tuple[Any, dict[str, Any]]]:
        """Iterate over rows as (index, dict) pairs."""
        for idx_val in self._index:
            row_dict = {}
            for col_name in self._columns:
                row_dict[col_name] = self[col_name][self._index.index(idx_val)]
            yield idx_val, row_dict

    def itertuples(self, name: str = "Row") -> Iterator[Any]:
        """Iterate over rows as named tuples."""
        from collections import namedtuple

        RowTuple = namedtuple(name, ["index"] + self.columns)
        for idx_val in self._index:
            values = [idx_val]
            for col_name in self._columns:
                values.append(self[col_name][self._index.index(idx_val)])
            yield RowTuple(*values)

    def __repr__(self) -> str:
        """String representation with aligned columns."""
        if len(self._index) == 0:
            return "Empty DataFrame"

        # Prepare header and data
        col_names = self.columns
        rows_to_show = min(10, len(self._index))

        # Calculate column widths
        col_widths = {}
        for col_name in col_names:
            col_widths[col_name] = max(len(col_name), 10)

        # Build display
        lines = []
        header = " | ".join(col_name.ljust(col_widths[col_name]) for col_name in col_names)
        lines.append(header)
        lines.append("-" * len(header))

        for i in range(rows_to_show):
            row_values = []
            for col_name in col_names:
                val = self[col_name][i]
                display = "None" if val is None else str(val)[: col_widths[col_name]]
                row_values.append(display.ljust(col_widths[col_name]))
            lines.append(" | ".join(row_values))

        if len(self._index) > rows_to_show:
            lines.append(f"... ({len(self._index) - rows_to_show} more rows)")

        return "\n".join(lines)

    def astype(self, dtype_map: dict[str, DType]) -> "DataFrame":
        """Convert column data types."""
        new_data = {}
        for col_name, series in self._columns.items():
            if col_name in dtype_map:
                target_dtype = dtype_map[col_name]
                converted = []
                for i in range(len(series)):
                    val = series[i]
                    if val is None:
                        converted.append(None)
                    else:
                        converted.append(series._convert_value(val, target_dtype))
                new_data[col_name] = converted
            else:
                new_data[col_name] = [series[i] for i in range(len(series))]
        return DataFrame(new_data, index=self._index)

    def to_dict(self, orient: str = "dict") -> dict[str, Any]:
        """Convert to dictionary.

        Args:
            orient: 'dict' (col->list), 'records' (list of dicts), 'index' (index->row_dict)
        """
        if orient == "dict":
            return {col_name: [self[col_name][i] for i in range(len(self._index))] for col_name in self.columns}
        elif orient == "records":
            result = []
            for idx_val in self._index:
                row_dict = {}
                idx = self._index.index(idx_val)
                for col_name in self.columns:
                    row_dict[col_name] = self[col_name][idx]
                result.append(row_dict)
            return {"records": result}
        elif orient == "index":
            result = {}
            for idx_val in self._index:
                row_dict = {}
                idx = self._index.index(idx_val)
                for col_name in self.columns:
                    row_dict[col_name] = self[col_name][idx]
                result[idx_val] = row_dict
            return result
        else:
            raise ValueError(f"Unknown orient: {orient}")

    def to_list(self) -> list[list[Any]]:
        """Convert to list of lists."""
        result = []
        for idx_val in self._index:
            row = []
            idx = self._index.index(idx_val)
            for col_name in self.columns:
                row.append(self[col_name][idx])
            result.append(row)
        return result
