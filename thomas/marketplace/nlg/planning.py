"""Document planning: content selection and structuring.

Implements document planning algorithms including:
- Content selection using importance ranking
- Document structuring using Rhetorical Structure Theory
- Paragraph planning
- Content ordering strategies
- Content aggregation
"""

from dataclasses import dataclass
from typing import Any

from thomas.marketplace.nlg._exceptions import ContentSelectionError, DocumentPlanningError
from thomas.marketplace.nlg._types import (
    DiscourseStructure,
    RhetoricalRelation,
    Sentence,
    TextPlan,
)


@dataclass
class ContentItem:
    """Content item for planning."""

    id: str
    content: dict[str, Any]
    importance: float = 0.5
    category: str = "general"
    dependencies: list[str] = None
    frequency: int = 1

    def __post_init__(self) -> None:
        if self.dependencies is None:
            self.dependencies = []


class DocumentPlanner:
    """Plans document structure from structured data.

    Implements document planning including content selection, ordering,
    and document structuring using RST-based discourse trees.
    """

    def __init__(self) -> None:
        """Initialize document planner."""
        self.max_content_items: int = 1000
        self.importance_threshold: float = 0.1
        self.aggregation_threshold: float = 0.8

    def select_content(self, items: list[dict[str, Any]], budget: int = 50) -> list[dict[str, Any]]:
        """Select important content items within budget.

        Uses importance ranking to select the most relevant content
        while respecting a maximum budget of items.

        Args:
            items: Available content items with importance scores
            budget: Maximum number of items to select

        Returns:
            Ranked list of selected content items

        Raises:
            ContentSelectionError: If content selection fails
        """
        if not items:
            raise ContentSelectionError("No content items provided")

        if len(items) > self.max_content_items:
            raise ContentSelectionError(f"Too many content items: {len(items)}", len(items))

        # Score each item
        scored_items: list[tuple[dict[str, Any], float]] = []
        for item in items:
            score = self._score_item(item)
            if score >= self.importance_threshold:
                scored_items.append((item, score))

        # Sort by importance
        scored_items.sort(key=lambda x: x[1], reverse=True)

        # Select within budget
        selected = [item for item, _ in scored_items[:budget]]

        if not selected:
            raise ContentSelectionError("No items met importance threshold")

        return selected

    def _score_item(self, item: dict[str, Any]) -> float:
        """Score item importance (0-1).

        Args:
            item: Content item to score

        Returns:
            Importance score
        """
        score: float = 0.0

        # Explicit importance field
        if "importance" in item:
            if isinstance(item["importance"], (int, float)):
                score += min(item["importance"], 1.0) * 0.4

        # Category-based scoring
        category = item.get("category", "general")
        category_weights = {
            "main": 1.0,
            "supporting": 0.7,
            "detail": 0.4,
            "general": 0.5,
        }
        score += category_weights.get(category, 0.5) * 0.3

        # Frequency-based scoring
        if "frequency" in item and isinstance(item["frequency"], (int, float)):
            freq_score = min(item["frequency"] / 10.0, 1.0)
            score += freq_score * 0.2

        # Recency-based scoring
        if "recency" in item and isinstance(item["recency"], (int, float)):
            recency_score = max(0, min(1.0 - item["recency"] / 100.0, 1.0))
            score += recency_score * 0.1

        return min(score, 1.0)

    def structure_document(self, content: list[dict[str, Any]]) -> DiscourseStructure:
        """Structure content using RST discourse tree.

        Creates a discourse structure following Rhetorical Structure Theory,
        where nucleus sentences are connected to satellite sentences through
        rhetorical relations.

        Args:
            content: Selected content items

        Returns:
            Discourse structure tree

        Raises:
            DocumentPlanningError: If structuring fails
        """
        if not content:
            raise DocumentPlanningError("No content to structure")

        # Create sentences from content
        sentences: list[Sentence] = []
        for i, item in enumerate(content):
            sent = Sentence(
                id=f"S{i}",
                semantic_frames=[],
                salience=item.get("importance", 0.5),
            )
            sentences.append(sent)

        if len(sentences) == 1:
            return DiscourseStructure(nucleus=sentences[0])

        # Build discourse tree using hierarchical clustering
        tree = self._build_discourse_tree(sentences)

        if tree is None:
            raise DocumentPlanningError("Failed to build discourse tree")

        return tree

    def _build_discourse_tree(self, sentences: list[Sentence]) -> DiscourseStructure | None:
        """Build discourse tree using hierarchical clustering.

        Args:
            sentences: Sentences to structure

        Returns:
            Discourse structure tree or None
        """
        if not sentences:
            return None

        if len(sentences) == 1:
            return DiscourseStructure(nucleus=sentences[0])

        # Find most salient sentence as nucleus
        nucleus = max(sentences, key=lambda s: s.salience)
        satellites = [s for s in sentences if s != nucleus]

        # Create discourse tree
        tree = DiscourseStructure(nucleus=nucleus)

        # Assign satellites using basic heuristics
        for sat in satellites:
            if sat.salience > nucleus.salience * 0.8:
                relation = RhetoricalRelation.ELABORATION
            elif sat.salience > nucleus.salience * 0.5:
                relation = RhetoricalRelation.EXPLANATION
            else:
                relation = RhetoricalRelation.BACKGROUND

            sat_tree = DiscourseStructure(nucleus=sat)
            tree.add_satellite(relation, sat_tree)

        return tree

    def plan_paragraphs(self, sentences: list[Sentence], paragraph_size: int = 5) -> list[list[Sentence]]:
        """Plan paragraphs by grouping related sentences.

        Groups sentences into coherent paragraphs based on topic continuity
        and discourse relations.

        Args:
            sentences: Sentences to group
            paragraph_size: Target paragraph size

        Returns:
            List of paragraph groups
        """
        if not sentences:
            return []

        paragraphs: list[list[Sentence]] = []
        current_para: list[Sentence] = []
        current_topic = ""

        for sent in sentences:
            # Determine topic from semantic frames
            topic = ""
            if sent.semantic_frames:
                topic = sent.semantic_frames[0].predicate

            # Start new paragraph on topic change or size limit
            if current_para and (topic != current_topic or len(current_para) >= paragraph_size):
                paragraphs.append(current_para)
                current_para = []

            current_para.append(sent)
            current_topic = topic

        if current_para:
            paragraphs.append(current_para)

        return paragraphs

    def order_content(self, items: list[dict[str, Any]], strategy: str = "importance") -> list[int]:
        """Order content items using specified strategy.

        Args:
            items: Content items to order
            strategy: Ordering strategy ("importance", "chronological", "cause_effect")

        Returns:
            List of item indices in desired order

        Raises:
            DocumentPlanningError: If ordering fails
        """
        if not items:
            return []

        if strategy == "importance":
            return self._order_by_importance(items)
        elif strategy == "chronological":
            return self._order_chronological(items)
        elif strategy == "cause_effect":
            return self._order_cause_effect(items)
        else:
            raise DocumentPlanningError(f"Unknown ordering strategy: {strategy}")

    def _order_by_importance(self, items: list[dict[str, Any]]) -> list[int]:
        """Order items by importance score.

        Args:
            items: Items to order

        Returns:
            Item indices in order
        """
        scored = [(i, self._score_item(item)) for i, item in enumerate(items)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in scored]

    def _order_chronological(self, items: list[dict[str, Any]]) -> list[int]:
        """Order items chronologically.

        Args:
            items: Items to order

        Returns:
            Item indices in chronological order
        """
        indexed = [(i, item.get("timestamp", float("inf"))) for i, item in enumerate(items)]
        indexed.sort(key=lambda x: x[1])
        return [idx for idx, _ in indexed]

    def _order_cause_effect(self, items: list[dict[str, Any]]) -> list[int]:
        """Order items in cause-effect chains.

        Args:
            items: Items to order

        Returns:
            Item indices in cause-effect order
        """
        ordered: list[int] = []
        remaining = set(range(len(items)))

        while remaining:
            # Find items with no unsatisfied dependencies
            best_idx = None
            for idx in remaining:
                deps = items[idx].get("dependencies", [])
                if not deps or all(dep_id not in remaining for dep_id in deps):
                    best_idx = idx
                    break

            if best_idx is None:
                best_idx = remaining.pop()
            else:
                remaining.remove(best_idx)

            ordered.append(best_idx)

        return ordered

    def aggregate_content(self, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group similar content for aggregation.

        Identifies similar facts that can be combined in single sentences
        through conjunction and relative clauses.

        Args:
            items: Content items to aggregate

        Returns:
            List of aggregation groups
        """
        groups: list[list[dict[str, Any]]] = []

        for item in items:
            # Find similar items
            group_found = False
            for group in groups:
                if self._items_similar(item, group[0]):
                    group.append(item)
                    group_found = True
                    break

            if not group_found:
                groups.append([item])

        return groups

    def _items_similar(self, item1: dict[str, Any], item2: dict[str, Any]) -> bool:
        """Check if two items are similar.

        Args:
            item1: First item
            item2: Second item

        Returns:
            True if items are similar enough to aggregate
        """
        # Same category is primary similarity
        if item1.get("category") != item2.get("category"):
            return False

        # Calculate similarity based on shared predicates
        pred1 = item1.get("predicate", "")
        pred2 = item2.get("predicate", "")

        if pred1 and pred2 and pred1 == pred2:
            return True

        # Check semantic similarity
        similarity = self._semantic_similarity(item1, item2)
        return similarity >= self.aggregation_threshold

    def _semantic_similarity(self, item1: dict[str, Any], item2: dict[str, Any]) -> float:
        """Calculate semantic similarity between items.

        Args:
            item1: First item
            item2: Second item

        Returns:
            Similarity score (0-1)
        """
        similarity: float = 0.0

        # Same subject
        if item1.get("subject") == item2.get("subject"):
            similarity += 0.5

        # Same type
        if item1.get("type") == item2.get("type"):
            similarity += 0.3

        # Shared arguments
        args1 = set(item1.get("args", {}).values())
        args2 = set(item2.get("args", {}).values())
        if args1 and args2:
            overlap = len(args1 & args2) / len(args1 | args2)
            similarity += 0.2 * overlap

        return min(similarity, 1.0)

    def create_text_plan(self, content: list[dict[str, Any]], structure: DiscourseStructure) -> TextPlan:
        """Create a text plan from content and structure.

        Args:
            content: Selected content items
            structure: Discourse structure

        Returns:
            Text plan
        """
        plan = TextPlan()

        # Add content items
        for item in content:
            plan.add_content(item)

        # Set structure (sentence indices corresponding to discourse tree)
        plan.structure = list(range(len(content)))

        # Set ordering
        plan.ordering = self.order_content(content)

        # Set aggregation groups
        plan.aggregation_groups = [list(range(i, min(i + 2, len(content)))) for i in range(0, len(content), 2)]

        return plan
