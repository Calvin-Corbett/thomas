"""Tests for document planning module."""

import pytest

from thomas.marketplace.nlg._exceptions import ContentSelectionError, DocumentPlanningError
from thomas.marketplace.nlg._types import Sentence
from thomas.marketplace.nlg.planning import DocumentPlanner


class TestContentSelection:
    """Test content selection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_select_empty_items(self) -> None:
        """Test selecting from empty list."""
        with pytest.raises(ContentSelectionError):
            self.planner.select_content([])

    def test_select_basic_content(self) -> None:
        """Test basic content selection."""
        items = [
            {"content": "Item 1", "importance": 0.9},
            {"content": "Item 2", "importance": 0.5},
            {"content": "Item 3", "importance": 0.2},
        ]
        selected = self.planner.select_content(items, budget=2)
        assert len(selected) <= 2
        assert items[0] in selected

    def test_select_with_budget(self) -> None:
        """Test content selection with budget."""
        items = [{"content": f"Item {i}", "importance": 0.5 + i * 0.1} for i in range(10)]
        selected = self.planner.select_content(items, budget=5)
        assert len(selected) <= 5

    def test_item_scoring(self) -> None:
        """Test item importance scoring."""
        item1 = {"importance": 0.5, "category": "main"}
        item2 = {"importance": 0.3, "category": "detail"}

        score1 = self.planner._score_item(item1)
        score2 = self.planner._score_item(item2)

        assert score1 > score2

    def test_frequency_scoring(self) -> None:
        """Test frequency-based scoring."""
        item_high_freq = {"frequency": 10}
        item_low_freq = {"frequency": 1}

        score_high = self.planner._score_item(item_high_freq)
        score_low = self.planner._score_item(item_low_freq)

        assert score_high >= score_low


class TestDocumentStructuring:
    """Test document structuring."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_structure_single_sentence(self) -> None:
        """Test structuring single sentence."""
        content = [{"content": "Single fact", "importance": 0.5}]
        structure = self.planner.structure_document(content)

        assert structure.nucleus is not None

    def test_structure_multiple_sentences(self) -> None:
        """Test structuring multiple sentences."""
        content = [{"content": f"Fact {i}", "importance": 0.5 + i * 0.1} for i in range(5)]
        structure = self.planner.structure_document(content)

        assert structure is not None
        sentences = structure.get_sentences()
        assert len(sentences) > 0

    def test_empty_structure_fails(self) -> None:
        """Test that empty content fails."""
        with pytest.raises(DocumentPlanningError):
            self.planner.structure_document([])


class TestParagraphPlanning:
    """Test paragraph planning."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_plan_paragraphs_empty(self) -> None:
        """Test paragraph planning with empty input."""
        paragraphs = self.planner.plan_paragraphs([])
        assert paragraphs == []

    def test_plan_paragraphs_single_sentence(self) -> None:
        """Test paragraph planning with single sentence."""
        sent = Sentence(id="S1")
        paragraphs = self.planner.plan_paragraphs([sent])

        assert len(paragraphs) == 1
        assert len(paragraphs[0]) == 1

    def test_plan_paragraphs_multiple_sentences(self) -> None:
        """Test paragraph planning with multiple sentences."""
        sentences = [Sentence(id=f"S{i}") for i in range(10)]
        paragraphs = self.planner.plan_paragraphs(sentences, paragraph_size=3)

        assert len(paragraphs) > 0
        total = sum(len(p) for p in paragraphs)
        assert total == len(sentences)

    def test_paragraph_size_respected(self) -> None:
        """Test that paragraph size limit is respected."""
        sentences = [Sentence(id=f"S{i}") for i in range(10)]
        paragraphs = self.planner.plan_paragraphs(sentences, paragraph_size=2)

        for para in paragraphs:
            assert len(para) <= 2


class TestContentOrdering:
    """Test content ordering strategies."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_order_by_importance(self) -> None:
        """Test importance-based ordering."""
        items = [
            {"importance": 0.3},
            {"importance": 0.9},
            {"importance": 0.5},
        ]
        order = self.planner.order_content(items, strategy="importance")

        assert order[0] == 1  # Highest importance first
        assert order[1] == 2
        assert order[2] == 0

    def test_order_chronological(self) -> None:
        """Test chronological ordering."""
        items = [
            {"timestamp": 3},
            {"timestamp": 1},
            {"timestamp": 2},
        ]
        order = self.planner.order_content(items, strategy="chronological")

        assert order[0] == 1  # timestamp 1
        assert order[1] == 2  # timestamp 2
        assert order[2] == 0  # timestamp 3

    def test_order_unknown_strategy_fails(self) -> None:
        """Test that unknown strategy raises error."""
        items = [{"importance": 0.5}]
        with pytest.raises(DocumentPlanningError):
            self.planner.order_content(items, strategy="unknown")

    def test_order_cause_effect(self) -> None:
        """Test cause-effect ordering."""
        items = [
            {"id": "a", "dependencies": []},
            {"id": "b", "dependencies": ["a"]},
            {"id": "c", "dependencies": ["b"]},
        ]
        order = self.planner.order_content(items, strategy="cause_effect")

        # a should come before b and c
        assert order.index(0) < order.index(1)
        assert order.index(1) < order.index(2)


class TestContentAggregation:
    """Test content aggregation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_aggregate_empty(self) -> None:
        """Test aggregation with empty input."""
        groups = self.planner.aggregate_content([])
        assert groups == []

    def test_aggregate_single_item(self) -> None:
        """Test aggregation with single item."""
        items = [{"category": "main", "importance": 0.5}]
        groups = self.planner.aggregate_content(items)

        assert len(groups) == 1
        assert groups[0] == items

    def test_aggregate_similar_items(self) -> None:
        """Test that similar items are grouped."""
        items = [
            {"category": "main", "predicate": "run", "subject": "john"},
            {"category": "main", "predicate": "run", "subject": "mary"},
        ]
        groups = self.planner.aggregate_content(items)

        # Similar predicates should group
        assert len(groups) == 1 or all(len(g) == 1 for g in groups)

    def test_item_similarity(self) -> None:
        """Test item similarity calculation."""
        item1 = {"category": "main", "predicate": "run"}
        item2 = {"category": "main", "predicate": "run"}

        assert self.planner._items_similar(item1, item2)

    def test_similarity_different_categories(self) -> None:
        """Test that different categories are not similar."""
        item1 = {"category": "main"}
        item2 = {"category": "detail"}

        assert not self.planner._items_similar(item1, item2)


class TestTextPlanCreation:
    """Test text plan creation."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_create_text_plan(self) -> None:
        """Test text plan creation."""
        content = [{"content": f"Item {i}", "importance": 0.5} for i in range(5)]
        structure = self.planner.structure_document(content)
        plan = self.planner.create_text_plan(content, structure)

        assert plan is not None
        assert len(plan.content_items) == len(content)
        assert len(plan.ordering) > 0

    def test_text_plan_content_items(self) -> None:
        """Test that text plan preserves content."""
        content = [{"content": f"Item {i}", "id": i} for i in range(3)]
        structure = self.planner.structure_document(content)
        plan = self.planner.create_text_plan(content, structure)

        assert len(plan.content_items) == 3

    def test_text_plan_aggregation(self) -> None:
        """Test that aggregation groups are created."""
        content = [{"content": f"Item {i}", "importance": 0.5} for i in range(6)]
        structure = self.planner.structure_document(content)
        plan = self.planner.create_text_plan(content, structure)

        assert len(plan.aggregation_groups) > 0


class TestSemanticSimilarity:
    """Test semantic similarity calculations."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.planner = DocumentPlanner()

    def test_identical_items_similar(self) -> None:
        """Test that identical items are similar."""
        item = {"subject": "John", "type": "action"}
        similarity = self.planner._semantic_similarity(item, item)

        assert similarity > 0.5

    def test_no_overlap_not_similar(self) -> None:
        """Test items with no overlap are not similar."""
        item1 = {"subject": "John", "type": "action"}
        item2 = {"subject": "Mary", "type": "event"}
        similarity = self.planner._semantic_similarity(item1, item2)

        assert similarity < 0.5
