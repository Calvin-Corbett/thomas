"""
Tests for columnar I/O formats: Parquet, CSV, JSON, Arrow.
"""

import os
import tempfile

from thomas.columnar._types import ColumnType, Field, Schema
from thomas.columnar.io_formats import (
    ArrowIPCReader,
    ArrowIPCWriter,
    CSVReader,
    JSONColumnReader,
    ParquetReader,
    ParquetWriter,
    convert_format,
)


class TestParquetIO:
    """Tests for Parquet I/O."""

    def test_write_and_read_parquet(self) -> None:
        """Test writing and reading Parquet file."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.parquet")

            writer = ParquetWriter(file_path, schema)
            rows = [
                {"id": 1, "name": "alice"},
                {"id": 2, "name": "bob"},
            ]
            writer.write_rows(rows)
            writer.finish()

            assert os.path.exists(file_path)

            reader = ParquetReader(file_path)
            assert reader.metadata.num_rows == 2
            assert len(reader.metadata.schema.fields) == 2

    def test_parquet_multiple_writes(self) -> None:
        """Test multiple writes to Parquet."""
        schema = Schema(fields=[Field("value", ColumnType.INT32)])

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.parquet")

            writer = ParquetWriter(file_path, schema)
            for i in range(10):
                writer.write_row({"value": i})
            writer.finish()

            reader = ParquetReader(file_path)
            assert reader.metadata.num_rows == 10


class TestCSVIO:
    """Tests for CSV I/O."""

    def test_infer_schema_from_csv(self) -> None:
        """Test inferring schema from CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.csv")

            with open(file_path, "w") as f:
                f.write("id,score,active\n")
                f.write("1,95.5,true\n")
                f.write("2,87.3,false\n")

            schema = CSVReader.infer_schema(file_path)

            assert len(schema.fields) == 3
            assert schema.fields[0].name == "id"

    def test_read_csv_file(self) -> None:
        """Test reading CSV file."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.csv")

            with open(file_path, "w") as f:
                f.write("id,name\n")
                f.write("1,alice\n")
                f.write("2,bob\n")

            rows = CSVReader.read_file(file_path, schema)

            assert len(rows) == 2
            assert rows[0]["id"] == 1
            assert rows[0]["name"] == "alice"

    def test_csv_type_conversion(self) -> None:
        """Test CSV type conversion."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("score", ColumnType.FLOAT64),
                Field("active", ColumnType.BOOL),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.csv")

            with open(file_path, "w") as f:
                f.write("id,score,active\n")
                f.write("1,95.5,true\n")
                f.write("2,87.3,false\n")

            rows = CSVReader.read_file(file_path, schema)

            assert isinstance(rows[0]["id"], int)
            assert isinstance(rows[0]["score"], float)
            assert isinstance(rows[0]["active"], bool)

    def test_csv_null_handling(self) -> None:
        """Test CSV null value handling."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("value", ColumnType.STRING),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.csv")

            with open(file_path, "w") as f:
                f.write("id,value\n")
                f.write("1,hello\n")
                f.write("2,\n")

            rows = CSVReader.read_file(file_path, schema)

            assert rows[0]["value"] == "hello"
            assert rows[1]["value"] is None


class TestJSONIO:
    """Tests for JSON I/O."""

    def test_infer_schema_from_json(self) -> None:
        """Test inferring schema from JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.json")

            with open(file_path, "w") as f:
                f.write('[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]')

            schema = JSONColumnReader.infer_schema(file_path)

            assert len(schema.fields) == 2

    def test_read_json_file(self) -> None:
        """Test reading JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.json")

            with open(file_path, "w") as f:
                f.write('[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]')

            rows = JSONColumnReader.read_file(file_path)

            assert len(rows) == 2
            assert rows[0]["id"] == 1
            assert rows[0]["name"] == "alice"

    def test_read_single_object_json(self) -> None:
        """Test reading single JSON object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.json")

            with open(file_path, "w") as f:
                f.write('{"id": 1, "name": "alice"}')

            rows = JSONColumnReader.read_file(file_path)

            assert len(rows) == 1
            assert rows[0]["id"] == 1


class TestArrowIPCIO:
    """Tests for Arrow IPC format."""

    def test_write_and_read_arrow(self) -> None:
        """Test writing and reading Arrow IPC format."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("value", ColumnType.FLOAT64),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.arrow")

            writer = ArrowIPCWriter(file_path, schema)
            rows = [
                {"id": 1, "value": 1.5},
                {"id": 2, "value": 2.5},
            ]
            writer.write_rows(rows)

            assert os.path.exists(file_path)

            read_schema, read_rows = ArrowIPCReader.read_file(file_path)

            assert read_schema.fields[0].name == "id"
            assert len(read_rows) == 2

    def test_arrow_batch_writing(self) -> None:
        """Test Arrow batch writing."""
        schema = Schema(fields=[Field("id", ColumnType.INT32)])

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.arrow")

            writer = ArrowIPCWriter(file_path, schema)
            rows = [{"id": i} for i in range(100)]
            writer.write_rows(rows)

            _, read_rows = ArrowIPCReader.read_file(file_path)

            assert len(read_rows) == 100


class TestFormatConversion:
    """Tests for format conversion."""

    def test_convert_csv_to_parquet(self) -> None:
        """Test converting CSV to Parquet."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "test.csv")
            parquet_path = os.path.join(tmpdir, "test.parquet")

            # Create CSV file
            with open(csv_path, "w") as f:
                f.write("id,name\n")
                f.write("1,alice\n")
                f.write("2,bob\n")

            # Convert
            convert_format(csv_path, "csv", parquet_path, "parquet")

            assert os.path.exists(parquet_path)

    def test_convert_json_to_csv(self) -> None:
        """Test converting JSON to CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test.json")
            csv_path = os.path.join(tmpdir, "test.csv")

            # Create JSON file
            with open(json_path, "w") as f:
                f.write('[{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]')

            # Convert
            convert_format(json_path, "json", csv_path, "csv")

            assert os.path.exists(csv_path)

            # Verify CSV content
            with open(csv_path) as f:
                content = f.read()
                assert "alice" in content
                assert "bob" in content


class TestIOEdgeCases:
    """Tests for I/O edge cases."""

    def test_empty_csv_file(self) -> None:
        """Test reading empty CSV file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "empty.csv")

            with open(file_path, "w") as f:
                f.write("id,name\n")

            schema = Schema(
                fields=[
                    Field("id", ColumnType.INT32),
                    Field("name", ColumnType.STRING),
                ]
            )

            rows = CSVReader.read_file(file_path, schema)

            assert len(rows) == 0

    def test_large_json_file(self) -> None:
        """Test reading large JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "large.json")

            rows_data = [{"id": i, "value": i * 2} for i in range(1000)]

            import json

            with open(file_path, "w") as f:
                json.dump(rows_data, f)

            rows = JSONColumnReader.read_file(file_path)

            assert len(rows) == 1000

    def test_parquet_large_schema(self) -> None:
        """Test Parquet with many columns."""
        fields = [Field(f"col_{i}", ColumnType.INT32) for i in range(100)]
        schema = Schema(fields=fields)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.parquet")

            writer = ParquetWriter(file_path, schema)
            writer.write_row({f"col_{i}": i for i in range(100)})
            writer.finish()

            reader = ParquetReader(file_path)
            assert len(reader.metadata.schema.fields) == 100
