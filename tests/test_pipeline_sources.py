"""
Tests for data sources.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, "/sessions/zen-pensive-cannon/mnt/Thomas")

from thomas.data_pipeline.sources import (
    APISource,
    CDCSource,
    CSVSource,
    DatabaseSource,
    FileWatcherSource,
    JSONSource,
    KafkaLikeTopicSource,
)


class TestCSVSource:
    """Test CSV source."""

    def test_csv_read(self):
        """Test reading CSV file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("id,name,age\n")
            f.write("1,Alice,30\n")
            f.write("2,Bob,25\n")
            f.flush()
            filepath = f.name

        try:
            source = CSVSource(filepath)
            records = source.read()

            assert len(records) == 2
            assert records[0].get("name") == "Alice"
            assert records[1].get("name") == "Bob"
        finally:
            Path(filepath).unlink()

    def test_csv_stream(self):
        """Test streaming CSV."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("id,value\n")
            f.write("1,100\n")
            f.write("2,200\n")
            f.flush()
            filepath = f.name

        try:
            source = CSVSource(filepath)
            records = list(source.stream())

            assert len(records) == 2
            assert records[0].get("value") == "100"
        finally:
            Path(filepath).unlink()

    def test_csv_schema_inference(self):
        """Test schema inference."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
            f.flush()
            filepath = f.name

        try:
            source = CSVSource(filepath)
            schema = source.get_schema()

            assert len(schema.fields) == 2
            assert schema.fields[0].name == "col1"
            assert schema.fields[1].name == "col2"
        finally:
            Path(filepath).unlink()


class TestJSONSource:
    """Test JSON source."""

    def test_json_line_delimited(self):
        """Test reading line-delimited JSON."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"id": 1, "name": "Alice"}\n')
            f.write('{"id": 2, "name": "Bob"}\n')
            f.flush()
            filepath = f.name

        try:
            source = JSONSource(filepath, is_array=False)
            records = source.read()

            assert len(records) == 2
            assert records[0].get("id") == 1
        finally:
            Path(filepath).unlink()

    def test_json_array(self):
        """Test reading JSON array."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            data = [{"id": 1, "value": "a"}, {"id": 2, "value": "b"}]
            json.dump(data, f)
            f.flush()
            filepath = f.name

        try:
            source = JSONSource(filepath, is_array=True)
            records = source.read()

            assert len(records) == 2
            assert records[0].get("id") == 1
        finally:
            Path(filepath).unlink()

    def test_json_schema_inference(self):
        """Test JSON schema inference."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"name": "Alice", "age": 30}\n')
            f.flush()
            filepath = f.name

        try:
            source = JSONSource(filepath)
            schema = source.get_schema()

            assert len(schema.fields) == 2
            field_names = [f.name for f in schema.fields]
            assert "name" in field_names
            assert "age" in field_names
        finally:
            Path(filepath).unlink()


class TestDatabaseSource:
    """Test database source."""

    def test_database_read(self):
        """Test reading from database."""
        source = DatabaseSource("SELECT * FROM users", {})
        source.set_simulated_data(
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        )

        records = source.read()
        assert len(records) == 2
        assert records[0].get("id") == 1

    def test_database_stream(self):
        """Test streaming from database."""
        source = DatabaseSource("SELECT * FROM users", {}, batch_size=1)
        source.set_simulated_data(
            [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"},
            ]
        )

        records = list(source.stream())
        assert len(records) == 2

    def test_database_batching(self):
        """Test batch iteration."""
        source = DatabaseSource("SELECT * FROM users", {}, batch_size=2)
        data = [{"id": i, "name": f"User{i}"} for i in range(5)]
        source.set_simulated_data(data)

        batches = list(source._execute_query_batched())
        assert len(batches) == 3
        assert len(batches[0]) == 2
        assert len(batches[2]) == 1


class TestAPISource:
    """Test API source."""

    def test_api_read(self):
        """Test reading from API."""
        source = APISource("https://api.example.com", "/users")
        source.set_simulated_data(
            [
                [
                    {"id": 1, "name": "Alice"},
                    {"id": 2, "name": "Bob"},
                ],
                [
                    {"id": 3, "name": "Charlie"},
                ],
            ]
        )

        records = source.read()
        assert len(records) == 3
        assert records[0].get("name") == "Alice"

    def test_api_streaming(self):
        """Test streaming from API."""
        source = APISource("https://api.example.com", "/data")
        source.set_simulated_data(
            [
                [{"value": 1}, {"value": 2}],
                [{"value": 3}],
            ]
        )

        records = list(source.stream())
        assert len(records) == 3


class TestKafkaLikeSource:
    """Test Kafka-like topic source."""

    def test_topic_read(self):
        """Test reading from topic."""
        source = KafkaLikeTopicSource("my-topic")
        source.set_messages(
            [
                {"id": 1, "data": "a"},
                {"id": 2, "data": "b"},
            ]
        )

        records = source.read()
        assert len(records) == 2
        assert records[0].metadata["offset"] == 0

    def test_topic_offset_tracking(self):
        """Test offset tracking."""
        source = KafkaLikeTopicSource("my-topic", start_offset=1)
        source.set_messages(
            [
                {"id": 1, "data": "a"},
                {"id": 2, "data": "b"},
                {"id": 3, "data": "c"},
            ]
        )

        records = source.read()
        # Should only get messages from offset 1 onwards
        assert len(records) == 2
        assert source.get_current_offset() == 3


class TestCDCSource:
    """Test CDC source."""

    def test_cdc_read(self):
        """Test reading CDC changes."""
        source = CDCSource("users", capture_mode="change")
        source.set_changes(
            [
                {
                    "op": "INSERT",
                    "before": {},
                    "after": {"id": 1, "name": "Alice"},
                    "ts": datetime.utcnow().isoformat(),
                },
                {
                    "op": "UPDATE",
                    "before": {"id": 1, "name": "Alice"},
                    "after": {"id": 1, "name": "Alicia"},
                    "ts": datetime.utcnow().isoformat(),
                },
            ]
        )

        records = source.read()
        assert len(records) == 2
        assert records[0].get("op") == "INSERT"
        assert "after_name" in records[0].data

    def test_cdc_schema(self):
        """Test CDC schema inference."""
        source = CDCSource("users")
        source.set_changes(
            [
                {
                    "op": "INSERT",
                    "before": {},
                    "after": {"id": 1, "name": "Alice"},
                    "ts": datetime.utcnow().isoformat(),
                },
            ]
        )

        schema = source.get_schema()
        field_names = [f.name for f in schema.fields]
        assert "after_id" in field_names
        assert "after_name" in field_names
        assert "op" in field_names


class TestFileWatcherSource:
    """Test file watcher source."""

    def test_file_watcher(self):
        """Test watching directory for files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file
            csv_path = Path(tmpdir) / "data.csv"
            csv_path.write_text("id,value\n1,100\n")

            source = FileWatcherSource(tmpdir, "*.csv")
            records = source.read()

            assert len(records) == 1
            assert records[0].get("value") == "100"

    def test_file_watcher_multiple(self):
        """Test watching multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create files
            (tmpdir / "file1.csv").write_text("value\n1\n")
            (tmpdir / "file2.csv").write_text("value\n2\n")

            source = FileWatcherSource(tmpdir, "*.csv")
            records = source.read()

            assert len(records) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
