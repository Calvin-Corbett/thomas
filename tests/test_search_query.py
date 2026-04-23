"""Tests for query types and parsing."""

from thomas.marketplace.search_engine import (
    BooleanQuery,
    FieldMapping,
    FieldType,
    FuzzyQuery,
    IndexConfig,
    InvertedIndex,
    MatchAllQuery,
    PhraseQuery,
    PrefixQuery,
    QueryParser,
    RangeQuery,
    TermQuery,
    WildcardQuery,
)


class TestTermQuery:
    """Test term queries."""

    def test_simple_term_query(self) -> None:
        """Test basic term query."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        index.add_document(1, {"body": "hello test"})
        index.add_document(2, {"body": "goodbye world"})

        query = TermQuery("body", "hello")
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids
        assert 1 in doc_ids
        assert 2 not in doc_ids

    def test_term_query_boost(self) -> None:
        """Test term query with boost."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})

        query = TermQuery("body", "hello", boost=2.0)
        results = query.execute(index)

        assert results[0][1] == 1.0 * 2.0  # tf * boost

    def test_term_query_get_terms(self) -> None:
        """Test get_terms method."""
        query = TermQuery("body", "hello")
        terms = query.get_terms()

        assert "hello" in terms


class TestPhraseQuery:
    """Test phrase queries."""

    def test_exact_phrase(self) -> None:
        """Test exact phrase matching."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world test"})
        index.add_document(1, {"body": "hello test world"})

        query = PhraseQuery("body", ["hello", "world"])
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids

    def test_phrase_with_slop(self) -> None:
        """Test phrase matching with slop."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello beautiful world"})

        # With slop=1, should match with one word in between
        query = PhraseQuery("body", ["hello", "world"], slop=1)
        results = query.execute(index)

        assert len(results) > 0

    def test_phrase_get_terms(self) -> None:
        """Test get_terms for phrase."""
        query = PhraseQuery("body", ["hello", "world"])
        terms = query.get_terms()

        assert "hello" in terms
        assert "world" in terms


class TestBooleanQuery:
    """Test boolean queries."""

    def test_must_clause(self) -> None:
        """Test MUST clause."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        index.add_document(1, {"body": "hello test"})
        index.add_document(2, {"body": "world test"})

        query = BooleanQuery()
        query.add_must(TermQuery("body", "hello"))
        query.add_must(TermQuery("body", "world"))

        results = query.execute(index)
        doc_ids = [doc_id for doc_id, _ in results]

        assert 0 in doc_ids
        assert 1 not in doc_ids
        assert 2 not in doc_ids

    def test_should_clause(self) -> None:
        """Test SHOULD clause."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})
        index.add_document(1, {"body": "world"})
        index.add_document(2, {"body": "test"})

        query = BooleanQuery()
        query.add_should(TermQuery("body", "hello"))
        query.add_should(TermQuery("body", "world"))

        results = query.execute(index)
        doc_ids = [doc_id for doc_id, _ in results]

        assert 0 in doc_ids
        assert 1 in doc_ids
        assert 2 not in doc_ids

    def test_must_not_clause(self) -> None:
        """Test MUST NOT clause."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        index.add_document(1, {"body": "hello test"})
        index.add_document(2, {"body": "goodbye test"})

        query = BooleanQuery()
        query.add_should(TermQuery("body", "test"))
        query.add_must_not(TermQuery("body", "hello"))

        results = query.execute(index)
        doc_ids = [doc_id for doc_id, _ in results]

        assert 0 not in doc_ids
        assert 1 not in doc_ids
        assert 2 in doc_ids

    def test_combined_clauses(self) -> None:
        """Test combined must, should, must_not."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world beautiful"})
        index.add_document(1, {"body": "hello world ugly"})
        index.add_document(2, {"body": "hello ugly"})

        query = BooleanQuery()
        query.add_must(TermQuery("body", "hello"))
        query.add_should(TermQuery("body", "world"))
        query.add_must_not(TermQuery("body", "ugly"))

        results = query.execute(index)
        doc_ids = [doc_id for doc_id, _ in results]

        assert 0 in doc_ids
        assert 1 not in doc_ids


class TestWildcardQuery:
    """Test wildcard queries."""

    def test_wildcard_asterisk(self) -> None:
        """Test * wildcard."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello world"})
        index.add_document(1, {"body": "help test"})
        index.add_document(2, {"body": "world"})

        query = WildcardQuery("body", "hel*")
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids
        assert 1 in doc_ids

    def test_wildcard_question(self) -> None:
        """Test ? wildcard."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "cat"})
        index.add_document(1, {"body": "car"})
        index.add_document(2, {"body": "card"})

        query = WildcardQuery("body", "ca?")
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids
        assert 1 in doc_ids
        assert 2 not in doc_ids


class TestFuzzyQuery:
    """Test fuzzy queries."""

    def test_fuzzy_matching(self) -> None:
        """Test fuzzy string matching."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})
        index.add_document(1, {"body": "helo"})
        index.add_document(2, {"body": "world"})

        query = FuzzyQuery("body", "hello", max_edits=1)
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids
        assert 1 in doc_ids
        assert 2 not in doc_ids

    def test_levenshtein_distance(self) -> None:
        """Test Levenshtein distance calculation."""
        query = FuzzyQuery("body", "test")

        assert query._levenshtein_distance("test", "test") == 0
        assert query._levenshtein_distance("test", "best") == 1
        assert query._levenshtein_distance("test", "world") > 1


class TestPrefixQuery:
    """Test prefix queries."""

    def test_prefix_matching(self) -> None:
        """Test prefix matching."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})
        index.add_document(1, {"body": "help"})
        index.add_document(2, {"body": "world"})

        query = PrefixQuery("body", "hel")
        results = query.execute(index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert 0 in doc_ids
        assert 1 in doc_ids
        assert 2 not in doc_ids


class TestRangeQuery:
    """Test range queries."""

    def test_range_query_creation(self) -> None:
        """Test range query creation."""
        query = RangeQuery("price", min_value=10.0, max_value=100.0)

        assert query.field == "price"
        assert query.min_value == 10.0
        assert query.max_value == 100.0


class TestMatchAllQuery:
    """Test match all query."""

    def test_match_all(self) -> None:
        """Test matching all documents."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        index.add_document(0, {"body": "hello"})
        index.add_document(1, {"body": "world"})

        query = MatchAllQuery()
        results = query.execute(index)

        assert len(results) == 2


class TestQueryParser:
    """Test query string parsing."""

    def test_simple_term_parsing(self) -> None:
        """Test parsing simple term."""
        parser = QueryParser()
        query = parser.parse("hello")

        assert query is not None

    def test_phrase_parsing(self) -> None:
        """Test parsing phrase."""
        parser = QueryParser()
        query = parser.parse('"hello world"')

        assert isinstance(query, (PhraseQuery, BooleanQuery))

    def test_boolean_parsing(self) -> None:
        """Test parsing boolean operators."""
        parser = QueryParser()
        query = parser.parse("+required -excluded optional")

        assert isinstance(query, BooleanQuery)

    def test_field_query_parsing(self) -> None:
        """Test parsing field:term syntax."""
        parser = QueryParser()
        query = parser.parse("title:hello")

        assert isinstance(query, BooleanQuery)

    def test_empty_query(self) -> None:
        """Test parsing empty query."""
        parser = QueryParser()
        query = parser.parse("")

        assert isinstance(query, MatchAllQuery)

    def test_complex_query(self) -> None:
        """Test parsing complex query."""
        parser = QueryParser()
        query = parser.parse("+title:hello -body:world optional")

        assert isinstance(query, BooleanQuery)
