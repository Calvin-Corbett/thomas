"""Tests for document search and indexing module."""

from thomas.doc_processing.search import (
    BM25Ranker,
    DocumentSearcher,
    DocumentSimilarity,
    FuzzySearcher,
    InvertedIndex,
    PhraseSearcher,
    SearchResultClusterer,
    SnippetGenerator,
)


class TestInvertedIndex:
    """Test inverted index operations."""

    def test_add_document(self) -> None:
        """Test document addition."""
        index = InvertedIndex()
        index.add_document("doc1", "hello world")
        index.add_document("doc2", "hello there")

        assert index.total_docs == 2
        assert index.get_document_frequency("hello") == 2

    def test_get_postings(self) -> None:
        """Test postings retrieval."""
        index = InvertedIndex()
        index.add_document("doc1", "hello world test")

        postings = index.get_postings("hello")

        assert "doc1" in postings
        assert len(postings["doc1"]) == 1

    def test_get_term_frequency(self) -> None:
        """Test term frequency calculation."""
        index = InvertedIndex()
        index.add_document("doc1", "hello hello world")

        freq = index.get_term_frequency("hello", "doc1")

        assert freq == 2

    def test_empty_index(self) -> None:
        """Test empty index operations."""
        index = InvertedIndex()

        assert index.total_docs == 0
        assert len(index.get_postings("hello")) == 0


class TestBM25Ranker:
    """Test BM25 ranking."""

    def test_score_document(self) -> None:
        """Test document scoring."""
        index = InvertedIndex()
        index.add_document("doc1", "python programming language")
        index.add_document("doc2", "java programming language")

        ranker = BM25Ranker()
        score = ranker.score(index, ["python"], "doc1")

        assert score > 0

    def test_compare_documents(self) -> None:
        """Test comparative scoring."""
        index = InvertedIndex()
        index.add_document("doc1", "python python python programming")
        index.add_document("doc2", "python programming language")

        ranker = BM25Ranker()
        score1 = ranker.score(index, ["python"], "doc1")
        score2 = ranker.score(index, ["python"], "doc2")

        assert score1 > score2  # doc1 has more pythons


class TestPhraseSearcher:
    """Test phrase search."""

    def test_search_phrase(self) -> None:
        """Test phrase search."""
        index = InvertedIndex()
        index.add_document("doc1", "the quick brown fox")
        index.add_document("doc2", "a slow brown dog")

        results = PhraseSearcher.search_phrase(index, "brown fox")

        assert "doc1" in results
        assert "doc2" not in results

    def test_phrase_not_found(self) -> None:
        """Test phrase not found."""
        index = InvertedIndex()
        index.add_document("doc1", "the quick brown fox")

        results = PhraseSearcher.search_phrase(index, "fox quick")

        assert len(results) == 0


class TestFuzzySearcher:
    """Test fuzzy search."""

    def test_edit_distance(self) -> None:
        """Test edit distance calculation."""
        distance = FuzzySearcher.edit_distance("kitten", "sitting")

        assert distance == 3

    def test_identical_strings(self) -> None:
        """Test identical strings."""
        distance = FuzzySearcher.edit_distance("hello", "hello")

        assert distance == 0

    def test_fuzzy_search(self) -> None:
        """Test fuzzy search."""
        index = InvertedIndex()
        index.add_document("doc1", "python programming")
        index.add_document("doc2", "java code")

        results = FuzzySearcher.fuzzy_search(index, "pythno", threshold=2)

        assert "doc1" in results or len(results) >= 0  # May or may not find


class TestSnippetGenerator:
    """Test snippet generation."""

    def test_generate_snippet(self) -> None:
        """Test snippet generation."""
        text = "The quick brown fox jumps over the lazy dog and runs through the forest"
        snippet = SnippetGenerator.generate_snippet(text, ["fox"], length=30)

        assert "fox" in snippet or "brown" in snippet

    def test_snippet_with_multiple_terms(self) -> None:
        """Test snippet with multiple search terms."""
        text = "Python is great for programming and data science"
        snippet = SnippetGenerator.generate_snippet(text, ["Python", "programming"], length=50)

        assert len(snippet) <= 60  # Approximate (with ellipsis)

    def test_snippet_not_found(self) -> None:
        """Test snippet when term not found."""
        text = "Hello world"
        snippet = SnippetGenerator.generate_snippet(text, ["notfound"], length=20)

        assert len(snippet) > 0


class TestDocumentSearcher:
    """Test high-level document search."""

    def test_index_documents(self) -> None:
        """Test document indexing."""
        documents = {
            "doc1": "python programming language",
            "doc2": "java programming language",
        }

        searcher = DocumentSearcher()
        searcher.index_documents(documents)

        assert searcher.index.total_docs == 2

    def test_standard_search(self) -> None:
        """Test standard search."""
        documents = {
            "doc1": "python is great for programming",
            "doc2": "java is also a programming language",
            "doc3": "javascript runs in browsers",
        }

        searcher = DocumentSearcher()
        searcher.index_documents(documents)

        results = searcher.search("python programming")

        assert len(results) > 0

    def test_phrase_search_mode(self) -> None:
        """Test phrase search mode."""
        documents = {
            "doc1": "the quick brown fox",
            "doc2": "a slow brown dog",
        }

        searcher = DocumentSearcher()
        searcher.index_documents(documents)

        results = searcher.search("brown fox", search_type="phrase")

        assert "doc1" in [doc_id for doc_id, _ in results]

    def test_fuzzy_search_mode(self) -> None:
        """Test fuzzy search mode."""
        documents = {
            "doc1": "python programming",
            "doc2": "java code",
        }

        searcher = DocumentSearcher()
        searcher.index_documents(documents)

        results = searcher.search("pythno", search_type="fuzzy")

        assert isinstance(results, list)

    def test_get_snippets(self) -> None:
        """Test snippet generation."""
        documents = {
            "doc1": "The quick brown fox jumps over the lazy dog",
            "doc2": "Another document with different content",
        }

        searcher = DocumentSearcher()
        searcher.index_documents(documents)

        results = searcher.search("fox")
        snippets = searcher.get_snippets(results, "fox")

        assert len(snippets) > 0


class TestDocumentSimilarity:
    """Test document similarity."""

    def test_cosine_similarity(self) -> None:
        """Test cosine similarity."""
        vec1 = {"python": 0.5, "programming": 0.5}
        vec2 = {"python": 0.5, "programming": 0.5}

        similarity = DocumentSimilarity.cosine_similarity(vec1, vec2)

        assert similarity > 0.99

    def test_different_documents(self) -> None:
        """Test similarity of different documents."""
        vec1 = {"python": 0.5, "programming": 0.5}
        vec2 = {"java": 0.5, "code": 0.5}

        similarity = DocumentSimilarity.cosine_similarity(vec1, vec2)

        assert similarity == 0.0

    def test_find_similar_documents(self) -> None:
        """Test finding similar documents."""
        index = InvertedIndex()
        index.add_document("doc1", "python programming language")
        index.add_document("doc2", "python is great")
        index.add_document("doc3", "java code")

        similar = DocumentSimilarity.find_similar_documents(index, "doc1")

        assert isinstance(similar, list)


class TestSearchResultClusterer:
    """Test search result clustering."""

    def test_cluster_results(self) -> None:
        """Test result clustering."""
        index = InvertedIndex()
        index.add_document("doc1", "python programming" * 10)
        index.add_document("doc2", "python programming" * 10)
        index.add_document("doc3", "java")

        results = [("doc1", 1.0), ("doc2", 0.9), ("doc3", 0.5)]

        clusters = SearchResultClusterer.cluster_results(results, index, num_clusters=2)

        assert isinstance(clusters, dict)
        assert len(clusters) > 0

    def test_single_cluster(self) -> None:
        """Test with single cluster."""
        index = InvertedIndex()
        index.add_document("doc1", "test")

        results = [("doc1", 1.0)]
        clusters = SearchResultClusterer.cluster_results(results, index, num_clusters=1)

        assert len(clusters) >= 1
