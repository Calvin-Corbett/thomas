"""
Data sinks for the pipeline framework.

Implements various data sinks including CSV, JSON, database, file partitioning,
console output, and multi-sink fan-out.
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.data_pipeline._exceptions import SinkError
from thomas.data_pipeline._types import (
    DataSink,
    Record,
)


class CSVSink(DataSink):
    """
    Writes data to CSV files.

    Supports configurable delimiters, quoting, and header handling.
    """

    def __init__(
        self,
        filepath: str | Path,
        delimiter: str = ",",
        quotechar: str = '"',
        write_header: bool = True,
        encoding: str = "utf-8",
        mode: str = "w",  # "w" for write, "a" for append
    ) -> None:
        """
        Initialize CSV sink.

        Args:
            filepath: Path to output CSV file
            delimiter: Field delimiter
            quotechar: Quote character
            write_header: Whether to write header row
            encoding: File encoding
            mode: File open mode
        """
        self.filepath = Path(filepath)
        self.delimiter = delimiter
        self.quotechar = quotechar
        self.write_header = write_header
        self.encoding = encoding
        self.mode = mode
        self._file = None
        self._writer = None
        self._fieldnames: list[str] | None = None
        self._header_written = False
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Write a single record to CSV."""
        try:
            if self._file is None:
                self._open_file()

            if self._fieldnames is None:
                self._fieldnames = list(record.data.keys())

            if self.write_header and not self._header_written:
                self._writer.writerow(self._fieldnames)
                self._header_written = True

            values = [str(record.get(fn, "")) for fn in self._fieldnames]
            self._writer.writerow(values)
            self._record_count += 1

        except Exception as e:
            raise SinkError(f"Failed to write CSV: {e}", "CSVSink")

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to CSV."""
        for record in records:
            self.write(record)

    def _open_file(self) -> None:
        """Open file for writing."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.filepath, self.mode, newline="", encoding=self.encoding)
        self._writer = csv.writer(
            self._file,
            delimiter=self.delimiter,
            quotechar=self.quotechar,
        )

    def flush(self) -> None:
        """Flush buffered data."""
        if self._file:
            self._file.flush()

    def close(self) -> None:
        """Close the sink."""
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None

    def __del__(self) -> None:
        """Ensure file is closed."""
        self.close()


class JSONSink(DataSink):
    """
    Writes data to JSON files.

    Supports both line-delimited JSON and JSON array output.
    """

    def __init__(
        self,
        filepath: str | Path,
        as_array: bool = False,
        pretty: bool = False,
        encoding: str = "utf-8",
    ) -> None:
        """
        Initialize JSON sink.

        Args:
            filepath: Path to output JSON file
            as_array: Whether to write JSON array (vs line-delimited)
            pretty: Pretty-print JSON
            encoding: File encoding
        """
        self.filepath = Path(filepath)
        self.as_array = as_array
        self.pretty = pretty
        self.encoding = encoding
        self._file = None
        self._records: list[dict[str, Any]] = []
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Write a single record to JSON."""
        try:
            if self.as_array:
                self._records.append(record.to_dict())
            else:
                if self._file is None:
                    self._open_file()
                self._write_line(record.to_dict())
            self._record_count += 1
        except Exception as e:
            raise SinkError(f"Failed to write JSON: {e}", "JSONSink")

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to JSON."""
        for record in records:
            self.write(record)

    def _open_file(self) -> None:
        """Open file for writing."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.filepath, "w", encoding=self.encoding)

    def _write_line(self, data: dict[str, Any]) -> None:
        """Write a single line of JSON."""
        if self._file:
            json_str = json.dumps(data, separators=(",", ":"))
            self._file.write(json_str + "\n")

    def flush(self) -> None:
        """Flush buffered data."""
        if self.as_array and self._records:
            self._open_file()
            indent = 2 if self.pretty else None
            json.dump(self._records, self._file, indent=indent)
        elif self._file:
            self._file.flush()

    def close(self) -> None:
        """Close the sink."""
        self.flush()
        if self._file:
            self._file.close()
            self._file = None

    def __del__(self) -> None:
        """Ensure file is closed."""
        self.close()


class DatabaseSink(DataSink):
    """
    Writes data to a database.

    Simulates SQL INSERT operations with configurable batch sizes.
    """

    def __init__(
        self,
        table_name: str,
        connection_params: dict[str, Any],
        batch_size: int = 1000,
    ) -> None:
        """
        Initialize database sink.

        Args:
            table_name: Target table name
            connection_params: Database connection parameters
            batch_size: Insert batch size
        """
        self.table_name = table_name
        self.connection_params = connection_params
        self.batch_size = batch_size
        self._buffer: list[Record] = []
        self._record_count = 0
        self._simulated_writes: list[list[dict[str, Any]]] = []

    def write(self, record: Record) -> None:
        """Write a single record to database."""
        self._buffer.append(record)
        self._record_count += 1

        if len(self._buffer) >= self.batch_size:
            self._flush_buffer()

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to database."""
        for record in records:
            self.write(record)

    def _flush_buffer(self) -> None:
        """Flush buffered records to database."""
        if not self._buffer:
            return

        try:
            data = [r.to_dict() for r in self._buffer]
            self._simulated_writes.append(data)
            self._buffer = []
        except Exception as e:
            raise SinkError(f"Failed to insert to database: {e}", "DatabaseSink")

    def flush(self) -> None:
        """Flush any remaining buffered data."""
        self._flush_buffer()

    def close(self) -> None:
        """Close the sink."""
        self.flush()

    def get_simulated_writes(self) -> list[list[dict[str, Any]]]:
        """Get simulated database writes for testing."""
        return self._simulated_writes


class FilePartitionedSink(DataSink):
    """
    Writes data to date-partitioned directories.

    Partitions files by date, allowing organized output.
    """

    def __init__(
        self,
        base_directory: str | Path,
        partition_format: str = "%Y/%m/%d",
        timestamp_field: str = "timestamp",
        file_extension: str = ".json",
    ) -> None:
        """
        Initialize partitioned sink.

        Args:
            base_directory: Base directory for partitioned output
            partition_format: strftime format for directory structure
            timestamp_field: Field to use for partitioning
            file_extension: File extension for output files
        """
        self.base_directory = Path(base_directory)
        self.partition_format = partition_format
        self.timestamp_field = timestamp_field
        self.file_extension = file_extension
        self._open_files: dict[str, Any] = {}
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Write a single record to partitioned directory."""
        try:
            partition_path = self._get_partition_path(record)
            sink = self._get_or_create_sink(partition_path)
            sink.write(record)
            self._record_count += 1
        except Exception as e:
            raise SinkError(f"Failed to write to partitioned sink: {e}", "FilePartitionedSink")

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to partitioned directories."""
        for record in records:
            self.write(record)

    def _get_partition_path(self, record: Record) -> str:
        """Get partition path for a record."""
        if self.timestamp_field in record.data:
            ts_value = record.data[self.timestamp_field]
            if isinstance(ts_value, datetime):
                return ts_value.strftime(self.partition_format)

        return datetime.utcnow().strftime(self.partition_format)

    def _get_or_create_sink(self, partition: str) -> DataSink:
        """Get or create sink for partition."""
        if partition not in self._open_files:
            file_path = self.base_directory / partition / f"data{self.file_extension}"
            file_path.parent.mkdir(parents=True, exist_ok=True)

            if self.file_extension == ".json":
                sink = JSONSink(file_path, as_array=False)
            elif self.file_extension == ".csv":
                sink = CSVSink(file_path)
            else:
                raise SinkError(f"Unsupported file extension: {self.file_extension}", "FilePartitionedSink")

            self._open_files[partition] = sink

        return self._open_files[partition]

    def flush(self) -> None:
        """Flush all open sinks."""
        for sink in self._open_files.values():
            sink.flush()

    def close(self) -> None:
        """Close all open sinks."""
        for sink in self._open_files.values():
            sink.close()
        self._open_files = {}

    def __del__(self) -> None:
        """Ensure all sinks are closed."""
        self.close()


class ConsoleSink(DataSink):
    """
    Writes data to console with pretty formatting.

    Useful for debugging and monitoring.
    """

    def __init__(
        self,
        max_width: int = 100,
        format_type: str = "table",  # "table", "json", "csv"
    ) -> None:
        """
        Initialize console sink.

        Args:
            max_width: Maximum line width
            format_type: Output format
        """
        self.max_width = max_width
        self.format_type = format_type
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Write a single record to console."""
        self._format_and_print(record)
        self._record_count += 1

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records to console."""
        for record in records:
            self.write(record)

    def _format_and_print(self, record: Record) -> None:
        """Format and print a record."""
        if self.format_type == "json":
            print(json.dumps(record.to_dict(), indent=2))
        elif self.format_type == "csv":
            print(",".join(str(v) for v in record.data.values()))
        else:  # table
            self._print_table_row(record)

    def _print_table_row(self, record: Record) -> None:
        """Print record as table row."""
        parts = []
        for k, v in record.data.items():
            val_str = str(v)
            if len(val_str) > 30:
                val_str = val_str[:27] + "..."
            parts.append(f"{k}={val_str}")

        line = " | ".join(parts)
        if len(line) > self.max_width:
            print(line[: self.max_width] + "...")
        else:
            print(line)

    def flush(self) -> None:
        """Flush console output."""
        pass

    def close(self) -> None:
        """Close the sink."""
        pass


class NullSink(DataSink):
    """
    Discards all data. Useful for testing.

    Counts records but doesn't write them anywhere.
    """

    def __init__(self) -> None:
        """Initialize null sink."""
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Discard a single record."""
        self._record_count += 1

    def write_batch(self, records: list[Record]) -> None:
        """Discard multiple records."""
        self._record_count += len(records)

    def flush(self) -> None:
        """Flush (no-op)."""
        pass

    def close(self) -> None:
        """Close (no-op)."""
        pass

    def get_record_count(self) -> int:
        """Get count of records processed."""
        return self._record_count


class MultiSink(DataSink):
    """
    Fan-out to multiple sinks simultaneously.

    Writes to multiple destinations in parallel.
    """

    def __init__(self, sinks: list[DataSink]) -> None:
        """
        Initialize multi-sink.

        Args:
            sinks: List of sinks to write to
        """
        self.sinks = sinks
        self._record_count = 0

    def write(self, record: Record) -> None:
        """Write record to all sinks."""
        for sink in self.sinks:
            try:
                sink.write(record)
            except Exception as e:
                raise SinkError(f"MultiSink write failed: {e}", "MultiSink")
        self._record_count += 1

    def write_batch(self, records: list[Record]) -> None:
        """Write records to all sinks."""
        for sink in self.sinks:
            try:
                sink.write_batch(records)
            except Exception as e:
                raise SinkError(f"MultiSink batch write failed: {e}", "MultiSink")
        self._record_count += len(records)

    def flush(self) -> None:
        """Flush all sinks."""
        for sink in self.sinks:
            sink.flush()

    def close(self) -> None:
        """Close all sinks."""
        for sink in self.sinks:
            sink.close()


class DeadLetterQueue(DataSink):
    """
    Captures failed records for error handling.

    Stores records that failed processing with error details.
    """

    def __init__(
        self,
        filepath: str | Path,
    ) -> None:
        """
        Initialize dead letter queue.

        Args:
            filepath: Path to store failed records
        """
        self.filepath = Path(filepath)
        self._sink = JSONSink(filepath, as_array=True, pretty=True)
        self._record_count = 0
        self._failed_records: list[dict[str, Any]] = []

    def write_failed_record(
        self,
        record: Record,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Write a failed record to DLQ."""
        dlq_record = {
            "original_data": record.to_dict(),
            "error": str(error),
            "error_type": type(error).__name__,
            "timestamp": datetime.utcnow().isoformat(),
            "context": context or {},
        }

        self._failed_records.append(dlq_record)
        self._record_count += 1

    def write(self, record: Record) -> None:
        """Write a single record (standard interface)."""
        self.write_failed_record(record, Exception("Unknown error"))

    def write_batch(self, records: list[Record]) -> None:
        """Write multiple records (standard interface)."""
        for record in records:
            self.write(record)

    def flush(self) -> None:
        """Flush failed records to file."""
        if self._failed_records:
            temp_record = Record(data={})
            for failed_record in self._failed_records:
                temp_record.data = failed_record
                self._sink.write(temp_record)
            self._sink.flush()

    def close(self) -> None:
        """Close the DLQ."""
        self.flush()
        self._sink.close()

    def get_failed_records(self) -> list[dict[str, Any]]:
        """Get list of failed records."""
        return self._failed_records

    def __del__(self) -> None:
        """Ensure file is closed."""
        self.close()
