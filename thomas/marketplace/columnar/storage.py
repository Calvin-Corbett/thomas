"""
Columnar storage layer: column chunks, row groups, and file format.

Manages column chunk layout, row group organization, and file metadata with
support for predicate pushdown and statistics-based query optimization.
"""

from datetime import datetime
from typing import Any

from thomas.marketplace.columnar import compression as comp_module
from thomas.marketplace.columnar import encoding as enc_module
from thomas.marketplace.columnar._exceptions import StorageError
from thomas.marketplace.columnar._types import (
    ColumnarFileMetadata,
    ColumnChunk,
    ColumnType,
    Compression,
    DataPage,
    DictionaryPage,
    Encoding,
    RowGroup,
    Schema,
    Statistics,
)


class ColumnChunkWriter:
    """Writer for column chunks with page management and statistics."""

    def __init__(
        self,
        column_index: int,
        column_name: str,
        column_type: ColumnType,
        encoding: Encoding = Encoding.PLAIN,
        compression: Compression = Compression.NONE,
        page_size: int = 65536,
    ) -> None:
        """Initialize column chunk writer.

        Args:
            column_index: Index of column in schema
            column_name: Name of column
            column_type: Data type of column
            encoding: Encoding scheme
            compression: Compression algorithm
            page_size: Target size for each page
        """
        self.column_index = column_index
        self.column_name = column_name
        self.column_type = column_type
        self.encoding = encoding
        self.compression = compression
        self.page_size = page_size

        self.pages: list[DataPage] = []
        self.dictionary_page: DictionaryPage | None = None
        self.statistics: Statistics | None = None
        self.current_page_values: list[Any] = []
        self.current_page_nulls: list[bool] = []
        self._distinct_values: set[Any] = set()

    def write_values(self, values: list[Any]) -> None:
        """Write values to column, creating pages as needed."""
        for value in values:
            self.current_page_values.append(value)
            self.current_page_nulls.append(value is None)

            # Flush page if it exceeds target size
            if self._estimate_page_size() >= self.page_size:
                self._flush_page()

        # Update statistics
        if self.statistics is None:
            self.statistics = Statistics()

        non_null = [v for v in values if v is not None]
        self.statistics.total_value_count += len(values)
        self.statistics.null_count += len(values) - len(non_null)

        if non_null:
            batch_min = min(non_null)
            batch_max = max(non_null)

            if self.statistics.min_value is None or batch_min < self.statistics.min_value:
                self.statistics.min_value = batch_min
            if self.statistics.max_value is None or batch_max > self.statistics.max_value:
                self.statistics.max_value = batch_max

            for value in non_null:
                try:
                    self._distinct_values.add(value)
                except TypeError:
                    # Skip unhashable values for distinct counting.
                    pass

            if self._distinct_values:
                self.statistics.distinct_count = len(self._distinct_values)

    def _estimate_page_size(self) -> int:
        """Estimate current page size in bytes."""
        if not self.current_page_values:
            return 0

        # Rough estimate based on type width
        byte_width = self.column_type.byte_width()
        if byte_width:
            return len(self.current_page_values) * byte_width

        # Variable-length estimate
        size = 0
        for v in self.current_page_values:
            if v is None:
                size += 1
            elif isinstance(v, str):
                size += len(v.encode("utf-8")) + 4
            elif isinstance(v, bytes):
                size += len(v) + 4
            else:
                size += 8

        return size

    def _flush_page(self) -> None:
        """Flush current page buffer to page list."""
        if not self.current_page_values:
            return

        # Encode values
        encoded_data = self._encode_values()

        # Compress data
        if self.compression != Compression.NONE:
            encoded_data = self._compress_data(encoded_data)

        # Create null bitmap
        null_bitmap = self._create_null_bitmap()

        # Create page
        page = DataPage(
            column_index=self.column_index,
            page_number=len(self.pages),
            encoding=self.encoding,
            compression=self.compression,
            data=encoded_data,
            null_bitmap=null_bitmap,
            statistics=Statistics(),
        )
        page.statistics.update(self.current_page_values)

        self.pages.append(page)
        self.current_page_values = []
        self.current_page_nulls = []

    def _encode_values(self) -> bytes:
        """Encode values using selected encoding."""
        if self.encoding == Encoding.DICTIONARY:
            data, dictionary = enc_module.encode_dictionary(self.current_page_values, self.column_type)
            self.dictionary_page = DictionaryPage(
                column_index=self.column_index,
                dictionary_values=dictionary,
            )
            return data
        elif self.encoding == Encoding.RLE:
            return enc_module.encode_rle(self.current_page_values, self.column_type)
        elif self.encoding == Encoding.DELTA:
            return enc_module.encode_delta(self.current_page_values, self.column_type)
        else:
            return enc_module.encode_plain(self.current_page_values, self.column_type)

    def _compress_data(self, data: bytes) -> bytes:
        """Compress data using selected compression."""
        if self.compression == Compression.NONE:
            return data
        elif self.compression == Compression.LZ4:
            return comp_module.compress_lz4(data)
        elif self.compression == Compression.SNAPPY:
            return comp_module.compress_snappy(data)
        elif self.compression == Compression.ZSTD:
            return comp_module.compress_zstd(data, level=3)
        else:
            return data

    def _create_null_bitmap(self) -> bytes | None:
        """Create null bitmap from null flags."""
        if not any(self.current_page_nulls):
            return None

        # Pack booleans into bytes (8 bools per byte)
        bitmap = bytearray()
        for i in range(0, len(self.current_page_nulls), 8):
            byte = 0
            for j in range(8):
                if i + j < len(self.current_page_nulls):
                    if not self.current_page_nulls[i + j]:
                        byte |= 1 << j
            bitmap.append(byte)

        return bytes(bitmap)

    def finish(self) -> ColumnChunk:
        """Flush remaining data and create column chunk."""
        if self.current_page_values:
            self._flush_page()

        chunk = ColumnChunk(
            column_index=self.column_index,
            column_name=self.column_name,
            column_type=self.column_type,
            encoding=self.encoding,
            compression=self.compression,
            pages=self.pages,
            dictionary_page=self.dictionary_page,
            statistics=self.statistics,
        )
        return chunk


class ColumnChunkReader:
    """Reader for column chunks with page materialization."""

    def __init__(self, column_chunk: ColumnChunk) -> None:
        """Initialize column chunk reader.

        Args:
            column_chunk: Column chunk to read
        """
        self.column_chunk = column_chunk

    def read_all(self) -> list[Any]:
        """Read all values from column chunk."""
        all_values = []

        for page in self.column_chunk.pages:
            values = self._read_page(page)
            all_values.extend(values)

        return all_values

    def read_page(self, page_number: int) -> list[Any]:
        """Read single page from column chunk."""
        if page_number >= len(self.column_chunk.pages):
            raise StorageError(f"Page {page_number} not found")

        return self._read_page(self.column_chunk.pages[page_number])

    def _read_page(self, page: DataPage) -> list[Any]:
        """Read and decompress page data."""
        data = page.data

        # Decompress if needed
        if page.compression != Compression.NONE:
            data = self._decompress_data(data, page.compression)

        # Use statistics for num_values if available, otherwise estimate
        if page.statistics and page.statistics.total_value_count > 0:
            num_values = page.statistics.total_value_count
        else:
            num_values = self._estimate_num_values(data)

        if num_values == 0:
            return []

        if page.encoding == Encoding.DICTIONARY and self.column_chunk.dictionary_page:
            values = enc_module.decode_dictionary(data, self.column_chunk.dictionary_page.dictionary_values, num_values)
        elif page.encoding == Encoding.RLE:
            values = enc_module.decode_rle(data, self.column_chunk.column_type, num_values)
        elif page.encoding == Encoding.DELTA:
            values = enc_module.decode_delta(data, self.column_chunk.column_type, num_values)
        else:
            values = enc_module.decode_plain(data, self.column_chunk.column_type, num_values, page.null_bitmap)

        return values

    def _decompress_data(self, data: bytes, compression: Compression) -> bytes:
        """Decompress data using specified compression."""
        if compression == Compression.NONE:
            return data
        elif compression == Compression.LZ4:
            return comp_module.decompress_lz4(data)
        elif compression == Compression.SNAPPY:
            return comp_module.decompress_snappy(data)
        elif compression == Compression.ZSTD:
            return comp_module.decompress_zstd(data)
        else:
            raise StorageError(f"Unknown compression: {compression}")

    def _estimate_num_values(self, data: bytes) -> int:
        """Estimate number of values in page."""
        byte_width = self.column_chunk.column_type.byte_width()
        if byte_width and byte_width > 0:
            return len(data) // byte_width

        # Conservative estimate for variable-length
        return len(data) if data else 0


class RowGroupWriter:
    """Writer for row groups containing multiple column chunks."""

    def __init__(
        self,
        group_id: int,
        schema: Schema,
        encoding: Encoding = Encoding.PLAIN,
        compression: Compression = Compression.NONE,
        page_size: int = 65536,
    ) -> None:
        """Initialize row group writer.

        Args:
            group_id: ID of row group
            schema: Schema defining columns
            encoding: Default encoding for all columns
            compression: Default compression for all columns
            page_size: Target page size
        """
        self.group_id = group_id
        self.schema = schema
        self.encoding = encoding
        self.compression = compression
        self.page_size = page_size
        self.num_rows = 0

        self.column_writers: dict[int, ColumnChunkWriter] = {}
        for i, field in enumerate(schema.fields):
            self.column_writers[i] = ColumnChunkWriter(
                column_index=i,
                column_name=field.name,
                column_type=field.column_type,
                encoding=encoding,
                compression=compression,
                page_size=page_size,
            )

    def write_row(self, row: dict[str, Any]) -> None:
        """Write single row to row group."""
        for i, field in enumerate(self.schema.fields):
            value = row.get(field.name)
            self.column_writers[i].write_values([value])

        self.num_rows += 1

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        """Write multiple rows to row group."""
        for row in rows:
            self.write_row(row)

    def write_column(self, column_index: int, values: list[Any]) -> None:
        """Write column values."""
        if column_index not in self.column_writers:
            raise StorageError(f"Column {column_index} not in schema")

        self.column_writers[column_index].write_values(values)

    def finish(self) -> RowGroup:
        """Flush all columns and create row group."""
        row_group = RowGroup(group_id=self.group_id, num_rows=self.num_rows)

        for col_idx, writer in self.column_writers.items():
            chunk = writer.finish()
            row_group.add_column_chunk(chunk)

        return row_group


class RowGroupReader:
    """Reader for row groups containing multiple column chunks."""

    def __init__(self, row_group: RowGroup) -> None:
        """Initialize row group reader.

        Args:
            row_group: Row group to read
        """
        self.row_group = row_group

    def read_all_rows(self) -> list[dict[str, Any]]:
        """Read all rows from row group."""
        num_rows = self.row_group.num_rows
        rows = [{} for _ in range(num_rows)]

        for col_idx, chunk in self.row_group.column_chunks.items():
            reader = ColumnChunkReader(chunk)
            values = reader.read_all()

            for i, value in enumerate(values):
                if i < num_rows:
                    rows[i][chunk.column_name] = value

        return rows

    def read_column(self, column_index: int) -> list[Any]:
        """Read single column from row group."""
        chunk = self.row_group.get_column_chunk(column_index)
        if not chunk:
            raise StorageError(f"Column {column_index} not found in row group")

        reader = ColumnChunkReader(chunk)
        return reader.read_all()

    def read_columns(self, column_indices: list[int]) -> dict[int, list[Any]]:
        """Read multiple columns from row group."""
        result = {}
        for col_idx in column_indices:
            result[col_idx] = self.read_column(col_idx)
        return result


class ColumnarFileWriter:
    """Writer for columnar files with multiple row groups."""

    def __init__(
        self,
        schema: Schema,
        encoding: Encoding = Encoding.PLAIN,
        compression: Compression = Compression.NONE,
        row_group_size: int = 131072,
        page_size: int = 65536,
    ) -> None:
        """Initialize columnar file writer.

        Args:
            schema: Schema for the file
            encoding: Default encoding for columns
            compression: Default compression for columns
            row_group_size: Target rows per row group
            page_size: Target size per page
        """
        self.schema = schema
        self.encoding = encoding
        self.compression = compression
        self.row_group_size = row_group_size
        self.page_size = page_size

        self.row_groups: list[RowGroup] = []
        self.current_row_group: RowGroupWriter | None = None
        self.total_rows = 0

    def write_row(self, row: dict[str, Any]) -> None:
        """Write single row."""
        if self.current_row_group is None:
            self._start_row_group()

        assert self.current_row_group is not None
        self.current_row_group.write_row(row)
        self.total_rows += 1

        if self.current_row_group.num_rows >= self.row_group_size:
            self._finish_row_group()

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        """Write multiple rows."""
        for row in rows:
            self.write_row(row)

    def _start_row_group(self) -> None:
        """Start new row group."""
        self.current_row_group = RowGroupWriter(
            group_id=len(self.row_groups),
            schema=self.schema,
            encoding=self.encoding,
            compression=self.compression,
            page_size=self.page_size,
        )

    def _finish_row_group(self) -> None:
        """Finish current row group."""
        if self.current_row_group:
            self.row_groups.append(self.current_row_group.finish())
            self.current_row_group = None

    def finish(self) -> ColumnarFileMetadata:
        """Finish writing and return metadata."""
        if self.current_row_group and self.current_row_group.num_rows > 0:
            self._finish_row_group()

        metadata = ColumnarFileMetadata(
            schema=self.schema,
            num_rows=self.total_rows,
            created_at=int(datetime.now().timestamp()),
            row_groups=self.row_groups,
        )

        return metadata


class ColumnarFileReader:
    """Reader for columnar files with multiple row groups."""

    def __init__(self, metadata: ColumnarFileMetadata) -> None:
        """Initialize columnar file reader.

        Args:
            metadata: File metadata
        """
        self.metadata = metadata

    def read_all_rows(self) -> list[dict[str, Any]]:
        """Read all rows from all row groups."""
        all_rows = []

        for row_group in self.metadata.row_groups:
            reader = RowGroupReader(row_group)
            rows = reader.read_all_rows()
            all_rows.extend(rows)

        return all_rows

    def read_row_group(self, group_id: int) -> list[dict[str, Any]]:
        """Read all rows from specific row group."""
        if group_id >= len(self.metadata.row_groups):
            raise StorageError(f"Row group {group_id} not found")

        reader = RowGroupReader(self.metadata.row_groups[group_id])
        return reader.read_all_rows()

    def read_column(self, column_name: str) -> list[Any]:
        """Read entire column across all row groups."""
        col_idx = self.metadata.schema.get_field_index(column_name)
        all_values = []

        for row_group in self.metadata.row_groups:
            reader = RowGroupReader(row_group)
            values = reader.read_column(col_idx)
            all_values.extend(values)

        return all_values

    def read_columns(self, column_names: list[str]) -> dict[str, list[Any]]:
        """Read multiple columns across all row groups."""
        indices = [self.metadata.schema.get_field_index(name) for name in column_names]
        result = {name: [] for name in column_names}

        for row_group in self.metadata.row_groups:
            reader = RowGroupReader(row_group)
            col_data = reader.read_columns(indices)
            for name, idx in zip(column_names, indices):
                result[name].extend(col_data[idx])

        return result
