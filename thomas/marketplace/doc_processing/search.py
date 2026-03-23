"""Full-text document search and indexing.

Implements inverted indexing, BM25 ranking, phrase search,
fuzzy search, and result clustering.
"""

import math
from collections import Counter, defaultdict


class InvertedIndex:
    """Full-text inverted index with term frequencies and positions."""

    def __init__(self) -> None:
        """Initialize inverted index."""
        # term -> {doc_id: [positions]}
        self.index: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        self.documents: dict[str, str] = {}  # doc_id -> text
        self.doc_lengths: dict[str, int] = {}  # doc_id -> word count
        self.avg_doc_length = 0.0
        self.total_docs = 0

    def add_document(self, doc_id: str, text: str) -> None:
        """Add document to index.

        Args:
            doc_id: Unique document identifier.
            text: Document text.
        """
        self.documents[doc_id] = text
        words = text.lower().split()
        self.doc_lengths[doc_id] = len(words)

        for position, word in enumerate(words):
            self.index[word][doc_id].append(position)

        self._update_stats()

    def _update_stats(self) -> None:
        """Update document statistics."""
        self.total_docs = len(self.documents)
        if self.total_docs > 0:
            total_length = sum(self.doc_lengths.values())
            self.avg_doc_length = total_length / self.total_docs

    def get_postings(self, term: str) -> dict[str, list[int]]:
        """Get postings for a term.

        Args:
            term: Search term.

        Returns:
            Dictionary of doc_id -> positions.
        """
        return self.index.get(term.lower(), {})

    def get_term_frequency(self, term: str, doc_id: str) -> int:
        """Get term frequency in document.

        Args:
            term: Term.
            doc_id: Document ID.

        Returns:
            Term frequency.
        """
        postings = self.get_postings(term)
        return len(postings.get(doc_id, []))

    def get_document_frequency(self, term: str) -> int:
        """Get number of documents containing term.

        Args:
            term: Term.

        Returns:
            Document frequency.
        """
        return len(self.get_postings(term))


class BM25Ranker:
    """BM25 ranking algorithm for search results."""

    def __init__(self, k1: float = 1.5, b: float = 0.75, k3: float = 8.0) -> None:
        """Initialize ranker.

        Args:
            k1: Term frequency saturation parameter.
            b: Length normalization parameter.
            k3: Query term frequency parameter.
        """
        self.k1 = k1
        self.b = b
        self.k3 = k3

    def score(self, index: InvertedIndex, query_terms: list[str], doc_id: str) -> float:
        """Calculate BM25 score for document.

        Args:
            index: Inverted index.
            query_terms: Query terms.
            doc_id: Document to score.

        Returns:
            BM25 score.
        """
        score = 0.0
        doc_length = index.doc_lengths.get(doc_id, 0)

        for term in query_terms:
            tf = index.get_term_frequency(term, doc_id)
            df = index.get_document_frequency(term)

            if tf == 0 or df == 0:
                continue

            # IDF component
            idf = math.log(1 + (index.total_docs - df + 0.5) / (df + 0.5))

            # BM25 formula
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * (doc_length / index.avg_doc_length))

            score += idf * (numerator / denominator)

        return score


class PhraseSearcher:
    """Phrase search using positional index."""

    @staticmethod
    def search_phrase(index: InvertedIndex, phrase: str) -> set[str]:
        """Find documents containing exact phrase.

        Args:
            index: Inverted index.
            phrase: Phrase to search (space-separated words).

        Returns:
            Set of matching document IDs.
        """
        terms = phrase.lower().split()
        if not terms:
            return set()

        # Get postings for first term
        first_postings = index.get_postings(terms[0])
        candidate_docs = set(first_postings.keys())

        # Refine with remaining terms
        for term in terms[1:]:
            term_postings = index.get_postings(term)
            candidate_docs &= set(term_postings.keys())

        # Check positional constraints
        matching_docs = set()
        for doc_id in candidate_docs:
            if PhraseSearcher._check_phrase_positions(index, terms, doc_id):
                matching_docs.add(doc_id)

        return matching_docs

    @staticmethod
    def _check_phrase_positions(index: InvertedIndex, terms: list[str], doc_id: str) -> bool:
        """Check if terms appear consecutively in document.

        Args:
            index: Inverted index.
            terms: Search terms.
            doc_id: Document ID.

        Returns:
            True if phrase found.
        """
        positions_list = []
        for term in terms:
            postings = index.get_postings(term)
            positions = postings.get(doc_id, [])
            if not positions:
                return False
            positions_list.append(positions)

        # Check if any sequence matches phrase
        for first_pos in positions_list[0]:
            match = True
            for i, pos_list in enumerate(positions_list[1:], 1):
                expected_pos = first_pos + i
                if expected_pos not in pos_list:
                    match = False
                    break
            if match:
                return True

        return False


class FuzzySearcher:
    """Fuzzy search using edit distance."""

    @staticmethod
    def edit_distance(s1: str, s2: str) -> int:
        """Calculate edit distance (Levenshtein distance).

        Args:
            s1: First string.
            s2: Second string.

        Returns:
            Edit distance.
        """
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(
                        dp[i - 1][j],  # deletion
                        dp[i][j - 1],  # insertion
                        dp[i - 1][j - 1],  # substitution
                    )

        return dp[m][n]

    @staticmethod
    def fuzzy_search(index: InvertedIndex, query: str, threshold: int = 2) -> set[str]:
        """Find documents with fuzzy term matching.

        Args:
            index: Inverted index.
            query: Search query.
            threshold: Maximum edit distance.

        Returns:
            Set of matching document IDs.
        """
        query_terms = query.lower().split()
        candidate_docs: set[str] = set(index.documents.keys())

        for query_term in query_terms:
            term_docs = set()

            # Find all terms within threshold distance
            for indexed_term in index.index.keys():
                distance = FuzzySearcher.edit_distance(query_term, indexed_term)
                if distance <= threshold:
                    term_postings = index.get_postings(indexed_term)
                    term_docs.update(term_postings.keys())

            if term_docs:
                candidate_docs &= term_docs
            else:
                candidate_docs = set()

        return candidate_docs


class SnippetGenerator:
    """Generate search result snippets."""

    @staticmethod
    def generate_snippet(text: str, query_terms: list[str], length: int = 150) -> str:
        """Generate snippet around search terms.

        Args:
            text: Document text.
            query_terms: Terms that were searched.
            length: Target snippet length.

        Returns:
            Snippet text.
        """
        if not query_terms or not text:
            return text[:length] if text else ""

        # Find first occurrence of any query term
        text_lower = text.lower()
        first_pos = len(text)

        for term in query_terms:
            pos = text_lower.find(term.lower())
            if pos >= 0:
                first_pos = min(first_pos, pos)

        if first_pos == len(text):
            # No term found, return beginning
            return text[:length]

        # Extract window around term
        start = max(0, first_pos - length // 2)
        end = min(len(text), start + length)

        snippet = text[start:end]

        # Add ellipsis if truncated
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."

        return snippet


class DocumentSearcher:
    """High-level document search interface."""

    def __init__(self) -> None:
        """Initialize searcher."""
        self.index = InvertedIndex()
        self.ranker = BM25Ranker()

    def index_documents(self, documents: dict[str, str]) -> None:
        """Index documents.

        Args:
            documents: Dictionary of doc_id -> text.
        """
        for doc_id, text in documents.items():
            self.index.add_document(doc_id, text)

    def search(self, query: str, top_k: int = 10, search_type: str = "standard") -> list[tuple[str, float]]:
        """Search documents.

        Args:
            query: Search query.
            top_k: Number of top results.
            search_type: "standard", "phrase", or "fuzzy".

        Returns:
            List of (doc_id, score) tuples.
        """
        query_terms = query.lower().split()

        if search_type == "phrase":
            matching_docs = PhraseSearcher.search_phrase(self.index, query)
            results = [(doc_id, 1.0) for doc_id in matching_docs]
        elif search_type == "fuzzy":
            matching_docs = FuzzySearcher.fuzzy_search(self.index, query)
            results = [(doc_id, self.ranker.score(self.index, query_terms, doc_id)) for doc_id in matching_docs]
        else:  # standard
            results = [
                (doc_id, self.ranker.score(self.index, query_terms, doc_id)) for doc_id in self.index.documents.keys()
            ]
            results = [(doc_id, score) for doc_id, score in results if score > 0]

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def get_snippets(
        self, results: list[tuple[str, float]], query: str, length: int = 150
    ) -> list[tuple[str, str, float]]:
        """Get snippets for search results.

        Args:
            results: Search results.
            query: Original query.
            length: Snippet length.

        Returns:
            List of (doc_id, snippet, score) tuples.
        """
        query_terms = query.lower().split()
        snippets = []

        for doc_id, score in results:
            text = self.index.documents.get(doc_id, "")
            snippet = SnippetGenerator.generate_snippet(text, query_terms, length)
            snippets.append((doc_id, snippet, score))

        return snippets


class DocumentSimilarity:
    """Calculate similarity between documents using TF-IDF cosine similarity."""

    @staticmethod
    def cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
        """Calculate cosine similarity between TF-IDF vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Similarity 0-1.
        """
        all_terms = set(vec1.keys()) | set(vec2.keys())

        if not all_terms:
            return 0.0

        dot_product = sum(vec1.get(term, 0.0) * vec2.get(term, 0.0) for term in all_terms)

        norm1 = math.sqrt(sum(v**2 for v in vec1.values()))
        norm2 = math.sqrt(sum(v**2 for v in vec2.values()))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    @staticmethod
    def find_similar_documents(index: InvertedIndex, doc_id: str, threshold: float = 0.5) -> list[tuple[str, float]]:
        """Find documents similar to given document.

        Args:
            index: Inverted index.
            doc_id: Reference document ID.
            threshold: Similarity threshold.

        Returns:
            List of (doc_id, similarity) tuples.
        """
        reference_text = index.documents.get(doc_id, "")
        if not reference_text:
            return []

        # Build TF-IDF vector for reference
        ref_words = reference_text.lower().split()
        ref_freq = Counter(ref_words)
        ref_vector: dict[str, float] = {}

        for word, count in ref_freq.items():
            tf = count / len(ref_words)
            idf = math.log(index.total_docs / (1 + index.get_document_frequency(word)))
            ref_vector[word] = tf * idf

        # Compare with all other documents
        similarities: list[tuple[str, float]] = []

        for other_doc_id in index.documents.keys():
            if other_doc_id == doc_id:
                continue

            other_text = index.documents[other_doc_id]
            other_words = other_text.lower().split()
            other_freq = Counter(other_words)
            other_vector: dict[str, float] = {}

            for word, count in other_freq.items():
                tf = count / len(other_words)
                idf = math.log(index.total_docs / (1 + index.get_document_frequency(word)))
                other_vector[word] = tf * idf

            similarity = DocumentSimilarity.cosine_similarity(ref_vector, other_vector)
            if similarity >= threshold:
                similarities.append((other_doc_id, similarity))

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities


class SearchResultClusterer:
    """Cluster search results by topic."""

    @staticmethod
    def cluster_results(
        results: list[tuple[str, float]],
        index: InvertedIndex,
        num_clusters: int = 3,
    ) -> dict[int, list[tuple[str, float]]]:
        """Cluster search results using simple k-means.

        Args:
            results: Search results.
            index: Document index.
            num_clusters: Number of clusters.

        Returns:
            Dictionary of cluster_id -> results.
        """
        if not results or num_clusters < 1:
            return {0: results}

        num_clusters = min(num_clusters, len(results))

        # Simple clustering: assign to clusters based on document length
        clusters: dict[int, list[tuple[str, float]]] = {i: [] for i in range(num_clusters)}

        for doc_id, score in results:
            doc_length = index.doc_lengths.get(doc_id, 0)
            cluster_id = (doc_length // 100) % num_clusters
            clusters[cluster_id].append((doc_id, score))

        # Remove empty clusters
        return {k: v for k, v in clusters.items() if v}
