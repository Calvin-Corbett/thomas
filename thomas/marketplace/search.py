"""Marketplace search with BM25 ranking, faceting, and autocomplete."""

import math
from dataclasses import dataclass, field
from decimal import Decimal

from thomas.marketplace._exceptions import InvalidSearchQuery
from thomas.marketplace._types import (
    Listing,
    ListingState,
    SearchQuery,
    SearchResult,
)


class BM25Ranker:
    """BM25 (Best Matching 25) ranking algorithm for full-text search."""

    K1: float = 1.5  # Term frequency saturation
    B: float = 0.75  # Field length normalization
    IDF_MIN: float = 0.1  # Minimum IDF value

    def __init__(self) -> None:
        """Initialize BM25 ranker."""
        self._documents: dict[str, list[str]] = {}
        self._idf_cache: dict[str, float] = {}
        self._avg_doc_length: float = 0.0
        self._total_docs: int = 0

    def index_document(self, doc_id: str, tokens: list[str]) -> None:
        """Index document for search.

        Args:
            doc_id: Document identifier.
            tokens: List of tokens from document.
        """
        self._documents[doc_id] = tokens
        self._total_docs = len(self._documents)

        # Recalculate average document length
        total_length = sum(len(doc) for doc in self._documents.values())
        self._avg_doc_length = total_length / self._total_docs if self._total_docs > 0 else 0

        # Clear IDF cache
        self._idf_cache.clear()

    def _calculate_idf(self, term: str) -> float:
        """Calculate inverse document frequency.

        Args:
            term: Search term.

        Returns:
            IDF score.
        """
        if term in self._idf_cache:
            return self._idf_cache[term]

        # Count documents containing term
        doc_count = sum(1 for tokens in self._documents.values() if term in tokens)

        # IDF formula: log(N / df + 0.5) / (log(N + 1) + 1)
        if doc_count == 0:
            idf = self.IDF_MIN
        else:
            idf = math.log((self._total_docs - doc_count + 0.5) / (doc_count + 0.5) + 1)

        self._idf_cache[term] = idf
        return idf

    def rank(self, query_tokens: list[str], doc_id: str) -> float:
        """Calculate BM25 relevance score for document against query.

        Args:
            query_tokens: List of query tokens.
            doc_id: Document identifier.

        Returns:
            Relevance score.
        """
        if doc_id not in self._documents:
            return 0.0

        doc_tokens = self._documents[doc_id]
        score = 0.0
        doc_length = len(doc_tokens)

        for term in query_tokens:
            term_freq = doc_tokens.count(term)
            if term_freq == 0:
                continue

            idf = self._calculate_idf(term)

            # BM25 formula
            numerator = term_freq * (self.K1 + 1)
            denominator = term_freq + self.K1 * (1 - self.B + self.B * doc_length / max(self._avg_doc_length, 1))

            score += idf * (numerator / denominator)

        return score


class SearchAutocomplete:
    """Prefix trie for search query autocomplete."""

    @dataclass
    class TrieNode:
        """Trie node for prefix matching."""

        children: dict[str, "SearchAutocomplete.TrieNode"] = field(default_factory=dict)
        is_end: bool = False
        query: str = ""
        frequency: int = 0

    def __init__(self) -> None:
        """Initialize autocomplete trie."""
        self._root = self.TrieNode()
        self._query_frequencies: dict[str, int] = {}

    def add_query(self, query: str) -> None:
        """Add query to autocomplete trie.

        Args:
            query: Search query to index.
        """
        query_lower = query.lower()
        self._query_frequencies[query_lower] = self._query_frequencies.get(query_lower, 0) + 1

        node = self._root
        for char in query_lower:
            if char not in node.children:
                node.children[char] = self.TrieNode()
            node = node.children[char]

        node.is_end = True
        node.query = query_lower
        node.frequency = self._query_frequencies[query_lower]

    def autocomplete(self, prefix: str, limit: int = 10) -> list[tuple[str, int]]:
        """Get autocomplete suggestions for prefix.

        Args:
            prefix: Query prefix.
            limit: Maximum suggestions to return.

        Returns:
            List of (query, frequency) tuples sorted by frequency.
        """
        prefix_lower = prefix.lower()
        node = self._root

        # Navigate to prefix end
        for char in prefix_lower:
            if char not in node.children:
                return []
            node = node.children[char]

        # Collect all queries with this prefix
        suggestions: list[tuple[str, int]] = []

        def dfs(current: SearchAutocomplete.TrieNode) -> None:
            """Depth-first search to collect suggestions."""
            if current.is_end:
                suggestions.append((current.query, current.frequency))

            for child in current.children.values():
                dfs(child)

        dfs(node)

        # Sort by frequency descending
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return suggestions[:limit]


class SearchIndex:
    """Full-text search index with BM25 ranking and faceting."""

    def __init__(self) -> None:
        """Initialize search index."""
        self._index: dict[str, BM25Ranker] = {}
        self._listings: dict[str, Listing] = {}
        self._autocomplete = SearchAutocomplete()
        self._query_analytics: dict[str, int] = {}
        self._zero_result_queries: set[str] = set()

    def index_listing(self, listing: Listing) -> None:
        """Index listing for search.

        Args:
            listing: Listing to index.
        """
        self._listings[listing.id] = listing

        # Index by field
        fields = ["title", "description", "category_id"]
        for field in fields:
            if field not in self._index:
                self._index[field] = BM25Ranker()

            tokens = self._tokenize(getattr(listing, field, ""))
            self._index[field].index_document(listing.id, tokens)

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into searchable tokens.

        Args:
            text: Text to tokenize.

        Returns:
            List of tokens.
        """
        return text.lower().split()

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute marketplace search with filtering and ranking.

        Args:
            query: Search query with filters.

        Returns:
            Ranked search results.

        Raises:
            InvalidSearchQuery: If query invalid.
        """
        if not query.q and not query.category_id:
            raise InvalidSearchQuery("Query string or category_id required")

        # Record query for analytics
        self._query_analytics[query.q] = self._query_analytics.get(query.q, 0) + 1
        self._autocomplete.add_query(query.q)

        # Get candidate listings
        candidates = self._filter_listings(query)

        if not candidates:
            self._zero_result_queries.add(query.q)
            return []

        # Score candidates
        results = []
        query_tokens = self._tokenize(query.q) if query.q else []

        for listing in candidates:
            # BM25 relevance score
            relevance = Decimal("0")
            if query_tokens and "title" in self._index:
                bm25_score = self._index["title"].rank(query_tokens, listing.id)
                relevance = Decimal(str(min(100, max(0, bm25_score * 10))))

            # Vendor score (stub)
            vendor_score = Decimal("80")

            # Listing quality
            quality = listing.quality_score

            # Combined score
            final_score = relevance * Decimal("0.4") + vendor_score * Decimal("0.3") + quality * Decimal("0.3")

            result = SearchResult(
                listing_id=listing.id,
                vendor_id=listing.vendor_id,
                title=listing.title,
                price=listing.price,
                rating=Decimal("4.5"),
                review_count=10,
                relevance_score=relevance,
                vendor_score=vendor_score,
                listing_quality=quality,
                is_sponsored=False,
                rank_position=0,
            )
            results.append(result)

        # Sort by final score
        results.sort(
            key=lambda r: (
                r.relevance_score * Decimal("0.4")
                + r.vendor_score * Decimal("0.3")
                + r.listing_quality * Decimal("0.3")
            ),
            reverse=True,
        )

        # Assign rank positions
        for i, result in enumerate(results[query.page - 1 : query.page - 1 + query.limit]):
            result.rank_position = i + 1

        return results[query.page - 1 : query.page - 1 + query.limit]

    def _filter_listings(self, query: SearchQuery) -> list[Listing]:
        """Filter listings by query criteria.

        Args:
            query: Search query.

        Returns:
            Filtered listings.
        """
        listings = [l for l in self._listings.values() if l.state == ListingState.PUBLISHED]

        # Category filter
        if query.category_id:
            listings = [l for l in listings if l.category_id == query.category_id]

        # Price range filter
        if query.price_min:
            listings = [l for l in listings if l.price >= query.price_min]
        if query.price_max:
            listings = [l for l in listings if l.price <= query.price_max]

        # Vendor filter
        if query.vendor_id:
            listings = [l for l in listings if l.vendor_id == query.vendor_id]

        # Rating filter
        if query.rating_min:
            # Stub: would pull from review system
            pass

        # Attribute filters
        for attr_key, attr_value in query.attributes.items():
            listings = [l for l in listings if l.attributes.get(attr_key) == attr_value]

        return listings

    def get_popular_queries(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get most popular search queries.

        Args:
            limit: Maximum queries to return.

        Returns:
            List of (query, count) tuples.
        """
        sorted_queries = sorted(self._query_analytics.items(), key=lambda x: x[1], reverse=True)
        return sorted_queries[:limit]

    def get_zero_result_queries(self, limit: int = 10) -> list[str]:
        """Get queries that returned no results.

        Args:
            limit: Maximum queries to return.

        Returns:
            List of zero-result queries.
        """
        return list(self._zero_result_queries)[:limit]

    def get_autocomplete_suggestions(self, prefix: str, limit: int = 10) -> list[str]:
        """Get autocomplete suggestions for query prefix.

        Args:
            prefix: Query prefix.
            limit: Maximum suggestions.

        Returns:
            List of suggested queries.
        """
        suggestions = self._autocomplete.autocomplete(prefix, limit)
        return [query for query, _ in suggestions]

    def correct_spelling(self, query: str, max_distance: int = 2) -> str | None:
        """Suggest spelling correction using edit distance.

        Args:
            query: Potentially misspelled query.
            max_distance: Maximum edit distance for suggestions.

        Returns:
            Suggested correction or None.
        """
        if query in self._query_analytics:
            return query

        # Find most popular query within edit distance
        best_match = None
        best_distance = max_distance + 1

        for known_query in self._query_analytics.keys():
            distance = self._edit_distance(query, known_query)
            if distance <= max_distance and distance < best_distance:
                best_distance = distance
                best_match = known_query

        return best_match

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between strings.

        Args:
            s1: First string.
            s2: Second string.

        Returns:
            Edit distance.
        """
        if len(s1) < len(s2):
            return SearchIndex._edit_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]
