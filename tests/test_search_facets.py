"""Tests for faceted search."""

from thomas.marketplace.search_engine import (
    DateHistogramFacet,
    FacetAggregator,
    FieldMapping,
    FieldType,
    HierarchicalFacet,
    IndexConfig,
    InvertedIndex,
    RangeFacet,
    StatsFacet,
    TermFacet,
)


class TestTermFacet:
    """Test term faceting."""

    def test_term_facet_aggregation(self) -> None:
        """Test term facet computation."""
        config = IndexConfig(field_mappings={"category": FieldMapping("category", FieldType.KEYWORD)})
        index = InvertedIndex(config)

        index.add_document(0, {"category": "tech"})
        index.add_document(1, {"category": "tech"})
        index.add_document(2, {"category": "news"})
        index.add_document(3, {"category": "news"})
        index.add_document(4, {"category": "sports"})

        facet = TermFacet("category")
        facet.aggregate(index, [0, 1, 2, 3, 4])

        assert facet.values["tech"] == 2
        assert facet.values["news"] == 2
        assert facet.values["sports"] == 1

    def test_facet_limit(self) -> None:
        """Test limiting facet results."""
        config = IndexConfig(field_mappings={"category": FieldMapping("category", FieldType.KEYWORD)})
        index = InvertedIndex(config)

        for i in range(15):
            index.add_document(i, {"category": f"cat_{i % 5}"})

        facet = TermFacet("category", limit=3)
        facet.aggregate(index, list(range(15)))

        result = facet.to_dict()
        assert len(result["values"]) <= 3
        assert "other" in result

    def test_facet_sorting(self) -> None:
        """Test facet value sorting by count."""
        config = IndexConfig(field_mappings={"category": FieldMapping("category", FieldType.KEYWORD)})
        index = InvertedIndex(config)

        index.add_document(0, {"category": "a"})
        index.add_document(1, {"category": "b"})
        index.add_document(2, {"category": "b"})
        index.add_document(3, {"category": "c"})
        index.add_document(4, {"category": "c"})
        index.add_document(5, {"category": "c"})

        facet = TermFacet("category")
        facet.aggregate(index, [0, 1, 2, 3, 4, 5])

        result = facet.to_dict()
        # Should be sorted by count descending
        assert result["values"][0]["count"] >= result["values"][1]["count"]


class TestRangeFacet:
    """Test range faceting."""

    def test_range_facet_aggregation(self) -> None:
        """Test range facet computation."""
        config = IndexConfig(field_mappings={"price": FieldMapping("price", FieldType.NUMERIC)})
        index = InvertedIndex(config)

        index.add_document(0, {"price": 5})
        index.add_document(1, {"price": 15})
        index.add_document(2, {"price": 25})
        index.add_document(3, {"price": 35})

        facet = RangeFacet("price")
        facet.add_range(0, 10)
        facet.add_range(10, 20)
        facet.add_range(20, 30)
        facet.add_range(30, 40)

        facet.aggregate(index, [0, 1, 2, 3])

        result = facet.to_dict()
        assert result["ranges"][0]["count"] == 1  # 0-10
        assert result["ranges"][1]["count"] == 1  # 10-20
        assert result["ranges"][2]["count"] == 1  # 20-30
        assert result["ranges"][3]["count"] == 1  # 30-40

    def test_range_facet_boundaries(self) -> None:
        """Test range boundary handling."""
        config = IndexConfig(field_mappings={"price": FieldMapping("price", FieldType.NUMERIC)})
        index = InvertedIndex(config)

        index.add_document(0, {"price": 10})
        index.add_document(1, {"price": 20})

        facet = RangeFacet("price")
        facet.add_range(0, 10)
        facet.add_range(10, 20)
        facet.add_range(20, 30)

        facet.aggregate(index, [0, 1])

        result = facet.to_dict()
        # 10 should be in [10, 20), 20 should be in [20, 30)
        assert result["ranges"][1]["count"] == 1  # 10 in [10, 20)
        assert result["ranges"][2]["count"] == 1  # 20 in [20, 30)


class TestDateHistogramFacet:
    """Test date histogram faceting."""

    def test_date_histogram_day(self) -> None:
        """Test daily date histogram."""
        config = IndexConfig(field_mappings={"date": FieldMapping("date", FieldType.DATE)})
        index = InvertedIndex(config)

        index.add_document(0, {"date": "2024-01-01"})
        index.add_document(1, {"date": "2024-01-01"})
        index.add_document(2, {"date": "2024-01-02"})

        facet = DateHistogramFacet("date", interval="day")
        facet.aggregate(index, [0, 1, 2])

        result = facet.to_dict()
        assert "2024-01-01" in [r["key"] for r in result["values"]]
        assert "2024-01-02" in [r["key"] for r in result["values"]]

    def test_date_histogram_month(self) -> None:
        """Test monthly date histogram."""
        config = IndexConfig(field_mappings={"date": FieldMapping("date", FieldType.DATE)})
        index = InvertedIndex(config)

        index.add_document(0, {"date": "2024-01-15"})
        index.add_document(1, {"date": "2024-02-15"})

        facet = DateHistogramFacet("date", interval="month")
        facet.aggregate(index, [0, 1])

        result = facet.to_dict()
        assert "2024-01" in [r["key"] for r in result["values"]]
        assert "2024-02" in [r["key"] for r in result["values"]]

    def test_date_histogram_year(self) -> None:
        """Test yearly date histogram."""
        config = IndexConfig(field_mappings={"date": FieldMapping("date", FieldType.DATE)})
        index = InvertedIndex(config)

        index.add_document(0, {"date": "2024-01-01"})
        index.add_document(1, {"date": "2025-01-01"})

        facet = DateHistogramFacet("date", interval="year")
        facet.aggregate(index, [0, 1])

        result = facet.to_dict()
        assert "2024" in [r["key"] for r in result["values"]]
        assert "2025" in [r["key"] for r in result["values"]]


class TestHierarchicalFacet:
    """Test hierarchical faceting."""

    def test_hierarchical_aggregation(self) -> None:
        """Test hierarchical facet computation."""
        config = IndexConfig(field_mappings={"path": FieldMapping("path", FieldType.KEYWORD)})
        index = InvertedIndex(config)

        index.add_document(0, {"path": "electronics/computers/laptops"})
        index.add_document(1, {"path": "electronics/computers/desktops"})
        index.add_document(2, {"path": "electronics/phones"})

        facet = HierarchicalFacet("path", separator="/")
        facet.aggregate(index, [0, 1, 2])

        result = facet.to_dict()
        assert "electronics" in result["hierarchy"]
        assert result["hierarchy"]["electronics"]["count"] == 3


class TestStatsFacet:
    """Test statistics faceting."""

    def test_stats_aggregation(self) -> None:
        """Test stats facet computation."""
        config = IndexConfig(field_mappings={"price": FieldMapping("price", FieldType.NUMERIC)})
        index = InvertedIndex(config)

        index.add_document(0, {"price": 10})
        index.add_document(1, {"price": 20})
        index.add_document(2, {"price": 30})

        facet = StatsFacet("price")
        facet.aggregate(index, [0, 1, 2])

        result = facet.to_dict()
        assert result["count"] == 3
        assert result["min"] == 10
        assert result["max"] == 30
        assert result["sum"] == 60
        assert result["avg"] == 20

    def test_stats_empty(self) -> None:
        """Test stats on empty set."""
        config = IndexConfig(field_mappings={"price": FieldMapping("price", FieldType.NUMERIC)})
        index = InvertedIndex(config)

        facet = StatsFacet("price")
        facet.aggregate(index, [])

        result = facet.to_dict()
        assert result["count"] == 0
        assert result["min"] is None


class TestFacetAggregator:
    """Test aggregating multiple facets."""

    def test_multiple_facets(self) -> None:
        """Test computing multiple facets together."""
        config = IndexConfig(
            field_mappings={
                "category": FieldMapping("category", FieldType.KEYWORD),
                "price": FieldMapping("price", FieldType.NUMERIC),
            }
        )
        index = InvertedIndex(config)

        index.add_document(0, {"category": "tech", "price": 100})
        index.add_document(1, {"category": "tech", "price": 200})
        index.add_document(2, {"category": "news", "price": 50})

        aggregator = FacetAggregator()
        aggregator.add_facet(TermFacet("category"))
        aggregator.add_facet(StatsFacet("price"))

        results = aggregator.aggregate_all(index, [0, 1, 2])

        assert "facet_category" in results
        assert "facet_price_stats" in results
        assert results["facet_price_stats"]["count"] == 3

    def test_get_facet(self) -> None:
        """Test retrieving facet by name."""
        aggregator = FacetAggregator()
        facet = TermFacet("category", name="my_facet")
        aggregator.add_facet(facet)

        retrieved = aggregator.get_facet("my_facet")
        assert retrieved is not None
        assert retrieved.field == "category"
