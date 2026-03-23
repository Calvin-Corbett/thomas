"""Faceted search implementation."""

from collections import defaultdict
from typing import Any

from .index import InvertedIndex


class FacetValue:
    """Single facet value with count."""

    def __init__(self, value: Any, count: int) -> None:
        """Initialize facet value."""
        self.value = value
        self.count = count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"value": self.value, "count": self.count}


class Facet:
    """Base facet class."""

    def __init__(self, field: str, name: str) -> None:
        """Initialize facet."""
        self.field = field
        self.name = name
        self.values: dict[Any, int] = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        sorted_values = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        return {"field": self.field, "values": [{"value": v, "count": c} for v, c in sorted_values]}


class TermFacet(Facet):
    """Count of values for field."""

    def __init__(self, field: str, name: str = None, limit: int = 10) -> None:
        """Initialize term facet."""
        super().__init__(field, name or f"facet_{field}")
        self.limit = limit

    def aggregate(self, index: InvertedIndex, doc_ids: list[int]) -> None:
        """Calculate facet for document set."""
        self.values.clear()

        # Get all documents with this field
        for doc_id in doc_ids:
            doc = index.document_store.get_document(doc_id)
            if doc and self.field in doc:
                value = str(doc[self.field])
                self.values[value] = self.values.get(value, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with limit."""
        sorted_values = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        limited = sorted_values[: self.limit]
        other_count = sum(c for _, c in sorted_values[self.limit :])

        result = {"field": self.field, "values": [{"value": v, "count": c} for v, c in limited]}

        if other_count > 0:
            result["other"] = other_count

        return result


class RangeFacet(Facet):
    """Numeric range faceting."""

    def __init__(self, field: str, name: str = None, ranges: list[tuple[Any, Any]] | None = None) -> None:
        """Initialize range facet."""
        super().__init__(field, name or f"facet_{field}_range")
        self.ranges = ranges or []
        self.range_counts: dict[int, int] = defaultdict(int)

    def add_range(self, min_val: Any, max_val: Any) -> None:
        """Add range bucket."""
        self.ranges.append((min_val, max_val))

    def aggregate(self, index: InvertedIndex, doc_ids: list[int]) -> None:
        """Calculate range facet."""
        self.range_counts.clear()

        for doc_id in doc_ids:
            doc = index.document_store.get_document(doc_id)
            if doc and self.field in doc:
                try:
                    value = float(doc[self.field])
                    for i, (min_val, max_val) in enumerate(self.ranges):
                        if min_val <= value < max_val:
                            self.range_counts[i] += 1
                except (ValueError, TypeError):
                    pass

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "field": self.field,
            "ranges": [
                {"min": min_val, "max": max_val, "count": self.range_counts.get(i, 0)}
                for i, (min_val, max_val) in enumerate(self.ranges)
            ],
        }


class DateHistogramFacet(Facet):
    """Date range histogram."""

    def __init__(self, field: str, name: str = None, interval: str = "day") -> None:
        """Initialize date histogram facet."""
        super().__init__(field, name or f"facet_{field}_date")
        self.interval = interval

    def aggregate(self, index: InvertedIndex, doc_ids: list[int]) -> None:
        """Calculate date histogram."""
        self.values.clear()

        for doc_id in doc_ids:
            doc = index.document_store.get_document(doc_id)
            if doc and self.field in doc:
                date_val = doc[self.field]
                bucket = self._get_bucket(date_val)
                self.values[bucket] = self.values.get(bucket, 0) + 1

    def _get_bucket(self, date_val: Any) -> str:
        """Convert date to bucket."""
        date_str = str(date_val)
        if self.interval == "day":
            return date_str[:10]
        elif self.interval == "month":
            return date_str[:7]
        elif self.interval == "year":
            return date_str[:4]
        return date_str


class HierarchicalFacet(Facet):
    """Hierarchical/nested facet."""

    def __init__(self, field: str, name: str = None, separator: str = "/") -> None:
        """Initialize hierarchical facet."""
        super().__init__(field, name or f"facet_{field}_hier")
        self.separator = separator
        self.hierarchy: dict[str, dict[str, Any]] = {}

    def aggregate(self, index: InvertedIndex, doc_ids: list[int]) -> None:
        """Calculate hierarchical facet."""
        self.values.clear()
        self.hierarchy.clear()

        for doc_id in doc_ids:
            doc = index.document_store.get_document(doc_id)
            if doc and self.field in doc:
                value = str(doc[self.field])
                parts = value.split(self.separator)
                self.values[value] = self.values.get(value, 0) + 1

                # Build hierarchy
                current = self.hierarchy
                for i, part in enumerate(parts):
                    if part not in current:
                        current[part] = {"count": 0, "children": {}}
                    current[part]["count"] += 1
                    current = current[part]["children"]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with hierarchy."""
        return {"field": self.field, "hierarchy": self.hierarchy}


class StatsFacet(Facet):
    """Statistics aggregation."""

    def __init__(self, field: str, name: str = None) -> None:
        """Initialize stats facet."""
        super().__init__(field, name or f"facet_{field}_stats")
        self.min_val: float | None = None
        self.max_val: float | None = None
        self.sum_val: float = 0.0
        self.count: int = 0

    def aggregate(self, index: InvertedIndex, doc_ids: list[int]) -> None:
        """Calculate statistics."""
        self.min_val = None
        self.max_val = None
        self.sum_val = 0.0
        self.count = 0

        for doc_id in doc_ids:
            doc = index.document_store.get_document(doc_id)
            if doc and self.field in doc:
                try:
                    value = float(doc[self.field])
                    self.sum_val += value
                    self.count += 1
                    if self.min_val is None or value < self.min_val:
                        self.min_val = value
                    if self.max_val is None or value > self.max_val:
                        self.max_val = value
                except (ValueError, TypeError):
                    pass

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        avg_val = self.sum_val / self.count if self.count > 0 else 0.0
        return {
            "field": self.field,
            "count": self.count,
            "min": self.min_val,
            "max": self.max_val,
            "avg": avg_val,
            "sum": self.sum_val,
        }


class FacetFilter:
    """Filters based on facet values."""

    def __init__(self) -> None:
        """Initialize facet filter."""
        self.filters: dict[str, list[Any]] = defaultdict(list)

    def add_filter(self, field: str, value: Any) -> None:
        """Add facet value filter."""
        self.filters[field].append(value)

    def apply(self, index: InvertedIndex, doc_ids: list[int]) -> list[int]:
        """Filter documents by facet values."""
        result = set(doc_ids)

        for field, values in self.filters.items():
            matching_docs = set()
            for doc_id in doc_ids:
                doc = index.document_store.get_document(doc_id)
                if doc and self.field in doc:
                    if doc[field] in values:
                        matching_docs.add(doc_id)
            result &= matching_docs

        return list(result)


class FacetAggregator:
    """Aggregates multiple facets."""

    def __init__(self) -> None:
        """Initialize aggregator."""
        self.facets: dict[str, Facet] = {}

    def add_facet(self, facet: Facet) -> None:
        """Add facet."""
        self.facets[facet.name] = facet

    def aggregate_all(self, index: InvertedIndex, doc_ids: list[int]) -> dict[str, Any]:
        """Calculate all facets."""
        results = {}
        for name, facet in self.facets.items():
            facet.aggregate(index, doc_ids)
            results[name] = facet.to_dict()
        return results

    def get_facet(self, name: str) -> Facet | None:
        """Get facet by name."""
        return self.facets.get(name)
