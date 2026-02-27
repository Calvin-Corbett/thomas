"""
Data sources for the pipeline framework.

Implements various data sources including CSV, JSON, database, API,
file watchers, Kafka-like topics, and CDC sources.
"""

import csv
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.data_pipeline._exceptions import SourceError
from thomas.data_pipeline._types import (
    DataSource,
    DataType,
    Field,
    Record,
    Schema,
)


class CSVSource(DataSource):
    """
    Reads data from CSV files.

    Supports configurable delimiters, quoting, and header handling.
    Can read single file or stream from directory.
    """

    def __init__(
        self,
        filepath: str | Path,
        delimiter: str = ",",
        quotechar: str = '"',
        has_header: bool = True,
        encoding: str = "utf-8",
        infer_schema: bool = True,
    ) -> None:
        """
        Initialize CSV source.

        Args:
            filepath: Path to CSV file
            delimiter: Field delimiter
            quotechar: Quote character
            has_header: Whether first row is header
            encoding: File encoding
            infer_schema: Whether to infer schema from data
        """
        self.filepath = Path(filepath)
        self.delimiter = delimiter
        self.quotechar = quotechar
        self.has_header = has_header
        self.encoding = encoding
        self.infer_schema = infer_schema
        self._schema: Schema | None = None

    def read(self) -> list[Record]:
        """Read all records from CSV file."""
        records = []
        try:
            with open(self.filepath, encoding=self.encoding) as f:
                reader = csv.DictReader(
                    f,
                    delimiter=self.delimiter,
                    quotechar=self.quotechar,
                )
                for row in reader:
                    record = Record(data=dict(row))
                    records.append(record)
        except OSError as e:
            raise SourceError(f"Failed to read CSV file {self.filepath}: {e}", "CSVSource")
        except Exception as e:
            raise SourceError(f"CSV parsing error: {e}", "CSVSource")

        return records

    def stream(self) -> Iterator[Record]:
        """Stream records from CSV file."""
        try:
            with open(self.filepath, encoding=self.encoding) as f:
                reader = csv.DictReader(
                    f,
                    delimiter=self.delimiter,
                    quotechar=self.quotechar,
                )
                for row in reader:
                    yield Record(data=dict(row))
        except OSError as e:
            raise SourceError(f"Failed to read CSV file {self.filepath}: {e}", "CSVSource")
        except Exception as e:
            raise SourceError(f"CSV parsing error: {e}", "CSVSource")

    def get_schema(self) -> Schema:
        """Infer and return schema from CSV file."""
        if self._schema is not None:
            return self._schema

        if not self.infer_schema:
            raise SourceError("Schema inference disabled", "CSVSource")

        fields = []
        try:
            with open(self.filepath, encoding=self.encoding) as f:
                reader = csv.DictReader(
                    f,
                    delimiter=self.delimiter,
                    quotechar=self.quotechar,
                )
                if reader.fieldnames:
                    for fieldname in reader.fieldnames:
                        fields.append(Field(name=fieldname, data_type=DataType.STRING))

        except Exception as e:
            raise SourceError(f"Failed to infer schema: {e}", "CSVSource")

        self._schema = Schema(fields=fields)
        return self._schema

    def supports_streaming(self) -> bool:
        """CSV source supports streaming."""
        return True


class JSONSource(DataSource):
    """
    Reads data from JSON files.

    Supports both line-delimited JSON and JSON arrays.
    """

    def __init__(
        self,
        filepath: str | Path,
        is_array: bool = False,
        encoding: str = "utf-8",
    ) -> None:
        """
        Initialize JSON source.

        Args:
            filepath: Path to JSON file
            is_array: Whether file contains JSON array (vs line-delimited)
            encoding: File encoding
        """
        self.filepath = Path(filepath)
        self.is_array = is_array
        self.encoding = encoding
        self._schema: Schema | None = None

    def read(self) -> list[Record]:
        """Read all records from JSON file."""
        records = []
        try:
            with open(self.filepath, encoding=self.encoding) as f:
                if self.is_array:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            record = Record(data=item if isinstance(item, dict) else {"value": item})
                            records.append(record)
                    else:
                        raise SourceError("Expected JSON array", "JSONSource")
                else:
                    for line in f:
                        if line.strip():
                            item = json.loads(line)
                            record = Record(data=item if isinstance(item, dict) else {"value": item})
                            records.append(record)
        except OSError as e:
            raise SourceError(f"Failed to read JSON file {self.filepath}: {e}", "JSONSource")
        except json.JSONDecodeError as e:
            raise SourceError(f"JSON parsing error: {e}", "JSONSource")

        return records

    def stream(self) -> Iterator[Record]:
        """Stream records from JSON file."""
        try:
            with open(self.filepath, encoding=self.encoding) as f:
                if self.is_array:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            yield Record(data=item if isinstance(item, dict) else {"value": item})
                else:
                    for line in f:
                        if line.strip():
                            item = json.loads(line)
                            yield Record(data=item if isinstance(item, dict) else {"value": item})
        except OSError as e:
            raise SourceError(f"Failed to read JSON file {self.filepath}: {e}", "JSONSource")
        except json.JSONDecodeError as e:
            raise SourceError(f"JSON parsing error: {e}", "JSONSource")

    def get_schema(self) -> Schema:
        """Infer schema from JSON data."""
        if self._schema is not None:
            return self._schema

        fields = []
        sample_record = None

        try:
            with open(self.filepath, encoding=self.encoding) as f:
                if self.is_array:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        sample_record = data[0]
                else:
                    line = f.readline()
                    if line.strip():
                        sample_record = json.loads(line)

            if sample_record and isinstance(sample_record, dict):
                for key in sample_record.keys():
                    value = sample_record[key]
                    data_type = self._infer_type(value)
                    fields.append(Field(name=key, data_type=data_type))

        except Exception as e:
            raise SourceError(f"Failed to infer schema: {e}", "JSONSource")

        self._schema = Schema(fields=fields)
        return self._schema

    @staticmethod
    def _infer_type(value: Any) -> DataType:
        """Infer DataType from Python value."""
        if value is None:
            return DataType.NULL
        elif isinstance(value, bool):
            return DataType.BOOLEAN
        elif isinstance(value, int):
            return DataType.INTEGER
        elif isinstance(value, float):
            return DataType.FLOAT
        elif isinstance(value, str):
            return DataType.STRING
        elif isinstance(value, list):
            return DataType.ARRAY
        elif isinstance(value, dict):
            return DataType.STRUCT
        else:
            return DataType.ANY

    def supports_streaming(self) -> bool:
        """JSON source supports streaming."""
        return True


class DatabaseSource(DataSource):
    """
    Reads data from a database.

    Simulates SQL query result iteration with configurable batch sizes.
    """

    def __init__(
        self,
        query: str,
        connection_params: dict[str, Any],
        batch_size: int = 1000,
    ) -> None:
        """
        Initialize database source.

        Args:
            query: SQL query to execute
            connection_params: Database connection parameters
            batch_size: Number of records to fetch per batch
        """
        self.query = query
        self.connection_params = connection_params
        self.batch_size = batch_size
        self._schema: Schema | None = None
        self._simulated_data: list[dict[str, Any]] = []

    def set_simulated_data(self, data: list[dict[str, Any]]) -> None:
        """Set simulated database results for testing."""
        self._simulated_data = data

    def read(self) -> list[Record]:
        """Read all records from database query."""
        records = []
        try:
            for batch in self._execute_query_batched():
                for row in batch:
                    record = Record(data=row)
                    records.append(record)
        except Exception as e:
            raise SourceError(f"Database query failed: {e}", "DatabaseSource")

        return records

    def stream(self) -> Iterator[Record]:
        """Stream records from database query."""
        try:
            for batch in self._execute_query_batched():
                for row in batch:
                    yield Record(data=row)
        except Exception as e:
            raise SourceError(f"Database query failed: {e}", "DatabaseSource")

    def _execute_query_batched(self) -> Iterator[list[dict[str, Any]]]:
        """Execute query and yield batches of results."""
        # Simulated implementation
        for i in range(0, len(self._simulated_data), self.batch_size):
            yield self._simulated_data[i : i + self.batch_size]

    def get_schema(self) -> Schema:
        """Get schema from query result."""
        if self._schema is not None:
            return self._schema

        fields = []
        if self._simulated_data and len(self._simulated_data) > 0:
            sample = self._simulated_data[0]
            for key, value in sample.items():
                data_type = self._infer_type(value)
                fields.append(Field(name=key, data_type=data_type))

        self._schema = Schema(fields=fields)
        return self._schema

    @staticmethod
    def _infer_type(value: Any) -> DataType:
        """Infer DataType from Python value."""
        if value is None:
            return DataType.NULL
        elif isinstance(value, bool):
            return DataType.BOOLEAN
        elif isinstance(value, int):
            return DataType.INTEGER
        elif isinstance(value, float):
            return DataType.FLOAT
        elif isinstance(value, str):
            return DataType.STRING
        else:
            return DataType.ANY

    def supports_streaming(self) -> bool:
        """Database source supports streaming."""
        return True


class APISource(DataSource):
    """
    Reads data from a REST API with pagination.

    Simulates paginated API responses.
    """

    def __init__(
        self,
        base_url: str,
        endpoint: str,
        page_param: str = "page",
        page_size_param: str = "limit",
        page_size: int = 100,
        auth_params: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize API source.

        Args:
            base_url: Base URL of API
            endpoint: API endpoint path
            page_param: Query parameter name for page
            page_size_param: Query parameter name for page size
            page_size: Records per page
            auth_params: Authentication parameters
        """
        self.base_url = base_url
        self.endpoint = endpoint
        self.page_param = page_param
        self.page_size_param = page_size_param
        self.page_size = page_size
        self.auth_params = auth_params or {}
        self._schema: Schema | None = None
        self._simulated_pages: list[list[dict[str, Any]]] = []

    def set_simulated_data(self, pages: list[list[dict[str, Any]]]) -> None:
        """Set simulated API responses for testing."""
        self._simulated_pages = pages

    def read(self) -> list[Record]:
        """Read all records from API."""
        records = []
        try:
            for page_data in self._fetch_all_pages():
                for row in page_data:
                    record = Record(data=row)
                    records.append(record)
        except Exception as e:
            raise SourceError(f"API fetch failed: {e}", "APISource")

        return records

    def stream(self) -> Iterator[Record]:
        """Stream records from API."""
        try:
            for page_data in self._fetch_all_pages():
                for row in page_data:
                    yield Record(data=row)
        except Exception as e:
            raise SourceError(f"API fetch failed: {e}", "APISource")

    def _fetch_all_pages(self) -> Iterator[list[dict[str, Any]]]:
        """Fetch all pages from API."""
        # Simulated implementation
        for page in self._simulated_pages:
            yield page

    def get_schema(self) -> Schema:
        """Get schema from API response."""
        if self._schema is not None:
            return self._schema

        fields = []
        if self._simulated_pages and len(self._simulated_pages) > 0:
            first_page = self._simulated_pages[0]
            if len(first_page) > 0:
                sample = first_page[0]
                for key, value in sample.items():
                    data_type = self._infer_type(value)
                    fields.append(Field(name=key, data_type=data_type))

        self._schema = Schema(fields=fields)
        return self._schema

    @staticmethod
    def _infer_type(value: Any) -> DataType:
        """Infer DataType from Python value."""
        if value is None:
            return DataType.NULL
        elif isinstance(value, bool):
            return DataType.BOOLEAN
        elif isinstance(value, int):
            return DataType.INTEGER
        elif isinstance(value, float):
            return DataType.FLOAT
        elif isinstance(value, str):
            return DataType.STRING
        else:
            return DataType.ANY

    def supports_streaming(self) -> bool:
        """API source supports streaming."""
        return True


class FileWatcherSource(DataSource):
    """
    Watches a directory for new files and reads them.

    Detects new files and processes them as they appear.
    """

    def __init__(
        self,
        directory: str | Path,
        file_pattern: str = "*.csv",
        reader_source: DataSource | None = None,
    ) -> None:
        """
        Initialize file watcher source.

        Args:
            directory: Directory to watch
            file_pattern: Glob pattern for files to watch
            reader_source: Source type to use for reading files
        """
        self.directory = Path(directory)
        self.file_pattern = file_pattern
        self.reader_source = reader_source
        self._processed_files: set = set()
        self._schema: Schema | None = None

    def read(self) -> list[Record]:
        """Read all available files."""
        records = []
        for filepath in self.directory.glob(self.file_pattern):
            if str(filepath) not in self._processed_files:
                try:
                    source = self.reader_source or CSVSource(filepath)
                    records.extend(source.read())
                    self._processed_files.add(str(filepath))
                except Exception as e:
                    raise SourceError(f"Failed to read file {filepath}: {e}", "FileWatcherSource")

        return records

    def stream(self) -> Iterator[Record]:
        """Stream records from new files."""
        for filepath in self.directory.glob(self.file_pattern):
            if str(filepath) not in self._processed_files:
                try:
                    source = self.reader_source or CSVSource(filepath)
                    for record in source.stream():
                        yield record
                    self._processed_files.add(str(filepath))
                except Exception as e:
                    raise SourceError(f"Failed to read file {filepath}: {e}", "FileWatcherSource")

    def get_schema(self) -> Schema:
        """Get schema from first available file."""
        if self._schema is not None:
            return self._schema

        for filepath in self.directory.glob(self.file_pattern):
            try:
                source = self.reader_source or CSVSource(filepath)
                self._schema = source.get_schema()
                return self._schema
            except Exception:
                continue

        raise SourceError("No files found to infer schema", "FileWatcherSource")

    def supports_streaming(self) -> bool:
        """File watcher supports streaming."""
        return True


class KafkaLikeTopicSource(DataSource):
    """
    Simulates a Kafka-like topic consumer.

    Reads messages from a simulated topic with offset tracking.
    """

    def __init__(
        self,
        topic: str,
        partition: int = 0,
        start_offset: int = 0,
    ) -> None:
        """
        Initialize Kafka-like source.

        Args:
            topic: Topic name
            partition: Partition number
            start_offset: Starting offset to read from
        """
        self.topic = topic
        self.partition = partition
        self.start_offset = start_offset
        self._messages: list[tuple[int, dict[str, Any]]] = []
        self._schema: Schema | None = None
        self._current_offset = start_offset

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        """Set simulated topic messages for testing."""
        self._messages = [(i, msg) for i, msg in enumerate(messages)]

    def read(self) -> list[Record]:
        """Read all messages from topic."""
        records = []
        for offset, message in self._messages:
            if offset >= self.start_offset:
                record = Record(data=message, metadata={"offset": offset, "partition": self.partition})
                records.append(record)
                self._current_offset = offset + 1

        return records

    def stream(self) -> Iterator[Record]:
        """Stream messages from topic."""
        for offset, message in self._messages:
            if offset >= self._current_offset:
                record = Record(data=message, metadata={"offset": offset, "partition": self.partition})
                yield record
                self._current_offset = offset + 1

    def get_schema(self) -> Schema:
        """Get schema from topic messages."""
        if self._schema is not None:
            return self._schema

        fields = []
        if self._messages and len(self._messages) > 0:
            _, sample = self._messages[0]
            for key, value in sample.items():
                data_type = self._infer_type(value)
                fields.append(Field(name=key, data_type=data_type))

        self._schema = Schema(fields=fields)
        return self._schema

    def get_current_offset(self) -> int:
        """Get current consumer offset."""
        return self._current_offset

    @staticmethod
    def _infer_type(value: Any) -> DataType:
        """Infer DataType from Python value."""
        if value is None:
            return DataType.NULL
        elif isinstance(value, bool):
            return DataType.BOOLEAN
        elif isinstance(value, int):
            return DataType.INTEGER
        elif isinstance(value, float):
            return DataType.FLOAT
        elif isinstance(value, str):
            return DataType.STRING
        else:
            return DataType.ANY

    def supports_streaming(self) -> bool:
        """Kafka-like source supports streaming."""
        return True


class CDCSource(DataSource):
    """
    Change Data Capture (CDC) source.

    Tracks before/after images of changed records.
    """

    def __init__(
        self,
        table_name: str,
        capture_mode: str = "change",  # "change", "before", "after"
    ) -> None:
        """
        Initialize CDC source.

        Args:
            table_name: Source table name
            capture_mode: What to capture (change, before, after)
        """
        self.table_name = table_name
        self.capture_mode = capture_mode
        self._changes: list[dict[str, Any]] = []
        self._schema: Schema | None = None

    def set_changes(self, changes: list[dict[str, Any]]) -> None:
        """Set simulated CDC changes for testing."""
        self._changes = changes

    def read(self) -> list[Record]:
        """Read all captured changes."""
        records = []
        for change in self._changes:
            record = self._create_cdc_record(change)
            records.append(record)

        return records

    def stream(self) -> Iterator[Record]:
        """Stream captured changes."""
        for change in self._changes:
            yield self._create_cdc_record(change)

    def _create_cdc_record(self, change: dict[str, Any]) -> Record:
        """Create a CDC record from change data."""
        data = {}

        if self.capture_mode in ("change", "before"):
            if "before" in change:
                for key, value in change["before"].items():
                    data[f"before_{key}"] = value

        if self.capture_mode in ("change", "after"):
            if "after" in change:
                for key, value in change["after"].items():
                    data[f"after_{key}"] = value

        data["op"] = change.get("op", "UNKNOWN")  # INSERT, UPDATE, DELETE
        data["ts"] = change.get("ts", datetime.utcnow().isoformat())

        return Record(data=data, metadata={"table": self.table_name})

    def get_schema(self) -> Schema:
        """Get schema from CDC changes."""
        if self._schema is not None:
            return self._schema

        fields = []
        if self._changes and len(self._changes) > 0:
            sample = self._changes[0]
            seen_fields = set()

            for key in ["before", "after"]:
                if key in sample:
                    for col_name in sample[key].keys():
                        field_name = f"{key}_{col_name}"
                        if field_name not in seen_fields:
                            fields.append(Field(name=field_name, data_type=DataType.ANY))
                            seen_fields.add(field_name)

            fields.append(Field(name="op", data_type=DataType.STRING))
            fields.append(Field(name="ts", data_type=DataType.TIMESTAMP))

        self._schema = Schema(fields=fields)
        return self._schema

    def supports_streaming(self) -> bool:
        """CDC source supports streaming."""
        return True
