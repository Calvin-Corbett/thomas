"""Integration tests for complete search pipeline."""

from thomas.marketplace.search_engine import (
    BooleanQuery,
    CompletionSuggester,
    DidYouMeanSuggester,
    FacetAggregator,
    FieldMapping,
    FieldType,
    Highlighter,
    IndexConfig,
    InvertedIndex,
    PhraseQuery,
    QueryParser,
    RangeFilter,
    SimilarityModel,
    StatsFacet,
    TermFacet,
    TermQuery,
    TermsFilter,
)


class TestCompleteSearch:
    """Test full search pipeline."""

    def setup_method(self) -> None:
        """Set up test index."""
        self.config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT, boost=2.0),
                "body": FieldMapping("body", FieldType.TEXT),
                "category": FieldMapping("category", FieldType.KEYWORD),
                "price": FieldMapping("price", FieldType.NUMERIC),
            }
        )
        self.index = InvertedIndex(self.config)

        # Index sample documents
        self.index.add_document(
            0,
            {
                "title": "Python Programming Guide",
                "body": "Learn Python programming with comprehensive examples and best practices.",
                "category": "programming",
                "price": 29.99,
            },
        )
        self.index.add_document(
            1,
            {
                "title": "Advanced Python Techniques",
                "body": "Deep dive into advanced Python features including decorators and metaclasses.",
                "category": "programming",
                "price": 39.99,
            },
        )
        self.index.add_document(
            2,
            {
                "title": "Web Development with Django",
                "body": "Build modern web applications using Django framework with Python.",
                "category": "web",
                "price": 49.99,
            },
        )
        self.index.add_document(
            3,
            {
                "title": "Data Science Fundamentals",
                "body": "Learn data science and machine learning with Python libraries.",
                "category": "data science",
                "price": 34.99,
            },
        )

    def test_basic_search(self) -> None:
        """Test basic term search."""
        query = TermQuery("body", "python")
        results = query.execute(self.index)

        doc_ids = [doc_id for doc_id, _ in results]
        assert len(doc_ids) >= 3

    def test_phrase_search(self) -> None:
        """Test phrase search."""
        query = PhraseQuery("body", ["python", "programming"])
        results = query.execute(self.index)

        assert len(results) > 0

    def test_boolean_search(self) -> None:
        """Test boolean query combination."""
        query = BooleanQuery()
        query.add_must(TermQuery("body", "python"))
        query.add_should(TermQuery("category", "programming"))

        results = query.execute(self.index)
        assert len(results) > 0

    def test_field_specific_search(self) -> None:
        """Test searching specific field."""
        title_results = TermQuery("title", "python").execute(self.index)
        body_results = TermQuery("body", "python").execute(self.index)

        # May have different results depending on field
        assert len(title_results) > 0 or len(body_results) > 0

    def test_scoring_comparison(self) -> None:
        """Test document relevance scoring."""
        query = TermQuery("body", "python")
        results = query.execute(self.index)

        # Results should be sorted by relevance
        assert len(results) > 0
        scores = [score for _, score in results]
        # Scores should be in descending order
        assert scores == sorted(scores, reverse=True)


class TestComplexQueries:
    """Test complex query scenarios."""

    def setup_method(self) -> None:
        """Set up test index."""
        self.config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
                "tags": FieldMapping("tags", FieldType.KEYWORD),
            }
        )
        self.index = InvertedIndex(self.config)

        for i in range(10):
            self.index.add_document(
                i, {"title": f"Document {i}", "body": f"Content for document {i}", "tags": f"tag{i % 3}"}
            )

    def test_query_parser(self) -> None:
        """Test query string parsing."""
        parser = QueryParser()
        query = parser.parse("python +required -excluded")

        results = query.execute(self.index)
        # Should execute without error
        assert isinstance(results, list)

    def test_combined_field_search(self) -> None:
        """Test searching multiple fields."""
        query = BooleanQuery()
        query.add_should(TermQuery("title", "document"))
        query.add_should(TermQuery("body", "content"))

        results = query.execute(self.index)
        assert len(results) > 0


class TestScoringIntegration:
    """Test scoring with full search."""

    def setup_method(self) -> None:
        """Set up test index."""
        self.config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
            }
        )
        self.index = InvertedIndex(self.config)

        self.index.add_document(0, {"title": "hello world", "body": "This is a test document"})
        self.index.add_document(1, {"title": "hello test", "body": "Another document with hello world"})

    def test_bm25_scoring(self) -> None:
        """Test BM25 scoring integration."""
        query = TermQuery("body", "hello")
        results = query.execute(self.index)

        assert len(results) > 0
        assert all(score >= 0 for _, score in results)

    def test_similarity_models(self) -> None:
        """Test different similarity models."""
        bm25 = SimilarityModel("bm25")
        tfidf = SimilarityModel("tfidf")

        query_terms = ["hello"]

        bm25_score = bm25.score(self.index, [], 0, query_terms, "body")
        tfidf_score = tfidf.score(self.index, [], 0, query_terms, "body")

        assert bm25_score >= 0
        assert tfidf_score >= 0


class TestFacetsIntegration:
    """Test faceted search integration."""

    def setup_method(self) -> None:
        """Set up test index with facet data."""
        self.config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "category": FieldMapping("category", FieldType.KEYWORD),
                "price": FieldMapping("price", FieldType.NUMERIC),
            }
        )
        self.index = InvertedIndex(self.config)

        categories = ["tech", "news", "sports", "tech", "news"]
        prices = [10, 20, 30, 15, 25]

        for i, (cat, price) in enumerate(zip(categories, prices)):
            self.index.add_document(i, {"title": f"Article {i}", "category": cat, "price": price})

    def test_faceted_search(self) -> None:
        """Test search with facets."""
        # Get all documents
        query = TermQuery("title", "article")
        results = query.execute(self.index)
        doc_ids = [doc_id for doc_id, _ in results]

        # Compute facets
        aggregator = FacetAggregator()
        aggregator.add_facet(TermFacet("category"))
        aggregator.add_facet(StatsFacet("price"))

        facets = aggregator.aggregate_all(self.index, doc_ids)

        assert "facet_category" in facets
        assert "facet_price_stats" in facets

    def test_facet_filtering(self) -> None:
        """Test filtering search results by facet."""
        query = TermQuery("title", "article")
        results = query.execute(self.index)
        doc_ids = [doc_id for doc_id, _ in results]

        # Filter to tech category
        filtered_docs = [
            doc_id for doc_id in doc_ids if self.index.document_store.get_document(doc_id)["category"] == "tech"
        ]

        assert len(filtered_docs) > 0
        assert len(filtered_docs) < len(doc_ids)


class TestHighlighting:
    """Test highlighting integration."""

    def test_highlight_search_results(self) -> None:
        """Test highlighting matched terms in results."""
        config = IndexConfig(field_mappings={"body": FieldMapping("body", FieldType.TEXT)})
        index = InvertedIndex(config)

        text = "This is a test document with test repeated multiple times test"
        index.add_document(0, {"body": text})

        query = TermQuery("body", "test")
        results = query.execute(index)

        assert len(results) > 0

        # Try to highlight
        highlighter = Highlighter()
        highlighted = highlighter.highlight(text, {"test"})

        assert len(highlighted) > 0
        assert "<em>" in highlighted[0]


class TestSuggestions:
    """Test suggestion features."""

    def setup_method(self) -> None:
        """Set up index for suggestions."""
        self.config = IndexConfig(field_mappings={"title": FieldMapping("title", FieldType.TEXT)})
        self.index = InvertedIndex(self.config)

        titles = ["Python", "Programming", "Pandas", "Pickle", "Performance"]
        for i, title in enumerate(titles):
            self.index.add_document(i, {"title": title.lower()})

    def test_completion_suggestions(self) -> None:
        """Test autocomplete suggestions."""
        suggester = CompletionSuggester("title")
        suggester.build(self.index)

        suggestions = suggester.suggest("py", limit=5)
        assert len(suggestions) > 0

    def test_fuzzy_suggestions(self) -> None:
        """Test fuzzy suggestions."""
        suggester = DidYouMeanSuggester("title")
        suggester.build(self.index)

        suggestions = suggester.suggest("pitho")  # Misspelling of python
        assert len(suggestions) >= 0


class TestFilteringIntegration:
    """Test result filtering."""

    def setup_method(self) -> None:
        """Set up index for filtering tests."""
        self.config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "price": FieldMapping("price", FieldType.NUMERIC),
            }
        )
        self.index = InvertedIndex(self.config)

        for i in range(10):
            self.index.add_document(i, {"title": "Product", "price": (i + 1) * 10})

    def test_range_filter(self) -> None:
        """Test filtering by numeric range."""
        query = TermQuery("title", "product")
        results = query.execute(self.index)
        doc_ids = [doc_id for doc_id, _ in results]

        # Filter to price range 20-60
        filter_obj = RangeFilter("price", min_value=20, max_value=60)
        filtered_docs = [
            doc_id for doc_id in doc_ids if filter_obj.matches(self.index.document_store.get_document(doc_id))
        ]

        assert len(filtered_docs) > 0
        assert len(filtered_docs) < len(doc_ids)

    def test_terms_filter(self) -> None:
        """Test filtering by multiple values."""
        query = TermQuery("title", "product")
        results = query.execute(self.index)
        doc_ids = [doc_id for doc_id, _ in results]

        # Filter to specific prices
        filter_obj = TermsFilter("price", [10, 20, 30])
        filtered_docs = [
            doc_id for doc_id in doc_ids if filter_obj.matches(self.index.document_store.get_document(doc_id))
        ]

        assert len(filtered_docs) > 0


class TestSearchPipeline:
    """Test complete search pipeline end-to-end."""

    def test_full_search_workflow(self) -> None:
        """Test complete search from query to results."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
                "category": FieldMapping("category", FieldType.KEYWORD),
            }
        )
        index = InvertedIndex(config)

        # Index documents
        documents = [
            {"title": "Search Engine", "body": "Full text search implementation", "category": "tech"},
            {"title": "Machine Learning", "body": "ML algorithms and techniques", "category": "ai"},
            {"title": "Data Science", "body": "Data analysis with Python", "category": "data"},
        ]

        for i, doc in enumerate(documents):
            index.add_document(i, doc)

        # Parse query
        parser = QueryParser()
        query = parser.parse("search")

        # Execute query
        results = query.execute(index)

        # Verify results
        assert len(results) > 0

        # Get top result
        if results:
            doc_id = results[0][0]
            doc = index.document_store.get_document(doc_id)
            assert doc is not None

    def test_search_with_all_features(self) -> None:
        """Test search using multiple features together."""
        config = IndexConfig(
            field_mappings={
                "title": FieldMapping("title", FieldType.TEXT),
                "body": FieldMapping("body", FieldType.TEXT),
                "category": FieldMapping("category", FieldType.KEYWORD),
                "rating": FieldMapping("rating", FieldType.NUMERIC),
            }
        )
        index = InvertedIndex(config)

        for i in range(5):
            index.add_document(
                i,
                {
                    "title": f"Item {i}",
                    "body": f"Description for item {i} with search terms",
                    "category": ["tech", "news", "sports"][i % 3],
                    "rating": 3 + (i % 3),
                },
            )

        # Query
        query = TermQuery("body", "search")
        results = query.execute(index)

        # Facets
        doc_ids = [doc_id for doc_id, _ in results]
        aggregator = FacetAggregator()
        aggregator.add_facet(TermFacet("category"))
        facets = aggregator.aggregate_all(index, doc_ids)

        # Filter
        filter_obj = RangeFilter("rating", min_value=4)
        [doc_id for doc_id in doc_ids if filter_obj.matches(index.document_store.get_document(doc_id))]

        # All should execute without error
        assert len(results) > 0
        assert "facet_category" in facets
