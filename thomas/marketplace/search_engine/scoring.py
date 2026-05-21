"""Scoring and ranking algorithms for search results."""

import math
from typing import Any

from ._types import Posting
from .index import InvertedIndex


class ScoringModel:
    """Base class for scoring models."""

    def score(
        self, index: InvertedIndex, postings: list[Posting], doc_id: int, query_terms: list[str], field: str
    ) -> float:
        """Calculate score for a document.

        Default implementation using BM25 algorithm with k1=1.2, b=0.75.
        Subclasses should override for alternative scoring schemes.

        Args:
            index: Inverted index for document statistics
            postings: Posting list for the current term
            doc_id: Document ID to score
            query_terms: List of query terms
            field: Field name being scored

        Returns:
            Float score for the document
        """
        # Default: use BM25 scoring
        bm25 = BM25(k1=1.2, b=0.75)
        return bm25.score(index, postings, doc_id, query_terms, field)


class BM25(ScoringModel):
    """BM25 probabilistic ranking function."""

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        """Initialize BM25 with parameters."""
        self.k1 = k1
        self.b = b

    def score(
        self, index: InvertedIndex, postings: list[Posting], doc_id: int, query_terms: list[str], field: str
    ) -> float:
        """Calculate BM25 score."""
        total_score = 0.0
        doc_length = index.get_doc_length(doc_id, field)
        avg_length = index.get_avg_doc_length(field)
        total_docs = index.count_docs()

        for term in query_terms:
            term_postings = index.get_field_postings(field, term)
            doc_posting = next((p for p in term_postings if p.doc_id == doc_id), None)

            if not doc_posting:
                continue

            term_freq = doc_posting.term_frequency
            doc_freq = len(term_postings)

            # IDF calculation
            idf = math.log((total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)

            # BM25 formula
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (
                1 - self.b + self.b * (doc_length / avg_length if avg_length > 0 else 0)
            )

            total_score += idf * (numerator / denominator)

        return total_score

    def explain(
        self, index: InvertedIndex, postings: list[Posting], doc_id: int, query_terms: list[str], field: str
    ) -> str:
        """Generate explanation for BM25 score."""
        explanations = []
        total_score = 0.0
        doc_length = index.get_doc_length(doc_id, field)
        avg_length = index.get_avg_doc_length(field)
        total_docs = index.count_docs()

        explanations.append(f"BM25 score for field '{field}':")
        explanations.append(f"  doc_length={doc_length}, avg_length={avg_length:.2f}")

        for term in query_terms:
            term_postings = index.get_field_postings(field, term)
            doc_posting = next((p for p in term_postings if p.doc_id == doc_id), None)

            if not doc_posting:
                continue

            term_freq = doc_posting.term_frequency
            doc_freq = len(term_postings)
            idf = math.log((total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
            numerator = term_freq * (self.k1 + 1)
            denominator = term_freq + self.k1 * (
                1 - self.b + self.b * (doc_length / avg_length if avg_length > 0 else 0)
            )
            term_score = idf * (numerator / denominator)
            total_score += term_score

            explanations.append(
                f"  term='{term}': tf={term_freq}, df={doc_freq}, idf={idf:.4f}, score={term_score:.4f}"
            )

        explanations.append(f"  total_score={total_score:.4f}")
        return "\n".join(explanations)


class TFIDF(ScoringModel):
    """TF-IDF ranking model."""

    def score(
        self, index: InvertedIndex, postings: list[Posting], doc_id: int, query_terms: list[str], field: str
    ) -> float:
        """Calculate TF-IDF score."""
        total_score = 0.0
        doc_length = index.get_doc_length(doc_id, field)
        total_docs = index.count_docs()

        if doc_length == 0:
            return 0.0

        for term in query_terms:
            term_postings = index.get_field_postings(field, term)
            doc_posting = next((p for p in term_postings if p.doc_id == doc_id), None)

            if not doc_posting:
                continue

            # Term frequency
            tf = doc_posting.term_frequency / doc_length

            # Inverse document frequency
            doc_freq = len(term_postings)
            idf = math.log(total_docs / (1 + doc_freq))

            total_score += tf * idf

        return total_score


class ScoreExplanation:
    """Detailed explanation of a score calculation."""

    def __init__(self, doc_id: int, base_score: float) -> None:
        """Initialize explanation."""
        self.doc_id = doc_id
        self.base_score = base_score
        self.field_scores: dict[str, float] = {}
        self.boost_factors: dict[str, float] = {}
        self.filter_penalty: float = 0.0

    def add_field_score(self, field: str, score: float) -> None:
        """Add field contribution."""
        self.field_scores[field] = score

    def add_boost(self, reason: str, factor: float) -> None:
        """Add boost factor."""
        self.boost_factors[reason] = factor

    def set_filter_penalty(self, penalty: float) -> None:
        """Set penalty from filters."""
        self.filter_penalty = penalty

    def get_final_score(self) -> float:
        """Calculate final score with boosts."""
        score = self.base_score
        for factor in self.boost_factors.values():
            score *= factor
        score -= self.filter_penalty
        return max(0.0, score)

    def to_string(self) -> str:
        """Generate explanation string."""
        lines = [f"Score explanation for doc_id={self.doc_id}:"]
        lines.append(f"  Base score: {self.base_score:.4f}")

        for field, score in self.field_scores.items():
            lines.append(f"  Field '{field}': {score:.4f}")

        for reason, factor in self.boost_factors.items():
            lines.append(f"  Boost ({reason}): {factor:.2f}x")

        if self.filter_penalty > 0:
            lines.append(f"  Filter penalty: -{self.filter_penalty:.4f}")

        lines.append(f"  Final score: {self.get_final_score():.4f}")
        return "\n".join(lines)


class SimilarityModel:
    """Configurable similarity calculation."""

    def __init__(self, model_type: str = "bm25", **kwargs: Any) -> None:
        """Initialize similarity model."""
        self.model_type = model_type

        if model_type == "bm25":
            self.model = BM25(k1=kwargs.get("k1", 1.2), b=kwargs.get("b", 0.75))
        elif model_type == "tfidf":
            self.model = TFIDF()
        else:
            raise ValueError(f"Unknown similarity model: {model_type}")

    def score(
        self,
        index: InvertedIndex,
        postings: list[Posting],
        doc_id: int,
        query_terms: list[str],
        field: str,
        field_boost: float = 1.0,
    ) -> float:
        """Score document with optional boost."""
        base_score = self.model.score(index, postings, doc_id, query_terms, field)
        return base_score * field_boost

    def explain(
        self, index: InvertedIndex, postings: list[Posting], doc_id: int, query_terms: list[str], field: str
    ) -> str:
        """Generate explanation if model supports it."""
        if hasattr(self.model, "explain"):
            return self.model.explain(index, postings, doc_id, query_terms, field)
        return f"Score: {self.score(index, postings, doc_id, query_terms, field):.4f}"


class FieldBoost:
    """Manages field-level boosting."""

    def __init__(self, boosts: dict[str, float] | None = None) -> None:
        """Initialize field boost map."""
        self.boosts = boosts or {}

    def get_boost(self, field: str) -> float:
        """Get boost factor for field."""
        return self.boosts.get(field, 1.0)

    def set_boost(self, field: str, boost: float) -> None:
        """Set boost for field."""
        self.boosts[field] = boost


class QueryTimeBoost:
    """Query-time relevance boosting."""

    def __init__(self) -> None:
        """Initialize query boost."""
        self.boosted_terms: dict[str, float] = {}
        self.field_boosted_terms: dict[tuple, float] = {}

    def boost_term(self, term: str, factor: float) -> None:
        """Boost specific term."""
        self.boosted_terms[term] = factor

    def boost_field_term(self, field: str, term: str, factor: float) -> None:
        """Boost term in specific field."""
        self.field_boosted_terms[(field, term)] = factor

    def get_term_boost(self, term: str) -> float:
        """Get boost for term."""
        return self.boosted_terms.get(term, 1.0)

    def get_field_term_boost(self, field: str, term: str) -> float:
        """Get boost for field:term combination."""
        return self.field_boosted_terms.get((field, term), self.get_term_boost(term))

    def apply_boosts(self, score: float, field: str, term: str) -> float:
        """Apply relevant boosts to score."""
        return score * self.get_field_term_boost(field, term)
