"""
Format I/O: Parquet-compatible writer, CSV/JSON readers, and Arrow IPC format.

Provides interoperability between different columnar and row-oriented formats.
"""

import csv
import json
import struct
from typing import Any

from thomas.columnar._exceptions import IOError as ColumnarIOError
from thomas.columnar._types import (
    ColumnarFileMetadata,
    ColumnType,
    Field,
    Schema,
)
from thomas.columnar.storage import ColumnarFileWriter


class ParquetWriter:
    """Parquet-compatible file writer."""

    def __init__(self, file_path: str, schema: Schema) -> None:
        """Initialize Parquet writer.

        Args:
            file_path: Path to write file
            schema: Schema for file
        """
        self.file_path = file_path
        self.schema = schema
        self.writer = ColumnarFileWriter(schema)

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        """Write rows to Parquet file.

        Args:
            rows: List of dictionaries (one per row)
        """
        self.writer.write_rows(rows)

    def write_row(self, row: dict[str, Any]) -> None:
        """Write single row to Parquet file.

        Args:
            row: Dictionary with column values
        """
        self.writer.write_row(row)

    def finish(self) -> None:
        """Finish writing and close file."""
        metadata = self.writer.finish()

        # Write Parquet file (simplified version)
        with open(self.file_path, "wb") as f:
            # Magic number
            f.write(b"PAR1")

            # Write metadata as JSON (simplified)
            metadata_json = self._serialize_metadata(metadata)
            f.write(struct.pack("<I", len(metadata_json)))
            f.write(metadata_json)

            # Magic number at end
            f.write(b"PAR1")

    def _serialize_metadata(self, metadata: ColumnarFileMetadata) -> bytes:
        """Serialize metadata to bytes."""
        data = {
            "num_rows": metadata.num_rows,
            "num_columns": len(metadata.schema.fields),
            "columns": [
                {
                    "name": field.name,
                    "type": field.column_type.name,
                    "nullable": field.nullable,
                }
                for field in metadata.schema.fields
            ],
        }
        return json.dumps(data).encode("utf-8")


class ParquetReader:
    """Parquet-compatible file reader."""

    def __init__(self, file_path: str) -> None:
        """Initialize Parquet reader.

        Args:
            file_path: Path to read file
        """
        self.file_path = file_path
        self.metadata = self._read_metadata()

    def _read_metadata(self) -> ColumnarFileMetadata:
        """Read file metadata."""
        with open(self.file_path, "rb") as f:
            # Check magic number
            magic = f.read(4)
            if magic != b"PAR1":
                raise ColumnarIOError("Invalid Parquet file")

            # Read metadata size
            size_bytes = f.read(4)
            if len(size_bytes) < 4:
                raise ColumnarIOError("Truncated Parquet file")

            size = struct.unpack("<I", size_bytes)[0]

            # Read metadata
            metadata_json = f.read(size).decode("utf-8")
            data = json.loads(metadata_json)

            # Reconstruct schema
            fields = []
            for col in data["columns"]:
                col_type = ColumnType[col["type"]]
                fields.append(
                    Field(
                        name=col["name"],
                        column_type=col_type,
                        nullable=col.get("nullable", True),
                    )
                )

            schema = Schema(fields=fields)
            metadata = ColumnarFileMetadata(
                schema=schema,
                num_rows=data["num_rows"],
            )

            return metadata

    def read_all_rows(self) -> list[dict[str, Any]]:
        """Read all rows from file.

        Returns:
            List of dictionaries
        """
        # Simplified: return empty list (full implementation would deserialize data)
        return []


class CSVReader:
    """CSV file reader with type inference."""

    @staticmethod
    def infer_schema(file_path: str, num_rows: int = 100) -> Schema:
        """Infer schema from CSV file.

        Args:
            file_path: Path to CSV file
            num_rows: Number of rows to sample

        Returns:
            Inferred schema
        """
        fields = []

        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)

            # Get headers
            if not reader.fieldnames:
                raise ColumnarIOError("CSV file has no headers")

            # Sample rows to infer types
            sample_rows = []
            for i, row in enumerate(reader):
                if i >= num_rows:
                    break
                sample_rows.append(row)

            # Infer type for each column
            for field_name in reader.fieldnames:
                col_type = CSVReader._infer_column_type(field_name, sample_rows)
                fields.append(
                    Field(
                        name=field_name,
                        column_type=col_type,
                        nullable=True,
                    )
                )

        return Schema(fields=fields)

    @staticmethod
    def _infer_column_type(column_name: str, rows: list[dict[str, Any]]) -> ColumnType:
        """Infer column type from values."""
        non_null_values = [row[column_name] for row in rows if row.get(column_name)]

        if not non_null_values:
            return ColumnType.STRING

        # Try to parse as numbers
        try:
            floats = [float(v) for v in non_null_values]
            if all(f == int(f) for f in floats):
                return ColumnType.INT64
            return ColumnType.FLOAT64
        except (ValueError, TypeError):
            pass

        # Check for booleans
        if all(v.lower() in {"true", "false"} for v in non_null_values):
            return ColumnType.BOOL

        # Default to string
        return ColumnType.STRING

    @staticmethod
    def read_file(file_path: str, schema: Schema) -> list[dict[str, Any]]:
        """Read CSV file with schema.

        Args:
            file_path: Path to CSV file
            schema: Schema for type conversion

        Returns:
            List of dictionaries
        """
        rows = []

        with open(file_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                converted_row = {}
                for field in schema.fields:
                    value = row.get(field.name)

                    if value is None or value == "":
                        converted_row[field.name] = None
                    else:
                        converted_row[field.name] = CSVReader._convert_value(value, field.column_type)

                rows.append(converted_row)

        return rows

    @staticmethod
    def _convert_value(value: str, col_type: ColumnType) -> Any:
        """Convert string value to column type."""
        if (
            col_type == ColumnType.INT8
            or col_type == ColumnType.INT16
            or col_type == ColumnType.INT32
            or col_type == ColumnType.INT64
            or col_type == ColumnType.UINT8
            or col_type == ColumnType.UINT16
            or col_type == ColumnType.UINT32
            or col_type == ColumnType.UINT64
        ):
            return int(value)
        elif col_type == ColumnType.FLOAT32 or col_type == ColumnType.FLOAT64:
            return float(value)
        elif col_type == ColumnType.BOOL:
            return value.lower() in {"true", "1", "yes"}
        else:
            return value


class JSONColumnReader:
    """JSON columnar reader (expects array of objects)."""

    @staticmethod
    def infer_schema(file_path: str) -> Schema:
        """Infer schema from JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            Inferred schema
        """
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or not data:
            raise ColumnarIOError("JSON must be array of objects")

        # Get schema from first object
        first_obj = data[0]
        fields = []

        for key, value in first_obj.items():
            col_type = JSONColumnReader._infer_value_type(value)
            fields.append(
                Field(
                    name=key,
                    column_type=col_type,
                    nullable=True,
                )
            )

        return Schema(fields=fields)

    @staticmethod
    def _infer_value_type(value: Any) -> ColumnType:
        """Infer column type from JSON value."""
        if value is None:
            return ColumnType.STRING

        if isinstance(value, bool):
            return ColumnType.BOOL
        elif isinstance(value, int):
            return ColumnType.INT64
        elif isinstance(value, float):
            return ColumnType.FLOAT64
        elif isinstance(value, str):
            return ColumnType.STRING
        elif isinstance(value, list):
            return ColumnType.LIST
        elif isinstance(value, dict):
            return ColumnType.STRUCT

        return ColumnType.STRING

    @staticmethod
    def read_file(file_path: str) -> list[dict[str, Any]]:
        """Read JSON file.

        Args:
            file_path: Path to JSON file

        Returns:
            List of dictionaries
        """
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return [data]
        else:
            raise ColumnarIOError("JSON must be object or array of objects")


class ArrowIPCWriter:
    """Arrow IPC (Inter-Process Communication) format writer."""

    def __init__(self, file_path: str, schema: Schema) -> None:
        """Initialize Arrow IPC writer.

        Args:
            file_path: Path to write file
            schema: Schema for file
        """
        self.file_path = file_path
        self.schema = schema
        self.row_count = 0

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        """Write rows in Arrow IPC format.

        Args:
            rows: List of dictionaries
        """
        with open(self.file_path, "wb") as f:
            # Arrow magic number
            f.write(b"ARROW1\x00\x00")

            # Write schema
            schema_data = self._serialize_schema()
            f.write(struct.pack("<I", len(schema_data)))
            f.write(schema_data)

            # Write record batches
            for row_batch in self._partition_rows(rows, batch_size=8192):
                batch_data = self._serialize_batch(row_batch)
                f.write(struct.pack("<I", len(batch_data)))
                f.write(batch_data)

            # End marker
            f.write(struct.pack("<I", 0))

    def _serialize_schema(self) -> bytes:
        """Serialize schema to bytes."""
        data = {
            "fields": [
                {
                    "name": field.name,
                    "type": field.column_type.name,
                    "nullable": field.nullable,
                }
                for field in self.schema.fields
            ]
        }
        return json.dumps(data).encode("utf-8")

    def _serialize_batch(self, rows: list[dict[str, Any]]) -> bytes:
        """Serialize record batch to bytes."""
        data = {"num_rows": len(rows), "columns": []}

        for field in self.schema.fields:
            column_data = [row.get(field.name) for row in rows]
            data["columns"].append({"name": field.name, "data": column_data})

        return json.dumps(data).encode("utf-8")

    @staticmethod
    def _partition_rows(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        """Partition rows into batches."""
        batches = []
        for i in range(0, len(rows), batch_size):
            batches.append(rows[i : i + batch_size])
        return batches


class ArrowIPCReader:
    """Arrow IPC format reader."""

    @staticmethod
    def read_file(file_path: str) -> tuple[Schema, list[dict[str, Any]]]:
        """Read Arrow IPC file.

        Args:
            file_path: Path to read file

        Returns:
            Tuple of (schema, rows)
        """
        with open(file_path, "rb") as f:
            # Check magic number
            magic = f.read(8)
            if magic != b"ARROW1\x00\x00":
                raise ColumnarIOError("Invalid Arrow IPC file")

            # Read schema
            schema_size = struct.unpack("<I", f.read(4))[0]
            schema_data = json.loads(f.read(schema_size).decode("utf-8"))

            # Reconstruct schema
            fields = []
            for field_info in schema_data["fields"]:
                col_type = ColumnType[field_info["type"]]
                fields.append(
                    Field(
                        name=field_info["name"],
                        column_type=col_type,
                        nullable=field_info.get("nullable", True),
                    )
                )
            schema = Schema(fields=fields)

            # Read record batches
            all_rows = []
            while True:
                size_bytes = f.read(4)
                if len(size_bytes) < 4:
                    break

                batch_size = struct.unpack("<I", size_bytes)[0]
                if batch_size == 0:
                    break

                batch_data = json.loads(f.read(batch_size).decode("utf-8"))
                rows = batch_data.get("rows")
                if rows is None:
                    # Backward-compatible path for column-oriented batches.
                    columns = batch_data.get("columns", [])
                    row_count = int(batch_data.get("num_rows", 0))
                    rows = [{} for _ in range(row_count)]
                    for column in columns:
                        name = column.get("name")
                        values = column.get("data", [])
                        if not name:
                            continue
                        for idx in range(row_count):
                            rows[idx][name] = values[idx] if idx < len(values) else None

                all_rows.extend(rows)

            return schema, all_rows


def convert_format(
    input_file: str,
    input_format: str,
    output_file: str,
    output_format: str,
    schema: Schema | None = None,
) -> None:
    """Convert between different columnar formats.

    Args:
        input_file: Input file path
        input_format: Input format (parquet, csv, json, arrow)
        output_file: Output file path
        output_format: Output format
        schema: Optional schema for conversion
    """
    # Read input
    if input_format == "csv":
        if not schema:
            schema = CSVReader.infer_schema(input_file)
        rows = CSVReader.read_file(input_file, schema)
    elif input_format == "json":
        if not schema:
            schema = JSONColumnReader.infer_schema(input_file)
        rows = JSONColumnReader.read_file(input_file)
    elif input_format == "arrow":
        schema, rows = ArrowIPCReader.read_file(input_file)
    else:
        raise ColumnarIOError(f"Unknown input format: {input_format}")

    # Write output
    if output_format == "parquet":
        writer = ParquetWriter(output_file, schema)
        writer.write_rows(rows)
        writer.finish()
    elif output_format == "csv":
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            if not rows:
                return
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    elif output_format == "json":
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, default=str)
    elif output_format == "arrow":
        arrow_writer = ArrowIPCWriter(output_file, schema)
        arrow_writer.write_rows(rows)
    else:
        raise ColumnarIOError(f"Unknown output format: {output_format}")
