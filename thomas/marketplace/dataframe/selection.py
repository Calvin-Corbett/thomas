"""Selection/indexing for DataFrames and Series."""

from typing import Any, Union

try:
    from ._exceptions import ColumnNotFoundError, DataFrameError
    from ._types import DType
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from _exceptions import ColumnNotFoundError, DataFrameError
    from _types import DType
    from frame import DataFrame
    from series import Series


class Loc:
    """Label-based indexing for DataFrames."""

    def __init__(self, df: DataFrame) -> None:
        """Initialize Loc indexer.

        Args:
            df: The DataFrame to index
        """
        self.df = df

    def __getitem__(self, key: Any | tuple[Any, str | list[str]]) -> Union[Series, "DataFrame", Any]:
        """Get by label(s).

        Examples:
            df.loc[0] -> row 0 as dict
            df.loc[0, 'col'] -> single value
            df.loc[0, ['col1', 'col2']] -> row as dict with selected columns
            df.loc[df['col'] > 5] -> boolean mask
        """
        if isinstance(key, tuple):
            row_key, col_key = key
            return self._get_row_col(row_key, col_key)
        else:
            return self._get_rows(key)

    def _get_rows(self, key: Any) -> Union[dict[str, Any], "DataFrame"]:
        """Get row(s) by label or boolean mask."""
        if isinstance(key, Series):
            # Boolean mask
            if key.dtype != DType.BOOL:
                raise DataFrameError("Boolean mask must have BOOL dtype")
            if len(key) != len(self.df._index):
                raise DataFrameError("Mask length must match DataFrame length")

            new_data = {}
            indices = [i for i in range(len(key)) if key[i]]

            for col_name, series in self.df._columns.items():
                new_data[col_name] = [series[i] for i in indices]

            return DataFrame(new_data, index=[self.df._index[i] for i in indices])
        else:
            # Single label
            try:
                idx = self.df._index.index(key)
            except ValueError:
                raise DataFrameError(f"Index label {key} not found")

            row_dict = {}
            for col_name in self.df.columns:
                row_dict[col_name] = self.df[col_name][idx]
            return row_dict

    def _get_row_col(self, row_key: Any, col_key: str | list[str]) -> Any | Series | dict[str, Any]:
        """Get specific cell(s) or row subset."""
        if isinstance(row_key, Series):
            # Boolean mask with column selection
            if isinstance(col_key, str):
                return self.df[col_key][row_key]
            else:
                sub_df = self.df[col_key]
                new_data = {}
                indices = [i for i in range(len(row_key)) if row_key[i]]
                for col_name in sub_df.columns:
                    new_data[col_name] = [sub_df[col_name][i] for i in indices]
                return DataFrame(new_data, index=[self.df._index[i] for i in indices])
        else:
            # Single row
            try:
                idx = self.df._index.index(row_key)
            except ValueError:
                raise DataFrameError(f"Index label {row_key} not found")

            if isinstance(col_key, str):
                return self.df[col_key][idx]
            else:
                row_dict = {}
                for col_name in col_key:
                    if col_name not in self.df.columns:
                        raise ColumnNotFoundError(col_name, self.df.columns)
                    row_dict[col_name] = self.df[col_name][idx]
                return row_dict


class ILoc:
    """Integer-based indexing for DataFrames."""

    def __init__(self, df: DataFrame) -> None:
        """Initialize ILoc indexer.

        Args:
            df: The DataFrame to index
        """
        self.df = df

    def __getitem__(self, key: int | slice | tuple[Any, int | list[int]]) -> Union[Any, Series, "DataFrame"]:
        """Get by integer position.

        Examples:
            df.iloc[0] -> first row
            df.iloc[0:5] -> rows 0-4
            df.iloc[0, 1] -> single value
            df.iloc[0:5, [0, 2]] -> rows 0-4, columns 0 and 2
        """
        if isinstance(key, tuple):
            row_key, col_key = key
            return self._get_row_col(row_key, col_key)
        else:
            return self._get_rows(key)

    def _get_rows(self, key: int | slice) -> Union[dict[str, Any], "DataFrame"]:
        """Get row(s) by integer position."""
        if isinstance(key, int):
            if key < 0:
                key += len(self.df._index)
            if key < 0 or key >= len(self.df._index):
                raise IndexError(f"Index {key} out of range")

            row_dict = {}
            for col_name in self.df.columns:
                row_dict[col_name] = self.df[col_name][key]
            return row_dict
        elif isinstance(key, slice):
            indices = range(*key.indices(len(self.df._index)))
            new_data = {}
            for col_name, series in self.df._columns.items():
                new_data[col_name] = [series[i] for i in indices]
            return DataFrame(new_data, index=[self.df._index[i] for i in indices])
        raise TypeError(f"Invalid index type: {type(key)}")

    def _get_row_col(self, row_key: int | slice, col_key: int | list[int]) -> Any | Series | dict[str, Any]:
        """Get specific cell(s) or subset."""
        col_names = self.df.columns

        # Resolve column indices
        if isinstance(col_key, int):
            if col_key < 0:
                col_key += len(col_names)
            col_names_selected = [col_names[col_key]]
        else:
            col_names_selected = [col_names[i] for i in col_key]

        # Resolve row indices
        if isinstance(row_key, int):
            if row_key < 0:
                row_key += len(self.df._index)
            if col_key == int and len(col_names_selected) == 1:
                return self.df[col_names_selected[0]][row_key]
            else:
                row_dict = {}
                for col_name in col_names_selected:
                    row_dict[col_name] = self.df[col_name][row_key]
                return row_dict
        elif isinstance(row_key, slice):
            indices = range(*row_key.indices(len(self.df._index)))
            new_data = {}
            for col_name in col_names_selected:
                new_data[col_name] = [self.df[col_name][i] for i in indices]
            return DataFrame(new_data, index=[self.df._index[i] for i in indices])
        raise TypeError(f"Invalid row key type: {type(row_key)}")


class QueryParser:
    """Simple query string parser for conditional selection."""

    @staticmethod
    def parse(df: DataFrame, query: str) -> Series:
        """Parse and evaluate a query string.

        Supports simple expressions like:
            'col > 5'
            'col == "value"'
            '(col1 > 5) & (col2 < 10)'

        Args:
            df: The DataFrame to query
            query: Query string

        Returns:
            Boolean Series indicating matching rows
        """
        # Handle parentheses recursively
        while "(" in query:
            innermost = None
            start = -1
            for i, c in enumerate(query):
                if c == "(":
                    start = i
                elif c == ")":
                    innermost = query[start + 1 : i]
                    break
            if innermost:
                QueryParser.parse(df, innermost)
                # Replace with placeholder
                query = query[:start] + "__RESULT__" + query[i + 1 :]
            else:
                break

        # Split by operators
        for op in ["|", "&"]:
            if op in query:
                parts = query.split(op)
                left = QueryParser.parse(df, parts[0].strip())
                right = QueryParser.parse(df, parts[1].strip())
                if op == "|":
                    result_data = [left[i] or right[i] for i in range(len(left))]
                else:  # &
                    result_data = [left[i] and right[i] for i in range(len(left))]
                return Series(result_data, dtype=DType.BOOL)

        # Single condition
        for comp_op in [">=", "<=", "!=", "==", ">", "<"]:
            if comp_op in query:
                col_part, val_part = query.split(comp_op, 1)
                col_name = col_part.strip()
                val_str = val_part.strip()

                if col_name not in df.columns:
                    raise ColumnNotFoundError(col_name, df.columns)

                col = df[col_name]

                # Parse value
                if (
                    val_str.startswith('"')
                    and val_str.endswith('"')
                    or val_str.startswith("'")
                    and val_str.endswith("'")
                ):
                    value = val_str[1:-1]
                else:
                    try:
                        value = float(val_str) if "." in val_str else int(val_str)
                    except ValueError:
                        value = val_str

                # Apply comparison
                if comp_op == "==":
                    return col == value
                elif comp_op == "!=":
                    return col != value
                elif comp_op == ">":
                    return col > value
                elif comp_op == "<":
                    return col < value
                elif comp_op == ">=":
                    return col >= value
                elif comp_op == "<=":
                    return col <= value

        raise DataFrameError(f"Could not parse query: {query}")


def boolean_indexing(df: DataFrame, mask: Series) -> DataFrame:
    """Select rows using a boolean mask.

    Args:
        df: The DataFrame to select from
        mask: Boolean Series of same length as df

    Returns:
        Filtered DataFrame
    """
    if mask.dtype != DType.BOOL:
        raise DataFrameError("Mask must have BOOL dtype")
    if len(mask) != len(df._index):
        raise DataFrameError("Mask length must match DataFrame length")

    indices = [i for i in range(len(mask)) if mask[i]]
    new_data = {}
    for col_name, series in df._columns.items():
        new_data[col_name] = [series[i] for i in indices]

    return DataFrame(new_data, index=[df._index[i] for i in indices])
