"""I/O operations for DataFrames."""

import csv
import json
from io import StringIO as _StringIO
from typing import Any

try:
    from ._exceptions import DataFrameError
    from ._types import DType, infer_dtype, promote_dtype
    from .frame import DataFrame
    from .series import Series
except ImportError:
    from frame import DataFrame

# Use the standard library StringIO
StringIO = _StringIO


class CSVReader:
    """CSV parsing with type inference."""

    @staticmethod
    def read_csv(
        data: str,
        delimiter: str = ",",
        quotechar: str = '"',
        escapechar: str | None = None,
        has_header: bool = True,
        infer_types: bool = True,
    ) -> DataFrame:
        """Read CSV data into a DataFrame.

        Args:
            data: CSV string
            delimiter: Field delimiter
            quotechar: Quote character
            escapechar: Escape character
            has_header: Whether first row is header
            infer_types: Whether to infer column types

        Returns:
            DataFrame containing parsed data
        """
        reader = csv.reader(StringIO(data), delimiter=delimiter, quotechar=quotechar, escapechar=escapechar)

        rows = list(reader)
        if not rows:
            return DataFrame()

        if has_header:
            headers = rows[0]
            data_rows = rows[1:]
        else:
            headers = [f"col_{i}" for i in range(len(rows[0]))]
            data_rows = rows

        # Parse data
        columns: dict[str, list[Any]] = {h: [] for h in headers}

        for row in data_rows:
            for i, header in enumerate(headers):
                if i < len(row):
                    value = row[i].strip() if isinstance(row[i], str) else row[i]
                    if value == "" or value.lower() == "none" or value.lower() == "null":
                        columns[header].append(None)
                    else:
                        columns[header].append(value)
                else:
                    columns[header].append(None)

        # Infer types
        if infer_types:
            for col_name in columns:
                columns[col_name] = CSVReader._infer_column_type(columns[col_name])

        return DataFrame(columns)

    @staticmethod
    def _infer_column_type(col_data: list[Any]) -> list[Any]:
        """Infer and convert column to appropriate type."""
        if not col_data:
            return col_data

        # Try to infer a common type
        non_null = [v for v in col_data if v is not None]
        if not non_null:
            return col_data

        inferred = None
        for val in non_null:
            val_type = CSVReader._infer_value_type(val)
            if inferred is None:
                inferred = val_type
            else:
                inferred = CSVReader._promote_type(inferred, val_type)

        # Convert all values
        result = []
        for val in col_data:
            if val is None:
                result.append(None)
            else:
                result.append(CSVReader._convert_value(val, inferred))

        return result

    @staticmethod
    def _infer_value_type(value: Any) -> str:
        """Infer the type of a string value."""
        if isinstance(value, str):
            if value.lower() in ("true", "false"):
                return "bool"
            try:
                int(value)
                return "int"
            except ValueError:
                pass
            try:
                float(value)
                return "float"
            except ValueError:
                pass
        return "str"

    @staticmethod
    def _promote_type(type1: str, type2: str) -> str:
        """Promote two types to a common type."""
        if type1 == type2:
            return type1
        if type1 == "str" or type2 == "str":
            return "str"
        if {type1, type2} == {"int", "float"}:
            return "float"
        if {type1, type2} == {"int", "bool"}:
            return "int"
        if {type1, type2} == {"float", "bool"}:
            return "float"
        return "str"

    @staticmethod
    def _convert_value(value: Any, target_type: str) -> Any:
        """Convert a value to target type."""
        if value is None:
            return None
        if target_type == "int":
            return int(float(value))
        if target_type == "float":
            return float(value)
        if target_type == "bool":
            return value.lower() in ("true", "1", "yes")
        return str(value)


class CSVWriter:
    """CSV writing."""

    @staticmethod
    def write_csv(
        df: DataFrame,
        include_header: bool = True,
        include_index: bool = False,
        delimiter: str = ",",
        quotechar: str = '"',
    ) -> str:
        """Write DataFrame to CSV string.

        Args:
            df: DataFrame to write
            include_header: Whether to write header row
            include_index: Whether to include index column
            delimiter: Field delimiter
            quotechar: Quote character

        Returns:
            CSV string
        """
        output = StringIO()
        writer = csv.writer(output, delimiter=delimiter, quotechar=quotechar)

        # Write header
        if include_header:
            header = []
            if include_index:
                header.append("index")
            header.extend(df.columns)
            writer.writerow(header)

        # Write rows
        for idx_val in df._index:
            row = []
            if include_index:
                row.append(idx_val)
            idx = df._index.index(idx_val)
            for col_name in df.columns:
                val = df[col_name][idx]
                row.append(val if val is not None else "")
            writer.writerow(row)

        return output.getvalue()


class JSONHandler:
    """JSON reading/writing."""

    @staticmethod
    def read_json(data: str, orient: str = "records") -> DataFrame:
        """Read JSON into DataFrame.

        Args:
            data: JSON string
            orient: 'records' (list of dicts), 'dict' (col->list), 'index' (index->row)

        Returns:
            DataFrame
        """
        obj = json.loads(data)

        if orient == "records":
            if isinstance(obj, list):
                return DataFrame(obj)
            elif "records" in obj:
                return DataFrame(obj["records"])
        elif orient == "dict":
            if isinstance(obj, dict):
                return DataFrame(obj)
        elif orient == "index":
            if isinstance(obj, dict):
                dfs = []
                for idx_val, row_dict in obj.items():
                    dfs.append(DataFrame([row_dict]))
                from .joins import JoinOperation

                if dfs:
                    result = dfs[0]
                    for df in dfs[1:]:
                        result = JoinOperation.concat([result, df], axis=0)
                    result._index = list(obj.keys())
                    return result

        return DataFrame()

    @staticmethod
    def write_json(df: DataFrame, orient: str = "records") -> str:
        """Write DataFrame to JSON string.

        Args:
            df: DataFrame to write
            orient: 'records', 'dict', or 'index'

        Returns:
            JSON string
        """
        if orient == "records":
            records = []
            for idx_val in df._index:
                row_dict = {}
                idx = df._index.index(idx_val)
                for col_name in df.columns:
                    val = df[col_name][idx]
                    row_dict[col_name] = val
                records.append(row_dict)
            return json.dumps(records)
        elif orient == "dict":
            data = {}
            for col_name in df.columns:
                data[col_name] = []
                for idx_val in df._index:
                    idx = df._index.index(idx_val)
                    data[col_name].append(df[col_name][idx])
            return json.dumps(data)
        elif orient == "index":
            data = {}
            for idx_val in df._index:
                row_dict = {}
                idx = df._index.index(idx_val)
                for col_name in df.columns:
                    val = df[col_name][idx]
                    row_dict[col_name] = val
                data[str(idx_val)] = row_dict
            return json.dumps(data)
        else:
            raise ValueError(f"Unknown orient: {orient}")


class MarkdownTable:
    """Markdown table output."""

    @staticmethod
    def to_markdown(df: DataFrame, max_rows: int = 10) -> str:
        """Convert DataFrame to Markdown table.

        Args:
            df: DataFrame to convert
            max_rows: Maximum rows to display

        Returns:
            Markdown table string
        """
        if len(df._index) == 0:
            return "Empty DataFrame"

        lines = []
        rows_to_show = min(max_rows, len(df._index))

        # Header
        header_parts = ["| index | " + " | ".join(df.columns) + " |"]
        lines.append(header_parts[0])

        # Separator
        sep_parts = ["|-" + "-|-" * (len(df.columns) + 1) + "|"]
        lines.append(sep_parts[0])

        # Rows
        for i in range(rows_to_show):
            row_parts = [f"| {df._index[i]} |"]
            for col_name in df.columns:
                val = df[col_name][i]
                display = str(val) if val is not None else "None"
                row_parts.append(f" {display} |")
            lines.append("".join(row_parts))

        if len(df._index) > rows_to_show:
            lines.append(f"... ({len(df._index) - rows_to_show} more rows)")

        return "\n".join(lines)
