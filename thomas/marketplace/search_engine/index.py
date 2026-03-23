"""Inverted index implementation for the search engine."""

import json
from collections import defaultdict
from typing import Any

from ._exceptions import IndexError
from ._types import IndexConfig, Posting
from .analyzer import Analyzer, AnalyzerFactory


class DocumentStore:
    """Stores original document fields."""

    def __init__(self) -> None:
        """Initialize document store."""
        self._documents: dict[int, dict[str, Any]] = {}
        self._next_doc_id: int = 0

    def add_document(self, fields: dict[str, Any]) -> int:
        """Add document and return its ID."""
        doc_id = self._next_doc_id
        self._documents[doc_id] = fields.copy()
        self._next_doc_id += 1
        return doc_id

    def get_document(self, doc_id: int) -> dict[str, Any] | None:
        """Retrieve stored fields for a document."""
        return self._documents.get(doc_id)

    def delete_document(self, doc_id: int) -> None:
        """Remove document from store."""
        if doc_id in self._documents:
            del self._documents[doc_id]

    def update_document(self, doc_id: int, fields: dict[str, Any]) -> None:
        """Update document fields."""
        if doc_id not in self._documents:
            raise IndexError(f"Document {doc_id} not found")
        self._documents[doc_id].update(fields)

    def count(self) -> int:
        """Return number of documents."""
        return len(self._documents)


class InvertedIndex:
    """Core inverted index structure."""

    def __init__(self, config: IndexConfig) -> None:
        """Initialize inverted index."""
        self.config = config
        self.document_store = DocumentStore()

        # Term → postings list
        self._postings: dict[str, list[Posting]] = defaultdict(list)
        # Field-specific postings
        self._field_postings: dict[tuple[str, str], list[Posting]] = defaultdict(list)
        # Document statistics
        self._doc_lengths: dict[int, dict[str, int]] = {}
        self._field_doc_counts: dict[str, int] = defaultdict(int)
        # Analyzers per field
        self._analyzers: dict[str, Analyzer] = {}
        self._setup_analyzers()

    def _setup_analyzers(self) -> None:
        """Initialize analyzers for each field."""
        for field_name, mapping in self.config.field_mappings.items():
            if mapping.analyzed:
                self._analyzers[field_name] = AnalyzerFactory.create_standard()
            else:
                self._analyzers[field_name] = AnalyzerFactory.create_keyword()

    def add_document(self, doc_id: int, fields: dict[str, Any]) -> None:
        """Add document to index."""
        self.document_store._documents[doc_id] = fields.copy()
        self._doc_lengths[doc_id] = {}

        for field_name, value in fields.items():
            if field_name not in self.config.field_mappings:
                continue

            mapping = self.config.field_mappings[field_name]
            if not mapping.indexed:
                continue

            # Get analyzer and tokenize
            analyzer = self._analyzers.get(field_name, AnalyzerFactory.create_keyword())
            text = str(value)
            tokens = analyzer.analyze(text)

            # Build term frequencies and positions
            term_positions: dict[str, list[int]] = defaultdict(list)
            for token in tokens:
                term_positions[token.term].append(token.position)

            # Index terms
            self._doc_lengths[doc_id][field_name] = len(tokens)
            self._field_doc_counts[field_name] += 1

            for term, positions in term_positions.items():
                # Global posting
                existing = [p for p in self._postings[term] if p.doc_id == doc_id]
                if existing:
                    existing[0].term_frequency = len(positions)
                    existing[0].positions = positions
                else:
                    self._postings[term].append(
                        Posting(doc_id=doc_id, term_frequency=len(positions), positions=positions)
                    )

                # Field-specific posting
                field_key = (field_name, term)
                existing = [p for p in self._field_postings[field_key] if p.doc_id == doc_id]
                if existing:
                    existing[0].term_frequency = len(positions)
                    existing[0].positions = positions
                else:
                    self._field_postings[field_key].append(
                        Posting(doc_id=doc_id, term_frequency=len(positions), positions=positions)
                    )

    def delete_document(self, doc_id: int) -> None:
        """Remove document from index."""
        # Remove from postings
        for term in list(self._postings.keys()):
            self._postings[term] = [p for p in self._postings[term] if p.doc_id != doc_id]
            if not self._postings[term]:
                del self._postings[term]

        # Remove from field postings
        for key in list(self._field_postings.keys()):
            self._field_postings[key] = [p for p in self._field_postings[key] if p.doc_id != doc_id]
            if not self._field_postings[key]:
                del self._field_postings[key]

        # Update stats
        if doc_id in self._doc_lengths:
            del self._doc_lengths[doc_id]

        self.document_store.delete_document(doc_id)

    def update_document(self, doc_id: int, fields: dict[str, Any]) -> None:
        """Update document in index."""
        self.delete_document(doc_id)
        self.add_document(doc_id, fields)

    def get_postings(self, term: str) -> list[Posting]:
        """Get postings for a term."""
        return self._postings.get(term, [])

    def get_field_postings(self, field: str, term: str) -> list[Posting]:
        """Get field-specific postings."""
        return self._field_postings.get((field, term), [])

    def get_terms(self, field: str) -> set[str]:
        """Get all terms indexed in a field."""
        terms = set()
        for f, term in self._field_postings.keys():
            if f == field:
                terms.add(term)
        return terms

    def get_all_terms(self) -> set[str]:
        """Get all indexed terms."""
        return set(self._postings.keys())

    def get_doc_length(self, doc_id: int, field: str) -> int:
        """Get field length for document."""
        return self._doc_lengths.get(doc_id, {}).get(field, 0)

    def get_avg_doc_length(self, field: str) -> float:
        """Calculate average document length for field."""
        if field not in self._field_doc_counts or self._field_doc_counts[field] == 0:
            return 0.0
        total_length = sum(self._doc_lengths.get(doc_id, {}).get(field, 0) for doc_id in self._doc_lengths.keys())
        return total_length / self._field_doc_counts[field]

    def get_doc_frequency(self, term: str) -> int:
        """Get document frequency for a term."""
        return len(self.get_postings(term))

    def get_term_frequency(self, term: str) -> int:
        """Get total term frequency."""
        return sum(p.term_frequency for p in self.get_postings(term))

    def count_docs(self) -> int:
        """Return total document count."""
        return len(self.document_store._documents)

    def count_terms(self) -> int:
        """Return total unique terms."""
        return len(self._postings)

    def bulk_add_documents(self, documents: list[dict[str, Any]]) -> None:
        """Add multiple documents efficiently."""
        for i, doc in enumerate(documents):
            self.add_document(i, doc)

    def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "doc_count": self.count_docs(),
            "term_count": self.count_terms(),
            "field_counts": dict(self._field_doc_counts),
            "indexed_fields": list(self.config.field_mappings.keys()),
        }

    def serialize(self) -> str:
        """Serialize index to JSON."""
        data = {
            "postings": {
                term: [
                    {"doc_id": p.doc_id, "term_frequency": p.term_frequency, "positions": p.positions} for p in postings
                ]
                for term, postings in self._postings.items()
            },
            "doc_lengths": self._doc_lengths,
            "field_doc_counts": dict(self._field_doc_counts),
            "documents": self.document_store._documents,
        }
        return json.dumps(data)

    def deserialize(self, data: str) -> None:
        """Deserialize index from JSON."""
        parsed = json.loads(data)

        self._postings.clear()
        for term, postings_data in parsed.get("postings", {}).items():
            self._postings[term] = [
                Posting(doc_id=p["doc_id"], term_frequency=p["term_frequency"], positions=p["positions"])
                for p in postings_data
            ]

        self._doc_lengths = parsed.get("doc_lengths", {})
        self._field_doc_counts = defaultdict(int, parsed.get("field_doc_counts", {}))

        self.document_store._documents = parsed.get("documents", {})
        if self.document_store._documents:
            self.document_store._next_doc_id = max(int(k) for k in self.document_store._documents.keys()) + 1


class IndexSegment:
    """Represents a segment of the index."""

    def __init__(self, segment_id: int, config: IndexConfig) -> None:
        """Initialize index segment."""
        self.segment_id = segment_id
        self.index = InvertedIndex(config)
        self.doc_count = 0

    def is_full(self, segment_size: int) -> bool:
        """Check if segment has reached size limit."""
        return self.doc_count >= segment_size


class SegmentedIndex:
    """Index with segment management."""

    def __init__(self, config: IndexConfig) -> None:
        """Initialize segmented index."""
        self.config = config
        self.segments: list[IndexSegment] = []
        self._segment_id_counter = 0
        self._add_segment()

    def _add_segment(self) -> None:
        """Add new segment."""
        segment = IndexSegment(self._segment_id_counter, self.config)
        self.segments.append(segment)
        self._segment_id_counter += 1

    def add_document(self, fields: dict[str, Any]) -> int:
        """Add document to current segment."""
        current = self.segments[-1]
        doc_id = self.config.segment_size * len(self.segments) + current.doc_count
        current.index.add_document(doc_id, fields)
        current.doc_count += 1

        if current.is_full(self.config.segment_size):
            self._add_segment()

        return doc_id

    def search_all_segments(self, term: str) -> list[Posting]:
        """Search term across all segments."""
        results = []
        for segment in self.segments:
            results.extend(segment.index.get_postings(term))
        return results

    def merge_segments(self, segment_indices: list[int]) -> None:
        """Merge multiple segments."""
        if not segment_indices:
            return

        merged_config = self.config
        merged = InvertedIndex(merged_config)

        for idx in segment_indices:
            if idx < len(self.segments):
                segment = self.segments[idx]
                for doc_id, fields in segment.index.document_store._documents.items():
                    merged.add_document(doc_id, fields)

        # Replace first segment with merged
        self.segments[segment_indices[0]].index = merged

        # Remove other segments
        for idx in sorted(segment_indices[1:], reverse=True):
            del self.segments[idx]

    def count_docs(self) -> int:
        """Count documents across all segments."""
        return sum(segment.doc_count for segment in self.segments)
