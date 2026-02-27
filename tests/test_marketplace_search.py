"""Tests for search module."""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import InvalidSearchQuery
from thomas.marketplace._types import (
    Listing,
    ListingState,
    SearchQuery,
)
from thomas.marketplace.search import (
    BM25Ranker,
    SearchAutocomplete,
    SearchIndex,
)


class TestBM25Ranker:
    """Test BM25 ranking algorithm."""

    def test_index_documents(self) -> None:
        """Test indexing documents."""
        ranker = BM25Ranker()

        ranker.index_document("doc1", ["laptop", "computer", "portable"])
        ranker.index_document("doc2", ["desktop", "computer", "large"])

        assert len(ranker._documents) == 2

    def test_rank_exact_match(self) -> None:
        """Test ranking with exact match."""
        ranker = BM25Ranker()

        ranker.index_document("doc1", ["laptop", "computer"])
        ranker.index_document("doc2", ["desktop", "monitor"])

        score1 = ranker.rank(["laptop"], "doc1")
        score2 = ranker.rank(["laptop"], "doc2")

        assert score1 > score2

    def test_rank_partial_match(self) -> None:
        """Test ranking with partial match."""
        ranker = BM25Ranker()

        ranker.index_document("doc1", ["laptop", "computer", "portable"])
        ranker.index_document("doc2", ["laptop"])

        score1 = ranker.rank(["laptop", "computer"], "doc1")
        score2 = ranker.rank(["laptop", "computer"], "doc2")

        assert score1 > score2


class TestSearchAutocomplete:
    """Test search query autocomplete."""

    def test_add_query(self) -> None:
        """Test adding query to trie."""
        autocomplete = SearchAutocomplete()

        autocomplete.add_query("laptop computer")
        autocomplete.add_query("laptop bag")

        assert len(autocomplete._query_frequencies) == 2

    def test_autocomplete_prefix(self) -> None:
        """Test autocomplete suggestions."""
        autocomplete = SearchAutocomplete()

        autocomplete.add_query("laptop computer")
        autocomplete.add_query("laptop bag")
        autocomplete.add_query("phone case")

        suggestions = autocomplete.autocomplete("laptop", limit=10)

        assert len(suggestions) == 2
        assert suggestions[0][0] in ["laptop computer", "laptop bag"]

    def test_autocomplete_empty_prefix(self) -> None:
        """Test autocomplete with no matches."""
        autocomplete = SearchAutocomplete()

        autocomplete.add_query("laptop")
        suggestions = autocomplete.autocomplete("xyz", limit=10)

        assert len(suggestions) == 0

    def test_autocomplete_frequency_ordering(self) -> None:
        """Test suggestions ordered by frequency."""
        autocomplete = SearchAutocomplete()

        autocomplete.add_query("laptop computer")
        autocomplete.add_query("laptop bag")
        autocomplete.add_query("laptop computer")
        autocomplete.add_query("laptop computer")

        suggestions = autocomplete.autocomplete("laptop", limit=10)

        assert suggestions[0][0] == "laptop computer"
        assert suggestions[0][1] > suggestions[1][1]


class TestSearchIndex:
    """Test search indexing and ranking."""

    def test_index_listing(self) -> None:
        """Test indexing listing."""
        index = SearchIndex()

        listing = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Laptop Computer",
            description="Portable laptop for work",
            price=Decimal("999.99"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        index.index_listing(listing)
        assert listing.id in index._listings

    def test_search_by_title(self) -> None:
        """Test searching by title."""
        index = SearchIndex()

        listing = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Laptop Computer",
            description="Portable laptop",
            price=Decimal("999.99"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        index.index_listing(listing)

        query = SearchQuery(q="laptop")
        results = index.search(query)

        assert len(results) > 0
        assert results[0].listing_id == "list_1"

    def test_search_with_category_filter(self) -> None:
        """Test searching with category filter."""
        index = SearchIndex()

        listing1 = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Laptop Computer",
            description="Portable laptop",
            price=Decimal("999.99"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        listing2 = Listing(
            id="list_2",
            vendor_id="vendor_2",
            product_id="prod_2",
            state=ListingState.PUBLISHED,
            title="Laptop Bag",
            description="Carrying bag for laptop",
            price=Decimal("49.99"),
            quantity=50,
            category_id="cat_accessories",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("70"),
        )

        index.index_listing(listing1)
        index.index_listing(listing2)

        query = SearchQuery(q="laptop", category_id="cat_electronics")
        results = index.search(query)

        assert len(results) == 1
        assert results[0].listing_id == "list_1"

    def test_search_with_price_range(self) -> None:
        """Test searching with price range filter."""
        index = SearchIndex()

        listing1 = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Expensive Laptop",
            description="High-end laptop",
            price=Decimal("2000"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        listing2 = Listing(
            id="list_2",
            vendor_id="vendor_2",
            product_id="prod_2",
            state=ListingState.PUBLISHED,
            title="Budget Laptop",
            description="Budget-friendly laptop",
            price=Decimal("500"),
            quantity=50,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("75"),
        )

        index.index_listing(listing1)
        index.index_listing(listing2)

        query = SearchQuery(
            q="laptop",
            price_min=Decimal("400"),
            price_max=Decimal("600"),
        )
        results = index.search(query)

        assert len(results) == 1
        assert results[0].listing_id == "list_2"

    def test_search_no_query(self) -> None:
        """Test search with no query raises error."""
        index = SearchIndex()

        with pytest.raises(InvalidSearchQuery):
            index.search(SearchQuery(q=""))

    def test_get_popular_queries(self) -> None:
        """Test getting popular queries."""
        index = SearchIndex()

        listing = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Laptop",
            description="Laptop",
            price=Decimal("999.99"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        index.index_listing(listing)

        query = SearchQuery(q="laptop")
        index.search(query)
        index.search(query)
        index.search(query)

        index.search(SearchQuery(q="phone"))

        popular = index.get_popular_queries(limit=5)

        assert popular[0][0] == "laptop"
        assert popular[0][1] == 3

    def test_spelling_correction(self) -> None:
        """Test spelling correction."""
        index = SearchIndex()

        listing = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.PUBLISHED,
            title="Laptop",
            description="Laptop",
            price=Decimal("999.99"),
            quantity=10,
            category_id="cat_electronics",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            quality_score=Decimal("80"),
        )

        index.index_listing(listing)
        index.search(SearchQuery(q="laptop"))

        suggestion = index.correct_spelling("laptop")
        assert suggestion == "laptop"

        suggestion = index.correct_spelling("lapto", max_distance=1)
        assert suggestion == "laptop"
