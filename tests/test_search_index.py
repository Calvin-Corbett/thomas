"""Tests for inverted index."""

import json

from thomas.marketplace.search_engine import (
    FieldMapping,
    FieldType,
    IndexConfig,
    InvertedIndex,
    SegmentedIndex,
)


class TestDocumentStore:
    """Test document storage."""

    def test_add_document(self) -> None:
        """Test adding documents."""
        config = IndexConfig()
        index = InvertedIndex(config)

        fields = {"title": "Hello World", "body": "Test content"}
        doc_id = index.document_store.add_document(fields)

        assert doc_id == 0
        retrieved = index.document_store.get_document(doc_id)
        assert retrieved == fields

    def test_document_count(self) -> None:
        """Test document count."""
        config = IndexConfig()
        index = InvertedIndex(config)

        index.document_store.add_document({"title": "Doc 1"})
        index.document_store.add_document({"title": "Doc 2"})

        assert index.document_store.count() == 2

    def test_delete_document(self) -> None:
        """Test deleting documents."""
        config = IndexConfig()
        index = InvertedIndex(config)

        doc_id = index.document_store.add_document({"title": "Test"})
        index.document_store.delete_document(doc_id)

        assert index.document_store.get_document(doc_id) is None

    def test_update_document(self) -> None:
        """Test updating documents."""
        config = IndexConfig()
        index = InvertedIndex(config)

        doc_id = index.document_store.add_document({"title": "Old Title"})
        index.document_store.update_document(doc_id, {"title": "New Title"})

        doc = index.document_store.get_document(doc_id)
        assert doc["title"] == "New Title"


class TestInvertedIndex:
    """Test inverted index."""

    def test_index_document(self) -> None:
        """Test indexing a document."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
            }
        )
        index = InvertedIndex(config)

        fields = {"title": "hello world", "body": "test content"}
        index.add_document(0, fields)

        postings = index.get_postings("hello")
        assert len(postings) > 0
        assert postings[0].doc_id == 0

    def test_field_specific_indexing(self) -> None:
        """Test field-specific indexing."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
            }
        )
        index = InvertedIndex(config)

        index.add_document(0, {"title": "hello", "body": "world"})

        title_postings = index.get_field_postings("title", "hello")
        body_postings = index.get_field_postings("body", "hello")

        assert len(title_postings) > 0
        assert len(body_postings) == 0

    def test_term_frequency(self) -> None:
        """Test term frequency tracking."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "test test test"})

        postings = index.get_postings("test")
        assert postings[0].term_frequency == 3

    def test_positions_tracking(self) -> None:
        """Test position tracking."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world hello"})

        postings = index.get_field_postings("body", "hello")
        # After analysis, positions depend on filters
        assert len(postings[0].positions) > 0

    def test_delete_document(self) -> None:
        """Test deleting from index."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        postings_before = index.get_postings("hello")
        assert len(postings_before) > 0

        index.delete_document(0)
        postings_after = index.get_postings("hello")
        assert len(postings_after) == 0

    def test_update_document(self) -> None:
        """Test updating document."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        index.update_document(0, {"body": "goodbye world"})

        hello_postings = index.get_postings("hello")
        # "goodbye" stems to "goodby"
        goodbye_postings = index.get_postings("goodby")

        assert len(hello_postings) == 0
        assert len(goodbye_postings) > 0

    def test_get_doc_length(self) -> None:
        """Test document length calculation."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world test"})

        # Length depends on tokenization and filtering
        length = index.get_doc_length(0, "body")
        assert length > 0

    def test_get_doc_frequency(self) -> None:
        """Test document frequency."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})
        index.add_document(1, {"body": "hello world"})
        index.add_document(2, {"body": "world"})

        df = index.get_doc_frequency("hello")
        assert df == 2

    def test_term_count(self) -> None:
        """Test total term count."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        count = index.count_terms()
        assert count > 0

    def test_bulk_indexing(self) -> None:
        """Test bulk document indexing."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        docs = [{"body": "hello world"}, {"body": "test document"}, {"body": "another test"}]
        index.bulk_add_documents(docs)

        assert index.count_docs() == 3

    def test_statistics(self) -> None:
        """Test index statistics."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
            }
        )
        index = InvertedIndex(config)

        index.add_document(0, {"title": "hello", "body": "world"})
        stats = index.get_stats()

        assert stats["doc_count"] == 1
        assert stats["term_count"] > 0
        assert "title" in stats["indexed_fields"]

    def test_non_indexed_field(self) -> None:
        """Test that non-indexed fields are not indexed."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT, indexed=True),
                "stored": FieldMapping("stored", FieldType.TEXT, indexed=False),
            }
        )
        index = InvertedIndex(config)

        index.add_document(0, {"title": "hello", "stored": "test"})

        postings = index.get_postings("test")
        assert len(postings) == 0


class TestIndexSerialization:
    """Test index serialization."""

    def test_serialize_deserialize(self) -> None:
        """Test round-trip serialization."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})

        serialized = index.serialize()
        assert isinstance(serialized, str)

        # Create new index and deserialize
        index2 = InvertedIndex(config)
        index2.deserialize(serialized)

        postings = index2.get_postings("hello")
        assert len(postings) > 0

    def test_serialization_format(self) -> None:
        """Test that serialization produces JSON."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "test"})
        serialized = index.serialize()

        data = json.loads(serialized)
        assert "postings" in data
        assert "documents" in data


class TestSegmentedIndex:
    """Test segmented index."""

    def test_create_segments(self) -> None:
        """Test segment creation."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)}, segment_size=10)
        segmented = SegmentedIndex(config)

        assert len(segmented.segments) > 0

    def test_add_document_to_segment(self) -> None:
        """Test adding document to segment."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)}, segment_size=100)
        segmented = SegmentedIndex(config)

        doc_id = segmented.add_document({"body": "hello world"})
        assert doc_id >= 0

    def test_segment_overflow(self) -> None:
        """Test creating new segment when full."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)}, segment_size=2)
        segmented = SegmentedIndex(config)

        initial_segments = len(segmented.segments)

        segmented.add_document({"body": "doc1"})
        segmented.add_document({"body": "doc2"})
        segmented.add_document({"body": "doc3"})

        assert len(segmented.segments) > initial_segments

    def test_search_all_segments(self) -> None:
        """Test searching across segments."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)}, segment_size=2)
        segmented = SegmentedIndex(config)

        segmented.add_document({"body": "hello"})
        segmented.add_document({"body": "hello"})
        segmented.add_document({"body": "hello"})

        results = segmented.search_all_segments("hello")
        assert len(results) == 3

    def test_total_doc_count(self) -> None:
        """Test document count across segments."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)}, segment_size=2)
        segmented = SegmentedIndex(config)

        segmented.add_document({"body": "doc1"})
        segmented.add_document({"body": "doc2"})
        segmented.add_document({"body": "doc3"})

        assert segmented.count_docs() == 3
