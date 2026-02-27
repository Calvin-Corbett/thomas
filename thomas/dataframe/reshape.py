"""Reshaping operations for DataFrames."""

from collections import defaultdict
from typing import Any

try:
    from ._exceptions import DataFrameError
    from ._types import DType
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from _exceptions import DataFrameError
    from frame import DataFrame
    from series import Series


class ReshapeOperations:
    """Reshape/transform operations."""

    @staticmethod
    def pivot(df: DataFrame, index: str, columns: str, values: str, aggfunc: str = "first") -> DataFrame:
        """Pivot table: long to wide.

        Args:
            df: DataFrame to pivot
            index: Column for row indices
            columns: Column for new column headers
            values: Column for cell values
            aggfunc: Aggregation function for duplicates

        Returns:
            Pivoted DataFrame
        """
        # Group by index and columns
        groups: dict[tuple[Any, Any], list[Any]] = defaultdict(list)

        for idx in range(len(df._index)):
            idx_val = df[index][idx]
            col_val = df[columns][idx]
            val = df[values][idx]
            groups[(idx_val, col_val)].append(val)

        # Aggregate duplicates
        result_data: dict[str, list[Any]] = defaultdict(list)
        unique_rows = sorted(set(k[0] for k in groups), key=str)
        unique_cols = sorted(set(k[1] for k in groups), key=str)

        for row_key in unique_rows:
            result_data[index].append(row_key)
            for col_key in unique_cols:
                key = (row_key, col_key)
                if key in groups:
                    vals = groups[key]
                    if aggfunc == "first":
                        result_data[str(col_key)].append(vals[0])
                    elif aggfunc == "sum":
                        result_data[str(col_key)].append(sum(v for v in vals if v is not None))
                    elif aggfunc == "mean":
                        non_null = [v for v in vals if v is not None]
                        result_data[str(col_key)].append(sum(non_null) / len(non_null) if non_null else None)
                    elif aggfunc == "count":
                        result_data[str(col_key)].append(len(vals))
                    else:
                        result_data[str(col_key)].append(vals[0])
                else:
                    result_data[str(col_key)].append(None)

        return DataFrame(dict(result_data))

    @staticmethod
    def melt(
        df: DataFrame,
        id_vars: str | list[str],
        value_vars: str | list[str] | None = None,
        var_name: str = "variable",
        value_name: str = "value",
    ) -> DataFrame:
        """Melt: wide to long.

        Args:
            df: DataFrame to melt
            id_vars: Columns to keep as identifiers
            value_vars: Columns to unpivot (all others if None)
            var_name: Name for variable column
            value_name: Name for value column

        Returns:
            Melted DataFrame
        """
        if isinstance(id_vars, str):
            id_vars = [id_vars]

        if value_vars is None:
            value_vars = [col for col in df.columns if col not in id_vars]
        elif isinstance(value_vars, str):
            value_vars = [value_vars]

        result_data: dict[str, list[Any]] = defaultdict(list)

        for row_idx in range(len(df._index)):
            for col in id_vars:
                result_data[col].append(df[col][row_idx])

            for val_col in value_vars:
                for col in id_vars:
                    result_data[col].append(df[col][row_idx])

                result_data[var_name].append(val_col)
                result_data[value_name].append(df[val_col][row_idx])

        return DataFrame(dict(result_data))

    @staticmethod
    def stack(df: DataFrame) -> DataFrame:
        """Stack: convert columns to rows.

        Args:
            df: DataFrame to stack

        Returns:
            Stacked DataFrame
        """
        rows = []
        for row_idx in range(len(df._index)):
            for col_name in df.columns:
                val = df[col_name][row_idx]
                rows.append({"index": df._index[row_idx], "column": col_name, "value": val})

        return DataFrame(rows)

    @staticmethod
    def unstack(df: DataFrame, col: str = "column") -> DataFrame:
        """Unstack: convert rows to columns.

        Args:
            df: DataFrame to unstack
            col: Column to use for new column headers

        Returns:
            Unstacked DataFrame
        """
        # Assume structure: index, column, value
        result_data: dict[str, list[Any]] = defaultdict(list)
        unique_rows = sorted(set(row["index"] for row in df.to_dict("records")))
        unique_cols = sorted(set(row[col] for row in df.to_dict("records")))

        for row_key in unique_rows:
            result_data["index"].append(row_key)
            for col_key in unique_cols:
                matching = [row for row in df.to_dict("records") if row["index"] == row_key and row[col] == col_key]
                if matching:
                    result_data[str(col_key)].append(matching[0].get("value"))
                else:
                    result_data[str(col_key)].append(None)

        return DataFrame(dict(result_data))

    @staticmethod
    def transpose(df: DataFrame) -> DataFrame:
        """Transpose: swap rows and columns.

        Args:
            df: DataFrame to transpose

        Returns:
            Transposed DataFrame
        """
        result_data: dict[Any, list[Any]] = {}

        for row_idx in range(len(df._index)):
            row_key = df._index[row_idx]
            result_data[row_key] = []

            for col_name in df.columns:
                result_data[row_key].append(df[col_name][row_idx])

        # Convert to DataFrame with column names as index
        new_data = {}
        for col_name in df.columns:
            new_data[col_name] = []
            for row_idx in range(len(df._index)):
                new_data[col_name].append(df[col_name][row_idx])

        result = DataFrame(new_data, index=df.columns)
        result._columns = {}
        for row_idx, row_key in enumerate(df._index):
            col_data = [df[col_name][row_idx] for col_name in df.columns]
            result._columns[row_key] = Series(col_data, name=row_key)

        return result

    @staticmethod
    def crosstab(series1: Series, series2: Series, values: Series | None = None, aggfunc: str = "count") -> DataFrame:
        """Create a crosstab (frequency table).

        Args:
            series1: Series for rows
            series2: Series for columns
            values: Values to aggregate (if None, count)
            aggfunc: Aggregation function

        Returns:
            Cross-tabulation DataFrame
        """
        if len(series1) != len(series2):
            raise DataFrameError("Series lengths must match")

        groups: dict[tuple[Any, Any], list[Any]] = defaultdict(list)

        for i in range(len(series1)):
            key = (series1[i], series2[i])
            if values is not None:
                groups[key].append(values[i])
            else:
                groups[key].append(1)

        # Build result
        result_data: dict[str, list[Any]] = defaultdict(list)
        unique_rows = sorted(set(k[0] for k in groups), key=str)
        unique_cols = sorted(set(k[1] for k in groups), key=str)

        for row_key in unique_rows:
            result_data["row"].append(row_key)
            for col_key in unique_cols:
                key = (row_key, col_key)
                if key in groups:
                    vals = groups[key]
                    if aggfunc == "count":
                        result_data[str(col_key)].append(len(vals))
                    elif aggfunc == "sum":
                        result_data[str(col_key)].append(sum(vals))
                    elif aggfunc == "mean":
                        result_data[str(col_key)].append(sum(vals) / len(vals) if vals else None)
                    else:
                        result_data[str(col_key)].append(len(vals))
                else:
                    result_data[str(col_key)].append(0)

        return DataFrame(dict(result_data))

    @staticmethod
    def explode(df: DataFrame, col: str) -> DataFrame:
        """Explode a list column into multiple rows.

        Args:
            df: DataFrame with list column
            col: Column name containing lists

        Returns:
            Exploded DataFrame
        """
        result_data: dict[str, list[Any]] = defaultdict(list)

        for row_idx in range(len(df._index)):
            list_val = df[col][row_idx]

            if not isinstance(list_val, list):
                # Single value, keep as is
                for col_name in df.columns:
                    result_data[col_name].append(df[col_name][row_idx])
            else:
                # Explode the list
                for item in list_val:
                    for col_name in df.columns:
                        if col_name == col:
                            result_data[col_name].append(item)
                        else:
                            result_data[col_name].append(df[col_name][row_idx])

        return DataFrame(dict(result_data))
