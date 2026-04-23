"""Log search and retrieval functionality."""

import re
import threading
from collections import defaultdict
from datetime import datetime
from typing import Any

from thomas.marketplace.logging_framework._types import LogQuery, LogRecord


class InvertedIndex:
    """Inverted index for full-text search on log messages."""

    def __init__(self) -> None:
        """Initialize inverted index."""
        self.index: dict[str, set[int]] = defaultdict(set)
        self.documents: dict[int, LogRecord] = {}
        self.next_doc_id = 0
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a log record to the index.

        Args:
            record: Log record to index
        """
        with self._lock:
            doc_id = self.next_doc_id
            self.next_doc_id += 1
            self.documents[doc_id] = record

            # Tokenize message and index
            tokens = self._tokenize(record.message)
            for token in tokens:
                self.index[token].add(doc_id)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text for indexing.

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        # Split on whitespace and punctuation, lowercase
        tokens = re.findall(r"\w+", text.lower())
        return tokens

    def search(self, query_text: str) -> list[LogRecord]:
        """Search for records matching query text.

        Args:
            query_text: Search query

        Returns:
            List of matching records
        """
        with self._lock:
            query_tokens = self._tokenize(query_text)
            if not query_tokens:
                return []

            # Start with first token's matches
            result_ids = set(self.index.get(query_tokens[0], set()))

            # Intersect with other tokens
            for token in query_tokens[1:]:
                result_ids &= set(self.index.get(token, set()))

            # Convert doc IDs back to records
            return [self.documents[doc_id] for doc_id in result_ids]


class FieldIndexer:
    """Creates indexes on specific fields for efficient filtering."""

    def __init__(self) -> None:
        """Initialize field indexer."""
        self.field_indexes: dict[str, dict[Any, set[int]]] = defaultdict(lambda: defaultdict(set))
        self.records: dict[int, LogRecord] = {}
        self.next_id = 0
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add record to field indexes.

        Args:
            record: Log record to index
        """
        with self._lock:
            doc_id = self.next_id
            self.next_id += 1
            self.records[doc_id] = record

            # Index by level
            self.field_indexes["level"][record.level].add(doc_id)

            # Index by logger
            self.field_indexes["logger"][record.logger_name].add(doc_id)

            # Index structured fields
            for field_name, field in record.fields.items():
                self.field_indexes[f"field_{field_name}"][field.value].add(doc_id)

    def search_field(self, field_name: str, value: Any) -> list[LogRecord]:
        """Search by exact field value.

        Args:
            field_name: Field name to search
            value: Value to match

        Returns:
            List of matching records
        """
        with self._lock:
            doc_ids = self.field_indexes[field_name].get(value, set())
            return [self.records[doc_id] for doc_id in doc_ids]


class LogStore:
    """In-memory log storage with search capabilities."""

    def __init__(self, max_size: int = 100000) -> None:
        """Initialize log store.

        Args:
            max_size: Maximum number of records to store
        """
        self.max_size = max_size
        self.records: list[LogRecord] = []
        self.text_index = InvertedIndex()
        self.field_indexer = FieldIndexer()
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add a record to the store.

        Args:
            record: Log record to add
        """
        with self._lock:
            self.records.append(record)
            self.text_index.add_record(record)
            self.field_indexer.add_record(record)

            # Remove oldest if exceeding max size
            if len(self.records) > self.max_size:
                self.records.pop(0)
                # TODO: Remove from indexes

    def search(self, query: LogQuery) -> tuple[list[LogRecord], int]:
        """Search logs using a LogQuery.

        Args:
            query: LogQuery specification

        Returns:
            Tuple of (matching records, total count)
        """
        with self._lock:
            # Filter records matching query
            results = []
            for record in self.records:
                if query.matches(record):
                    results.append(record)

            # Apply offset and limit
            total = len(results)
            results = results[query.offset : query.offset + query.limit]

            return results, total

    def get_records_by_time_range(
        self,
        start: datetime,
        end: datetime,
    ) -> list[LogRecord]:
        """Get records within time range.

        Args:
            start: Start time
            end: End time

        Returns:
            List of records in range
        """
        with self._lock:
            return [r for r in self.records if start <= r.timestamp <= end]


class LogTailer:
    """Tail logs matching a query, returning new logs as they arrive."""

    def __init__(self, query: LogQuery, poll_interval: float = 0.1) -> None:
        """Initialize log tailer.

        Args:
            query: Query to match
            poll_interval: How often to check for new logs
        """
        self.query = query
        self.poll_interval = poll_interval
        self.last_timestamp: datetime | None = None
        self._new_records: list[LogRecord] = []
        self._lock = threading.RLock()

    def on_new_record(self, record: LogRecord) -> None:
        """Called when a new record is available.

        Args:
            record: New log record
        """
        if self.query.matches(record):
            with self._lock:
                if self.last_timestamp is None or record.timestamp > self.last_timestamp:
                    self._new_records.append(record)
                    self.last_timestamp = record.timestamp

    def get_new_records(self) -> list[LogRecord]:
        """Get new records since last call.

        Returns:
            List of new matching records
        """
        with self._lock:
            records = self._new_records[:]
            self._new_records.clear()
            return records


class SearchResultsPaginator:
    """Handles pagination of search results."""

    def __init__(self, records: list[LogRecord], page_size: int = 50) -> None:
        """Initialize paginator.

        Args:
            records: Complete list of records
            page_size: Records per page
        """
        self.records = records
        self.page_size = page_size
        self.current_page = 0

    def get_page(self, page_num: int = 0) -> tuple[list[LogRecord], int]:
        """Get a page of results.

        Args:
            page_num: Page number (0-indexed)

        Returns:
            Tuple of (records for page, total pages)
        """
        if page_num < 0:
            page_num = 0

        start = page_num * self.page_size
        end = start + self.page_size

        total_pages = (len(self.records) + self.page_size - 1) // self.page_size

        return self.records[start:end], total_pages

    def next_page(self) -> tuple[list[LogRecord], int]:
        """Get next page.

        Returns:
            Tuple of (records for page, total pages)
        """
        page, total = self.get_page(self.current_page + 1)
        if page:
            self.current_page += 1
        return page, total

    def prev_page(self) -> tuple[list[LogRecord], int]:
        """Get previous page.

        Returns:
            Tuple of (records for page, total pages)
        """
        page, total = self.get_page(self.current_page - 1)
        if page:
            self.current_page -= 1
        return page, total


class ResultHighlighter:
    """Highlights matched search terms in results."""

    def __init__(self, search_terms: list[str]) -> None:
        """Initialize highlighter.

        Args:
            search_terms: Terms to highlight
        """
        self.search_terms = search_terms

    def highlight_record(
        self,
        record: LogRecord,
        tag_start: str = "<mark>",
        tag_end: str = "</mark>",
    ) -> dict[str, Any]:
        """Highlight search terms in a record.

        Args:
            record: Record to highlight
            tag_start: HTML tag to open highlight
            tag_end: HTML tag to close highlight

        Returns:
            Dict with highlighted message and fields
        """
        highlighted_message = self._highlight_text(
            record.message,
            tag_start,
            tag_end,
        )

        highlighted_fields = {}
        for field_name, field in record.fields.items():
            highlighted_fields[field_name] = self._highlight_text(
                str(field.value),
                tag_start,
                tag_end,
            )

        return {
            "message": highlighted_message,
            "fields": highlighted_fields,
        }

    def _highlight_text(
        self,
        text: str,
        tag_start: str,
        tag_end: str,
    ) -> str:
        """Highlight terms in text.

        Args:
            text: Text to highlight
            tag_start: Start tag
            tag_end: End tag

        Returns:
            Text with highlights
        """
        for term in self.search_terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            text = pattern.sub(f"{tag_start}{term}{tag_end}", text)

        return text


class FacetedSearch:
    """Provides faceted search results."""

    def __init__(self) -> None:
        """Initialize faceted search."""
        self.facets: dict[str, dict[Any, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = threading.RLock()

    def add_record(self, record: LogRecord) -> None:
        """Add record to facet counts.

        Args:
            record: Log record to add
        """
        with self._lock:
            self.facets["level"][record.level.name] += 1
            self.facets["logger"][record.logger_name] += 1

            for field_name, field in record.fields.items():
                value = str(field.value)[:100]  # Truncate long values
                self.facets[f"field_{field_name}"][value] += 1

    def get_facet_counts(
        self,
        facet_name: str,
        top_n: int = 10,
    ) -> list[tuple[Any, int]]:
        """Get counts for a facet.

        Args:
            facet_name: Name of facet
            top_n: Return top N values

        Returns:
            List of (value, count) tuples sorted by count
        """
        with self._lock:
            facet = self.facets.get(facet_name, {})
            sorted_facet = sorted(facet.items(), key=lambda x: x[1], reverse=True)
            return sorted_facet[:top_n]

    def get_all_facets(self) -> dict[str, list[tuple[Any, int]]]:
        """Get all facet values.

        Returns:
            Dict mapping facet names to value counts
        """
        with self._lock:
            return {
                name: sorted(counts.items(), key=lambda x: x[1], reverse=True) for name, counts in self.facets.items()
            }
