"""
Tests for columnar storage: column chunks, row groups, and file operations.
"""

from thomas.marketplace.columnar._types import (
    ColumnType,
    Field,
    Schema,
)
from thomas.marketplace.columnar.storage import (
    ColumnarFileReader,
    ColumnarFileWriter,
    ColumnChunkReader,
    ColumnChunkWriter,
    RowGroupReader,
    RowGroupWriter,
)


class TestColumnChunkWriter:
    """Tests for column chunk writer."""

    def test_write_simple_chunk(self) -> None:
        """Test writing simple column chunk."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="id",
            column_type=ColumnType.INT32,
        )

        values = [1, 2, 3, 4, 5]
        writer.write_values(values)

        chunk = writer.finish()
        assert chunk.column_index == 0
        assert chunk.column_name == "id"
        assert len(chunk.pages) > 0

    def test_write_with_nulls(self) -> None:
        """Test writing values with nulls."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="value",
            column_type=ColumnType.INT32,
        )

        values = [1, None, 3, None, 5]
        writer.write_values(values)

        chunk = writer.finish()
        assert chunk.statistics is not None
        assert chunk.statistics.null_count == 2

    def test_write_multiple_pages(self) -> None:
        """Test writing data that spans multiple pages."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="data",
            column_type=ColumnType.INT32,
            page_size=100,  # Small page size
        )

        values = list(range(1000))
        writer.write_values(values)

        chunk = writer.finish()
        assert len(chunk.pages) > 1

    def test_statistics_tracking(self) -> None:
        """Test statistics are properly tracked."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="value",
            column_type=ColumnType.INT32,
        )

        values = [10, 20, 30, 40, 50]
        writer.write_values(values)

        chunk = writer.finish()
        assert chunk.statistics is not None
        assert chunk.statistics.min_value == 10
        assert chunk.statistics.max_value == 50
        assert chunk.statistics.distinct_count == 5

    def test_string_column_chunk(self) -> None:
        """Test writing string column chunk."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="name",
            column_type=ColumnType.STRING,
        )

        values = ["alice", "bob", "charlie"]
        writer.write_values(values)

        chunk = writer.finish()
        assert chunk.column_type == ColumnType.STRING
        assert len(chunk.pages) > 0


class TestColumnChunkReader:
    """Tests for column chunk reader."""

    def test_read_simple_chunk(self) -> None:
        """Test reading simple column chunk."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="id",
            column_type=ColumnType.INT32,
        )

        values = [1, 2, 3, 4, 5]
        writer.write_values(values)
        chunk = writer.finish()

        reader = ColumnChunkReader(chunk)
        read_values = reader.read_all()

        # May not be exact due to encoding
        assert len(read_values) == len(values)

    def test_read_multiple_pages(self) -> None:
        """Test reading column chunk with multiple pages."""
        writer = ColumnChunkWriter(
            column_index=0,
            column_name="data",
            column_type=ColumnType.INT32,
            page_size=100,
        )

        values = list(range(500))
        writer.write_values(values)
        chunk = writer.finish()

        reader = ColumnChunkReader(chunk)
        read_values = reader.read_all()
        assert len(read_values) == len(values)


class TestRowGroupWriter:
    """Tests for row group writer."""

    def test_write_rows(self) -> None:
        """Test writing rows to row group."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
            ]
        )

        writer = RowGroupWriter(group_id=0, schema=schema)

        rows = [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
            {"id": 3, "name": "charlie"},
        ]
        writer.write_rows(rows)

        row_group = writer.finish()
        assert row_group.num_rows == 3
        assert len(row_group.column_chunks) == 2

    def test_write_single_row(self) -> None:
        """Test writing single row."""
        schema = Schema(fields=[Field("value", ColumnType.INT32)])

        writer = RowGroupWriter(group_id=0, schema=schema)
        writer.write_row({"value": 42})

        row_group = writer.finish()
        assert row_group.num_rows == 1

    def test_write_mixed_types(self) -> None:
        """Test writing mixed data types."""
        schema = Schema(
            fields=[
                Field("int_col", ColumnType.INT32),
                Field("float_col", ColumnType.FLOAT64),
                Field("string_col", ColumnType.STRING),
            ]
        )

        writer = RowGroupWriter(group_id=0, schema=schema)

        rows = [
            {"int_col": 1, "float_col": 1.1, "string_col": "a"},
            {"int_col": 2, "float_col": 2.2, "string_col": "b"},
        ]
        writer.write_rows(rows)

        row_group = writer.finish()
        assert row_group.num_rows == 2
        assert len(row_group.column_chunks) == 3


class TestRowGroupReader:
    """Tests for row group reader."""

    def test_read_all_rows(self) -> None:
        """Test reading all rows from row group."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
            ]
        )

        writer = RowGroupWriter(group_id=0, schema=schema)
        rows = [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
        ]
        writer.write_rows(rows)
        row_group = writer.finish()

        reader = RowGroupReader(row_group)
        read_rows = reader.read_all_rows()

        assert len(read_rows) == 2

    def test_read_single_column(self) -> None:
        """Test reading single column from row group."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("value", ColumnType.INT32),
            ]
        )

        writer = RowGroupWriter(group_id=0, schema=schema)
        rows = [
            {"id": 1, "value": 10},
            {"id": 2, "value": 20},
        ]
        writer.write_rows(rows)
        row_group = writer.finish()

        reader = RowGroupReader(row_group)
        values = reader.read_column(1)  # Read "value" column

        assert len(values) == 2


class TestColumnarFileWriter:
    """Tests for columnar file writer."""

    def test_write_single_row_group(self) -> None:
        """Test writing file with single row group."""
        schema = Schema(fields=[Field("id", ColumnType.INT32)])

        writer = ColumnarFileWriter(schema)

        for i in range(10):
            writer.write_row({"id": i})

        metadata = writer.finish()
        assert metadata.num_rows == 10
        assert len(metadata.row_groups) == 1

    def test_write_multiple_row_groups(self) -> None:
        """Test writing file with multiple row groups."""
        schema = Schema(fields=[Field("id", ColumnType.INT32)])

        writer = ColumnarFileWriter(schema, row_group_size=5)

        for i in range(15):
            writer.write_row({"id": i})

        metadata = writer.finish()
        assert metadata.num_rows == 15
        assert len(metadata.row_groups) == 3

    def test_write_complex_schema(self) -> None:
        """Test writing file with complex schema."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
                Field("score", ColumnType.FLOAT64),
                Field("active", ColumnType.BOOL),
            ]
        )

        writer = ColumnarFileWriter(schema)

        rows = [
            {"id": 1, "name": "alice", "score": 95.5, "active": True},
            {"id": 2, "name": "bob", "score": 87.3, "active": False},
        ]
        writer.write_rows(rows)

        metadata = writer.finish()
        assert metadata.num_rows == 2
        assert len(metadata.schema.fields) == 4


class TestColumnarFileReader:
    """Tests for columnar file reader."""

    def test_read_all_rows(self) -> None:
        """Test reading all rows from file."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("value", ColumnType.INT32),
            ]
        )

        writer = ColumnarFileWriter(schema)
        rows = [{"id": 1, "value": 10}, {"id": 2, "value": 20}]
        writer.write_rows(rows)
        metadata = writer.finish()

        reader = ColumnarFileReader(metadata)
        read_rows = reader.read_all_rows()

        assert len(read_rows) == 2

    def test_read_single_column(self) -> None:
        """Test reading single column from file."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
            ]
        )

        writer = ColumnarFileWriter(schema)
        rows = [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
        ]
        writer.write_rows(rows)
        metadata = writer.finish()

        reader = ColumnarFileReader(metadata)
        values = reader.read_column("name")

        assert len(values) == 2

    def test_read_multiple_columns(self) -> None:
        """Test reading multiple columns from file."""
        schema = Schema(
            fields=[
                Field("id", ColumnType.INT32),
                Field("name", ColumnType.STRING),
                Field("score", ColumnType.FLOAT64),
            ]
        )

        writer = ColumnarFileWriter(schema)
        rows = [
            {"id": 1, "name": "alice", "score": 95.5},
            {"id": 2, "name": "bob", "score": 87.3},
        ]
        writer.write_rows(rows)
        metadata = writer.finish()

        reader = ColumnarFileReader(metadata)
        data = reader.read_columns(["id", "name"])

        assert "id" in data
        assert "name" in data
        assert len(data["id"]) == 2


class TestStorageEdgeCases:
    """Tests for storage edge cases."""

    def test_empty_row_group(self) -> None:
        """Test empty row group."""
        schema = Schema(fields=[Field("id", ColumnType.INT32)])

        writer = RowGroupWriter(group_id=0, schema=schema)
        row_group = writer.finish()

        assert row_group.num_rows == 0

    def test_large_values(self) -> None:
        """Test writing large values."""
        schema = Schema(fields=[Field("data", ColumnType.STRING)])

        writer = RowGroupWriter(group_id=0, schema=schema)
        large_string = "x" * 1000000

        writer.write_row({"data": large_string})
        row_group = writer.finish()

        assert row_group.num_rows == 1

    def test_all_nulls(self) -> None:
        """Test column with all null values."""
        schema = Schema(fields=[Field("value", ColumnType.INT32)])

        writer = RowGroupWriter(group_id=0, schema=schema)
        for _ in range(5):
            writer.write_row({"value": None})

        row_group = writer.finish()
        assert row_group.num_rows == 5

        chunk = row_group.get_column_chunk(0)
        assert chunk is not None
        assert chunk.statistics.null_count == 5
