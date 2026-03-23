"""
Read model store for denormalized views.

Provides create, read, update, delete operations on denormalized read models
with indexing and query builder support.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._exceptions import ReadModelException


@dataclass
class QueryFilter:
    """Filter for read model queries."""

    field: str
    operator: str  # "eq", "ne", "gt", "lt", "gte", "lte", "in", "contains"
    value: Any

    def matches(self, doc: dict[str, Any]) -> bool:
        """
        Check if document matches filter.

        Args:
            doc: Document to check

        Returns:
            True if matches
        """
        if field := doc.get(self.field):
            if self.operator == "eq":
                return field == self.value
            elif self.operator == "ne":
                return field != self.value
            elif self.operator == "gt":
                return field > self.value
            elif self.operator == "lt":
                return field < self.value
            elif self.operator == "gte":
                return field >= self.value
            elif self.operator == "lte":
                return field <= self.value
            elif self.operator == "in":
                return field in self.value
            elif self.operator == "contains":
                return self.value in field
        return False


class QueryBuilder:
    """
    Builder for read model queries.

    Constructs complex queries with filters, ordering, and limits.
    """

    def __init__(self) -> None:
        """Initialize query builder."""
        self._filters: list[QueryFilter] = []
        self._order_by: tuple[str, str] | None = None
        self._limit_count: int | None = None
        self._offset_count: int = 0

    def where(self, field: str, operator: str, value: Any) -> QueryBuilder:
        """
        Add filter condition.

        Args:
            field: Field to filter on
            operator: Comparison operator
            value: Value to compare

        Returns:
            Self for chaining
        """
        self._filters.append(QueryFilter(field, operator, value))
        return self

    def order_by(self, field: str, direction: str = "asc") -> QueryBuilder:
        """
        Set ordering.

        Args:
            field: Field to order by
            direction: "asc" or "desc"

        Returns:
            Self for chaining
        """
        self._order_by = (field, direction)
        return self

    def limit(self, count: int) -> QueryBuilder:
        """
        Set result limit.

        Args:
            count: Maximum results

        Returns:
            Self for chaining
        """
        self._limit_count = count
        return self

    def offset(self, count: int) -> QueryBuilder:
        """
        Set result offset.

        Args:
            count: Number of results to skip

        Returns:
            Self for chaining
        """
        self._offset_count = count
        return self

    def build(self) -> dict[str, Any]:
        """
        Build query specification.

        Returns:
            Query specification dict
        """
        return {
            "filters": self._filters,
            "order_by": self._order_by,
            "limit": self._limit_count,
            "offset": self._offset_count,
        }


@dataclass
class ReadModelDocument:
    """Document in read model store."""

    id: str
    data: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    version: int = 1


class ReadModelStore:
    """
    In-memory store for denormalized read models.

    Provides CRUD operations and query support with indexing.
    """

    def __init__(self) -> None:
        """Initialize read model store."""
        self._documents: dict[str, ReadModelDocument] = {}
        self._indexes: dict[str, dict[Any, list[str]]] = {}
        self._lock = asyncio.Lock()

    async def create(self, id: str, data: dict[str, Any]) -> ReadModelDocument:
        """
        Create document.

        Args:
            id: Document ID
            data: Document data

        Returns:
            Created document

        Raises:
            ReadModelException: If document exists
        """
        async with self._lock:
            if id in self._documents:
                raise ReadModelException(f"Document {id} already exists")

            doc = ReadModelDocument(id=id, data=data.copy())
            self._documents[id] = doc
            self._update_indexes(id, doc)
            return doc

    async def update(
        self,
        id: str,
        data: dict[str, Any],
    ) -> ReadModelDocument:
        """
        Update document.

        Args:
            id: Document ID
            data: Updated data

        Returns:
            Updated document

        Raises:
            ReadModelException: If not found
        """
        async with self._lock:
            if id not in self._documents:
                raise ReadModelException(f"Document {id} not found")

            doc = self._documents[id]
            self._remove_indexes(id, doc)

            doc.data.update(data)
            doc.updated_at = datetime.utcnow()
            doc.version += 1

            self._update_indexes(id, doc)
            return doc

    async def delete(self, id: str) -> None:
        """
        Delete document.

        Args:
            id: Document ID

        Raises:
            ReadModelException: If not found
        """
        async with self._lock:
            if id not in self._documents:
                raise ReadModelException(f"Document {id} not found")

            doc = self._documents.pop(id)
            self._remove_indexes(id, doc)

    async def get(self, id: str) -> ReadModelDocument | None:
        """
        Get document by ID.

        Args:
            id: Document ID

        Returns:
            Document or None
        """
        async with self._lock:
            return self._documents.get(id)

    async def query(self, spec: dict[str, Any]) -> list[ReadModelDocument]:
        """
        Query documents.

        Args:
            spec: Query specification from QueryBuilder

        Returns:
            Matching documents
        """
        async with self._lock:
            results = list(self._documents.values())

            # Apply filters
            for filter_item in spec.get("filters", []):
                results = [doc for doc in results if filter_item.matches(doc.data)]

            # Apply ordering
            if order_by := spec.get("order_by"):
                field, direction = order_by
                reverse = direction == "desc"
                results.sort(
                    key=lambda d: d.data.get(field, ""),
                    reverse=reverse,
                )

            # Apply offset and limit
            offset = spec.get("offset", 0)
            limit = spec.get("limit")

            if offset > 0:
                results = results[offset:]
            if limit:
                results = results[:limit]

            return results

    async def count(self) -> int:
        """
        Get total document count.

        Returns:
            Document count
        """
        async with self._lock:
            return len(self._documents)

    async def clear(self) -> None:
        """Clear all documents."""
        async with self._lock:
            self._documents.clear()
            self._indexes.clear()

    def _update_indexes(self, doc_id: str, doc: ReadModelDocument) -> None:
        """Update indexes for document."""
        # Index common fields
        for field in ["id", "type", "status"]:
            if field in doc.data:
                if field not in self._indexes:
                    self._indexes[field] = {}

                value = doc.data[field]
                if value not in self._indexes[field]:
                    self._indexes[field][value] = []

                self._indexes[field][value].append(doc_id)

    def _remove_indexes(self, doc_id: str, doc: ReadModelDocument) -> None:
        """Remove indexes for document."""
        for field in ["id", "type", "status"]:
            if field in doc.data and field in self._indexes:
                value = doc.data[field]
                if value in self._indexes[field]:
                    self._indexes[field][value] = [d for d in self._indexes[field][value] if d != doc_id]

    async def find_by_index(self, field: str, value: Any) -> list[ReadModelDocument]:
        """
        Find documents using index.

        Args:
            field: Field to search
            value: Value to match

        Returns:
            Matching documents
        """
        async with self._lock:
            if field not in self._indexes or value not in self._indexes[field]:
                return []

            doc_ids = self._indexes[field][value]
            return [self._documents[doc_id] for doc_id in doc_ids if doc_id in self._documents]

    async def rebuild_indexes(self) -> None:
        """Rebuild all indexes."""
        async with self._lock:
            self._indexes.clear()
            for doc_id, doc in self._documents.items():
                self._update_indexes(doc_id, doc)
