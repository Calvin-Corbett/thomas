"""Data loaders for CSV, JSON, XML, Parquet with streaming and batch support."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from typing import Any


@dataclass
class LoadResult:
    """Result of data loading."""

    rows_loaded: int
    rows_failed: int
    errors: list[str]
    sample_data: list[dict[str, Any]]


class DataLoader:
    """Base data loader."""

    def load(self, source: str) -> LoadResult:
        """Load data from source."""
        raise NotImplementedError

    def stream(self, source: str, batch_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        """Stream data in batches."""
        raise NotImplementedError


class CSVLoader(DataLoader):
    """Load CSV files."""

    def load(self, source: str) -> LoadResult:
        """Load CSV data."""
        rows = []
        errors = []
        failed = 0

        try:
            reader = csv.DictReader(StringIO(source))
            for row in reader:
                try:
                    rows.append(row)
                except Exception as e:
                    errors.append(f"Row error: {e}")
                    failed += 1

        except Exception as e:
            errors.append(f"CSV parse error: {e}")

        return LoadResult(
            rows_loaded=len(rows),
            rows_failed=failed,
            errors=errors[:10],  # Limit error list
            sample_data=rows[:5],
        )

    def stream(self, source: str, batch_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        """Stream CSV data."""
        batch = []
        reader = csv.DictReader(StringIO(source))

        for row in reader:
            batch.append(row)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch


class JSONLoader(DataLoader):
    """Load JSON data."""

    def load(self, source: str) -> LoadResult:
        """Load JSON data."""
        rows = []
        errors = []
        failed = 0

        try:
            data = json.loads(source)

            # Handle array of objects
            if isinstance(data, list):
                rows = data
            elif isinstance(data, dict):
                # Try to find array in object
                for value in data.values():
                    if isinstance(value, list):
                        rows = value
                        break

        except json.JSONDecodeError as e:
            errors.append(f"JSON parse error: {e}")
            failed = 1

        return LoadResult(
            rows_loaded=len(rows),
            rows_failed=failed,
            errors=errors,
            sample_data=rows[:5] if isinstance(rows[0] if rows else None, dict) else [],
        )

    def stream(self, source: str, batch_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        """Stream JSON data."""
        data = json.loads(source)
        rows = data if isinstance(data, list) else list(data.values())[0]

        batch = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch


class XMLLoader(DataLoader):
    """Load XML data (simple implementation)."""

    def load(self, source: str) -> LoadResult:
        """Load XML data."""
        rows = []
        errors = []

        try:
            # Simple XML parsing - just extract text content
            import xml.etree.ElementTree as ET

            root = ET.fromstring(source)

            # Assume structure: <root><item>...</item>...</root>
            for item in root:
                row = {}
                for child in item:
                    row[child.tag] = child.text
                if row:
                    rows.append(row)

        except Exception as e:
            errors.append(f"XML parse error: {e}")

        return LoadResult(rows_loaded=len(rows), rows_failed=0, errors=errors, sample_data=rows[:5])

    def stream(self, source: str, batch_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        """Stream XML data."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(source)

        batch = []
        for item in root:
            row = {}
            for child in item:
                row[child.tag] = child.text
            if row:
                batch.append(row)
                if len(batch) >= batch_size:
                    yield batch
                    batch = []

        if batch:
            yield batch


class ParquetLoader(DataLoader):
    """Load Parquet data (simplified, using JSON representation)."""

    def load(self, source: str) -> LoadResult:
        """Load Parquet-like data."""
        # In real implementation, would use pyarrow
        # Here we assume Parquet is represented as JSON with metadata
        try:
            data = json.loads(source)
            rows = data.get("data", [])
            metadata = data.get("metadata", {})

            return LoadResult(rows_loaded=len(rows), rows_failed=0, errors=[], sample_data=rows[:5])

        except Exception as e:
            return LoadResult(rows_loaded=0, rows_failed=1, errors=[str(e)], sample_data=[])

    def stream(self, source: str, batch_size: int = 100) -> Iterator[list[dict[str, Any]]]:
        """Stream Parquet data."""
        data = json.loads(source)
        rows = data.get("data", [])

        batch = []
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                yield batch
                batch = []

        if batch:
            yield batch


class DataValidator:
    """Validate loaded data."""

    def __init__(self, schema: dict[str, str] | None = None):
        self.schema = schema or {}

    def validate(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate data against schema."""
        issues = []
        valid_rows = 0

        for row_idx, row in enumerate(data):
            for field, expected_type in self.schema.items():
                if field not in row:
                    issues.append(f"Row {row_idx}: missing field '{field}'")
                else:
                    value = row[field]
                    if expected_type == "int" and not isinstance(value, int):
                        issues.append(f"Row {row_idx}: '{field}' expected int, got {type(value).__name__}")
                    elif expected_type == "string" and not isinstance(value, str):
                        issues.append(f"Row {row_idx}: '{field}' expected string")

            valid_rows += 1 if not any(f"Row {row_idx}:" in i for i in issues) else 0

        return {
            "valid_rows": valid_rows,
            "invalid_rows": len(data) - valid_rows,
            "total_rows": len(data),
            "issues": issues[:20],  # Limit issue list
        }


class DataLoaderFactory:
    """Factory for creating data loaders."""

    _loaders = {
        "csv": CSVLoader,
        "json": JSONLoader,
        "xml": XMLLoader,
        "parquet": ParquetLoader,
    }

    @classmethod
    def create_loader(cls, format_type: str) -> DataLoader | None:
        """Create loader for format."""
        loader_class = cls._loaders.get(format_type.lower())
        return loader_class() if loader_class else None

    @classmethod
    def register_loader(cls, format_type: str, loader_class) -> None:
        """Register custom loader."""
        cls._loaders[format_type.lower()] = loader_class

    @classmethod
    def get_supported_formats(cls) -> list[str]:
        """Get supported formats."""
        return list(cls._loaders.keys())
